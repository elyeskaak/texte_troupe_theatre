"""
Étape 1 — OCR Vision : `<Livre>.pdf` → `<Livre>_OCR.txt`.

Parcourt les PDF du dossier de travail, rasterise chaque page, la soumet à un
modèle vision via la Responses API, et assemble les transcriptions.

**L'unité de reprise est la page.** Chaque page est écrite dès qu'elle est
obtenue, avec son sidecar. Une coupure de Colab ne coûte donc au maximum qu'un
seul appel, et une relance reprend exactement là où elle s'était arrêtée.

Trois choix méritent d'être signalés.

**L'assemblage est refait à chaque exécution.** C'est une opération locale et
gratuite qui garantit que `OCR.txt` reflète toujours l'état réel du cache, y
compris après une reprise partielle. On ne cherche jamais à « compléter » un
fichier existant, ce qui serait la principale source d'incohérence.

**Une page qui échoue n'interrompt pas le livre.** Elle est marquée en échec,
signalée dans le récapitulatif, et un marqueur visible est inséré dans
`OCR.txt` afin que le trou soit repérable plutôt que silencieux. Perdre 288
pages parce que la page 96 est illisible serait absurde.

**Le modèle ne corrige rien.** C'est le prompt qui l'impose, et c'est la
condition de possibilité de l'étape 3 : `OCR.txt` est la référence de vérité qui
permettra de détecter ce que l'édition aurait perdu.

**Une couche texte déjà présente est réutilisée si elle est bonne.** Beaucoup de
PDF ont déjà été passés à l'OCR par un scanner ou par Acrobat : les repasser au
modèle vision serait payer deux fois. Mais une couche texte n'est pas forcément
exploitable — accents dépouillés, ligatures, ordre de lecture faux — et s'en
servir à tort dégraderait tout le livre. Les contrôles de
`blocks.evaluer_couche_texte()` sont donc sévères, et le doute renvoie à l'OCR
Vision. `diagnostiquer_couches_texte()` permet de savoir, gratuitement et avant
de lancer, combien de pages seront réellement facturées.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from theatre_editor import config
from theatre_editor.utils import api, blocks, io
from theatre_editor.utils import logging as journalisation

NOM_ETAPE = "ocr"

# Statuts d'une page, tels que remontés à la boucle appelante.
PAGE_TERMINEE = "terminee"
PAGE_SAUTEE = "sautee"
PAGE_SUSPECTE = "suspecte"
PAGE_ECHOUEE = "echouee"

# Pages traitées sans aucun appel API.
PAGE_COUCHE_TEXTE = "couche_texte"
PAGE_BLANCHE = "blanche"

# Origine du texte d'une page, consignée dans son sidecar.
SOURCE_VISION = "vision"
SOURCE_COUCHE_TEXTE = "couche_texte"
SOURCE_PAGE_BLANCHE = "page_blanche"

# Statuts n'ayant coûté aucun appel : ni pause à respecter, ni jeton consommé.
STATUTS_SANS_APPEL = frozenset({PAGE_SAUTEE, PAGE_COUCHE_TEXTE, PAGE_BLANCHE})


# ============================================================
# 1. RÉSULTATS
# ============================================================


@dataclass
class ResultatLivre:
    """Bilan du traitement d'un PDF."""

    nom: str
    statut: str = config.STATUT_TERMINE
    # Pages du PDF, et pages effectivement retenues : les deux diffèrent
    # lorsqu'une limite d'essai est active.
    pages_du_pdf: int = 0
    pages_totales: int = 0
    pages_traitees: int = 0
    pages_sautees: int = 0
    pages_suspectes: int = 0
    pages_couche_texte: int = 0
    pages_blanches: int = 0
    pages_echouees: int = 0
    duree_secondes: float = 0.0
    erreur: str | None = None
    numeros_echoues: list[int] = field(default_factory=list)

    @property
    def complet(self) -> bool:
        """Vrai si aucune page ne reste à reprendre."""
        return self.pages_echouees == 0 and self.pages_suspectes == 0

    def champs_journal(self) -> dict[str, Any]:
        """Bilan à consigner dans le journal de l'étape."""
        return {
            "statut": self.statut,
            "pages_du_pdf": self.pages_du_pdf,
            "pages_totales": self.pages_totales,
            "pages_traitees": self.pages_traitees,
            "pages_couche_texte": self.pages_couche_texte,
            "pages_blanches": self.pages_blanches,
            "pages_sautees": self.pages_sautees,
            "pages_suspectes": self.pages_suspectes,
            "pages_echouees": self.pages_echouees,
            "numeros_echoues": self.numeros_echoues,
            "duree_secondes": self.duree_secondes,
            "erreur": self.erreur,
        }


# ============================================================
# 2. RASTERISATION
# ============================================================


@lru_cache(maxsize=1)
def _module_pymupdf():
    """
    Importe PyMuPDF à la demande.

    Le module s'appelle `pymupdf` depuis la version 1.24, et `fitz` avant :
    les deux noms sont tentés. L'import est différé pour que ce module
    s'importe sur une machine sans PyMuPDF, ce qui permet de tester la logique
    d'assemblage et de reprise hors ligne.
    """
    try:
        import pymupdf

        return pymupdf
    except ImportError:
        pass

    try:
        import fitz

        return fitz
    except ImportError as erreur:  # pragma: no cover - dépend de l'environnement
        raise RuntimeError(
            "PyMuPDF est introuvable.\n"
            "Installez-le :  pip install -U pymupdf"
        ) from erreur


def ouvrir_pdf(chemin: Path):
    """
    Ouvre un PDF.

    Raises:
        RuntimeError: message explicite si le fichier est illisible ou chiffré,
            plutôt que l'exception brute de PyMuPDF.
    """
    try:
        return _module_pymupdf().open(str(chemin))
    except Exception as erreur:
        raise RuntimeError(
            f"PDF illisible : {chemin.name}\n"
            f"    {erreur}\n"
            "Le fichier est peut-être corrompu, ou protégé par un mot de passe."
        ) from erreur


def rasteriser_page(page: Any, dpi: int) -> bytes:
    """Rend une page en PNG à la résolution demandée."""
    return page.get_pixmap(dpi=dpi).tobytes("png")


# Table de traduction comptant les octets d'encre en une seule passe C.
# Une boucle Python sur les octets d'un pixmap coûterait des dixièmes de
# seconde par page, soit près d'une minute sur un livre entier.
_TABLE_ENCRE = bytes(255 if valeur < config.SEUIL_ENCRE else 0 for valeur in range(256))


def proportion_encre(page: Any, dpi: int | None = None) -> float:
    """
    Mesure la part d'encre d'une page, entre 0 et 1.

    Rasterise à très basse résolution : une page blanche l'est à toute
    résolution, et le test devient instantané.

    Returns:
        La proportion d'octets sombres. **1.0 en cas d'échec**, afin qu'une page
        illisible ne soit jamais prise pour blanche — mieux vaut payer un appel
        que perdre une page imprimée.
    """
    resolution = dpi if dpi is not None else config.DPI_TEST_BLANCHEUR

    try:
        echantillons = page.get_pixmap(dpi=resolution).samples
    except Exception:
        return 1.0

    if not echantillons:
        return 1.0

    return echantillons.translate(_TABLE_ENCRE).count(255) / len(echantillons)


def page_blanche(page: Any) -> bool:
    """
    Détermine si une page est blanche, **sans aucun appel API**.

    Un livre imprimé en comporte normalement : dos de page de titre, séparation
    entre parties, fin de cahier. Les soumettre au modèle coûte un appel pour
    rien — et l'expose à répondre autre chose que la mention attendue, réponse
    qui serait alors écrite dans `OCR.txt` comme du texte de la pièce.

    Le test est **sévère** par construction. L'asymétrie est nette : manquer une
    page blanche coûte un appel, sauter une page imprimée perdrait du texte.
    """
    if not config.DETECTER_PAGES_BLANCHES:
        return False

    # Une couche texte exploitable interdit de conclure à la blancheur.
    if extraire_couche_texte(page).strip():
        return False

    return proportion_encre(page) <= config.PROPORTION_ENCRE_MAXIMALE


def pages_retenues(pages_du_pdf: int, limite: int | None = None) -> int:
    """
    Détermine combien de pages seront réellement traitées.

    Args:
        pages_du_pdf: nombre de pages du document.
        limite: plafond, ou `config.LIMITE_PAGES` si None.

    Raises:
        ValueError: si la limite est nulle ou négative, ce qui ne traiterait
            rien tout en produisant un `OCR.txt` vide d'apparence normale.
    """
    plafond = config.LIMITE_PAGES if limite is None else limite

    if plafond is None:
        return pages_du_pdf

    if plafond < 1:
        raise ValueError(
            f"LIMITE_PAGES doit valoir au moins 1, reçu {plafond}. "
            "Utilisez None pour traiter le livre entier."
        )

    return min(pages_du_pdf, plafond)


# ============================================================
# 2 bis. COUCHE TEXTE DÉJÀ PRÉSENTE DANS LE PDF
# ============================================================


def extraire_couche_texte(page: Any) -> str:
    """
    Extrait la couche texte d'une page, si elle en possède une.

    `sort=True` réordonne les blocs selon leur position sur la page. C'est
    important au théâtre : les noms de personnages sont souvent centrés ou
    décalés, et l'ordre interne du PDF ne suit pas toujours l'ordre de lecture.

    Returns:
        Le texte normalisé, ou une chaîne vide si la page n'a pas de couche
        texte exploitable.
    """
    try:
        brut = page.get_text("text", sort=True)
    except TypeError:
        # Anciennes versions de PyMuPDF, sans le paramètre `sort`.
        brut = page.get_text("text")
    except Exception:
        return ""

    return blocks.normaliser_couche_texte(brut or "")


def evaluer_page_couche_texte(page: Any) -> tuple[str, list[str]]:
    """
    Extrait et juge la couche texte d'une page.

    Returns:
        `(texte, raisons de refus)`. Une liste de raisons vide signifie que la
        couche texte peut être réutilisée telle quelle, sans appel API.
    """
    texte = extraire_couche_texte(page)

    return texte, blocks.evaluer_couche_texte(texte)


def couche_texte_retenue(texte: str, raisons: list[str]) -> bool:
    """
    Applique la stratégie configurée à une couche texte évaluée.

    Trois comportements, selon `config.STRATEGIE_COUCHE_TEXTE` :
    « jamais » ignore la couche texte, « toujours » l'accepte dès qu'elle
    existe, « auto » ne l'accepte que si elle passe les contrôles.
    """
    strategie = config.STRATEGIE_COUCHE_TEXTE

    if strategie not in config.STRATEGIES_COUCHE_TEXTE:
        raise ValueError(
            f"STRATEGIE_COUCHE_TEXTE invalide : « {strategie} ». "
            f"Valeurs admises : {', '.join(config.STRATEGIES_COUCHE_TEXTE)}."
        )

    if strategie == "jamais":
        return False

    if not texte.strip():
        return False

    if strategie == "toujours":
        return True

    return not raisons


def reduire_dpi(dpi: int) -> int:
    """
    Calcule le palier de résolution inférieur, sans descendre sous le plancher.

    Fonction séparée et pure, pour que la boucle de dégradation soit
    vérifiable sans PDF.
    """
    return max(config.DPI_MINIMAL, int(dpi * config.FACTEUR_REDUCTION_DPI))


def rasteriser_avec_degradation(page: Any, libelle: str = "") -> tuple[bytes, int, list[str]]:
    """
    Rasterise une page en réduisant la résolution si l'image est trop lourde.

    Une page très chargée peut dépasser la taille acceptée par l'API. Plutôt
    que d'échouer, on dégrade progressivement : une transcription à 110 dpi
    vaut infiniment mieux qu'une page absente.

    Returns:
        `(image PNG, dpi retenu, avertissements)`.
    """
    dpi = config.DPI_RASTERISATION
    avertissements: list[str] = []

    while True:
        image = rasteriser_page(page, dpi)
        taille_mo = len(image) / (1024 * 1024)

        if taille_mo <= config.TAILLE_MAX_IMAGE_MO:
            return image, dpi, avertissements

        palier = reduire_dpi(dpi)

        # Plancher atteint : on tente l'appel malgré tout. L'API acceptera
        # peut-être, et un échec sec ici serait plus dommageable qu'un essai.
        if palier >= dpi:
            avertissements.append(
                f"image de {taille_mo:.1f} Mo à {dpi} dpi, plancher atteint"
            )
            return image, dpi, avertissements

        journalisation.detail(
            f"{libelle} : {taille_mo:.1f} Mo à {dpi} dpi, "
            f"nouvelle tentative à {palier} dpi"
        )
        avertissements.append(f"résolution réduite à {palier} dpi")
        dpi = palier


# ============================================================
# 3. TRAITEMENT D'UNE PAGE
# ============================================================


def _message_page(numero: int, nombre_pages: int) -> str:
    """Construit le message utilisateur accompagnant l'image."""
    return (
        f"Transcris intégralement la page {numero} sur {nombre_pages} "
        f"de ce livre.\n\n"
        "Applique strictement les instructions de transcription. "
        "Ne corrige rien, n'ajoute aucune mise en forme, "
        "n'ajoute aucun marqueur de page."
    )


def _controler_transcription(texte: str, page_vide: bool) -> list[str]:
    """Rassemble les avertissements portant sur le contenu transcrit."""
    if page_vide:
        return []

    avertissements = blocks.verifier_page_ocr(texte)

    if not texte.strip():
        # Une page réellement blanche doit être déclarée par le modèle. Une
        # sortie vide non déclarée est suspecte : la page sera reprise.
        avertissements.append(
            "sortie vide sans déclaration de page blanche"
        )

    return avertissements


def traiter_page(
    *,
    page: Any,
    numero: int,
    nombre_pages: int,
    chemins: io.CheminsLivre,
    journal: journalisation.Journal,
    nom_livre: str,
) -> str:
    """
    Transcrit une page et l'enregistre, sauf si elle est déjà terminée.

    L'ordre d'écriture est critique : le `.txt` d'abord, le sidecar ensuite.
    Une coupure entre les deux laisse un fichier orphelin qui sera réécrit,
    jamais une page faussement validée (ARCHITECTURE.md §7).

    Returns:
        L'un des statuts `PAGE_*`.
    """
    libelle = f"page {numero}"

    if not io.unite_a_refaire(chemins.page_json(numero)):
        return PAGE_SAUTEE

    # Réutilisation d'une couche texte déjà présente : le seul chemin qui ne
    # consomme aucun jeton. Tenté avant toute rasterisation.
    texte_couche, raisons = evaluer_page_couche_texte(page)

    if couche_texte_retenue(texte_couche, raisons):
        _enregistrer_couche_texte(
            chemins=chemins,
            numero=numero,
            texte=texte_couche,
            journal=journal,
            nom_livre=nom_livre,
        )
        journalisation.detail(f"{libelle} : couche texte réutilisée, aucun appel")
        return PAGE_COUCHE_TEXTE

    if texte_couche.strip() and raisons:
        journalisation.detail(
            f"{libelle} : couche texte écartée ({raisons[0]}), OCR Vision"
        )

    # Page blanche reconnue localement : aucun appel, et aucun risque que le
    # modèle réponde une phrase qui finirait dans le texte de la pièce.
    if page_blanche(page):
        _enregistrer_page_vide(
            chemins=chemins,
            numero=numero,
            source=SOURCE_PAGE_BLANCHE,
            journal=journal,
            nom_livre=nom_livre,
        )
        journalisation.detail(f"{libelle} : page blanche, aucun appel")
        return PAGE_BLANCHE

    image, dpi, avertissements = rasteriser_avec_degradation(page, libelle)

    try:
        resultat = api.appeler_modele(
            modele=config.MODEL_OCR,
            instructions=io.charger_prompt("prompt_ocr"),
            message=_message_page(numero, nombre_pages),
            image_png=image,
            libelle=libelle,
        )
    except api.EchecAppelAPI as erreur:
        _enregistrer_echec(
            chemins=chemins,
            numero=numero,
            dpi=dpi,
            taille_image=len(image),
            erreur=str(erreur),
            journal=journal,
            nom_livre=nom_livre,
        )
        journalisation.echec(f"{libelle} : {erreur}")
        return PAGE_ECHOUEE

    texte = blocks.nettoyer_enveloppe(resultat.texte)

    # Toute déclaration de page vide est reconnue, pas seulement la mention
    # exacte du prompt. Un modèle qui paraphrase — « Cette page est vide. » —
    # verrait sinon sa phrase écrite dans OCR.txt comme du texte de la pièce,
    # puis rendue dans le DOCX.
    page_vide = blocks.est_declaration_page_vide(texte)

    if page_vide:
        # On enregistre une page vide, et non la déclaration : c'est un signal
        # de protocole, pas du contenu à transmettre à l'étape 2.
        texte = ""

    avertissements += resultat.avertissements
    avertissements += _controler_transcription(texte, page_vide)

    statut = io.statut_depuis_avertissements(avertissements)

    # Compteur de reprises : borne les retentatives sur un avertissement
    # reproductible, qu'un nouvel appel ne corrigerait jamais.
    reprises = io.reprises_effectuees(chemins.page_json(numero))
    if statut == config.STATUT_SUSPECT:
        reprises += 1

    # Contenu d'abord, sidecar ensuite : l'ordre porte l'invariant de reprise.
    io.ecrire_texte_atomique(chemins.page_txt(numero), texte)
    io.ecrire_sidecar(
        chemins.page_json(numero),
        {
            "statut": statut,
            "reprises": reprises,
            "unite": "page",
            "numero": numero,
            "date_traitement": journalisation.horodatage(),
            "source": SOURCE_VISION,
            "dpi": dpi,
            "page_vide": page_vide,
            # L'entrée est une image : cette longueur est en octets, non en
            # caractères, contrairement aux autres étapes.
            "longueur_entree": len(image),
            "avertissements": avertissements,
            **resultat.champs_journal(),
        },
    )

    journal.enregistrer_appel(
        livre=nom_livre,
        unite="page",
        numero=numero,
        longueur_entree=len(image),
        avertissements=avertissements,
        **resultat.champs_journal(),
    )

    if avertissements:
        journalisation.alerte(f"{libelle} : {', '.join(avertissements)}")
        return PAGE_SUSPECTE

    return PAGE_TERMINEE


def _enregistrer_page_vide(
    *,
    chemins: io.CheminsLivre,
    numero: int,
    source: str,
    journal: journalisation.Journal,
    nom_livre: str,
) -> None:
    """
    Enregistre une page reconnue blanche localement, sans aucun appel.

    Le sidecar porte `page_vide` et sa provenance, si bien que le décompte des
    pages blanches d'un livre reste vérifiable après coup.
    """
    io.ecrire_texte_atomique(chemins.page_txt(numero), "")
    io.ecrire_sidecar(
        chemins.page_json(numero),
        {
            "statut": config.STATUT_TERMINE,
            "unite": "page",
            "numero": numero,
            "source": source,
            "modele": None,
            "response_id": None,
            "date_traitement": journalisation.horodatage(),
            "duree_secondes": 0.0,
            "page_vide": True,
            "longueur_entree": 0,
            "longueur_sortie": 0,
            "avertissements": [],
        },
    )

    journal.enregistrer_appel(
        livre=nom_livre,
        unite="page",
        numero=numero,
        source=source,
        modele=None,
        page_vide=True,
        longueur_sortie=0,
        tokens_entree=0,
        tokens_sortie=0,
        avertissements=[],
    )


def _enregistrer_couche_texte(
    *,
    chemins: io.CheminsLivre,
    numero: int,
    texte: str,
    journal: journalisation.Journal,
    nom_livre: str,
) -> None:
    """
    Enregistre une page issue de la couche texte du PDF.

    Le sidecar porte `source: "couche_texte"`, ce qui rend la provenance de
    chaque page vérifiable après coup — utile si le résultat final surprend, et
    indispensable pour savoir ce qui a réellement été payé.
    """
    io.ecrire_texte_atomique(chemins.page_txt(numero), texte)
    io.ecrire_sidecar(
        chemins.page_json(numero),
        {
            "statut": config.STATUT_TERMINE,
            "unite": "page",
            "numero": numero,
            "source": SOURCE_COUCHE_TEXTE,
            "modele": None,
            "response_id": None,
            "date_traitement": journalisation.horodatage(),
            "duree_secondes": 0.0,
            "longueur_entree": 0,
            "longueur_sortie": len(texte),
            "avertissements": [],
        },
    )

    journal.enregistrer_appel(
        livre=nom_livre,
        unite="page",
        numero=numero,
        source=SOURCE_COUCHE_TEXTE,
        modele=None,
        longueur_sortie=len(texte),
        # Aucun jeton consommé : c'est tout l'intérêt de ce chemin.
        tokens_entree=0,
        tokens_sortie=0,
        avertissements=[],
    )


def _enregistrer_echec(
    *,
    chemins: io.CheminsLivre,
    numero: int,
    dpi: int,
    taille_image: int,
    erreur: str,
    journal: journalisation.Journal,
    nom_livre: str,
) -> None:
    """
    Consigne l'échec définitif d'une page.

    Le sidecar porte `STATUT_ECHEC`, donc la page sera reprise au prochain
    passage. Aucun fichier `.txt` n'est écrit : il n'y a rien à écrire, et un
    fichier vide pourrait être pris pour une page blanche légitime.
    """
    io.ecrire_sidecar(
        chemins.page_json(numero),
        {
            "statut": config.STATUT_ECHEC,
            "unite": "page",
            "numero": numero,
            "modele": config.MODEL_OCR,
            "date_traitement": journalisation.horodatage(),
            "dpi": dpi,
            "longueur_entree": taille_image,
            "erreur": erreur,
            "avertissements": ["échec définitif de l'appel"],
        },
    )

    journal.enregistrer_appel(
        livre=nom_livre,
        unite="page",
        numero=numero,
        modele=config.MODEL_OCR,
        longueur_entree=taille_image,
        erreur=erreur,
        avertissements=["échec définitif de l'appel"],
    )


# ============================================================
# 4. ASSEMBLAGE
# ============================================================


def assembler_ocr(chemins: io.CheminsLivre, nombre_pages: int) -> str:
    """
    Assemble les pages du cache en un fichier OCR complet.

    Les marqueurs `[PAGE X]` sont ajoutés **ici**, par le code, et non par le
    modèle : c'est ce qui rend leur format déterministe, donc le découpage de
    l'étape 2 fiable.

    Une page absente ou en échec reçoit un marqueur d'échec explicite. Un trou
    visible dans `OCR.txt` vaut mieux qu'un trou silencieux : on peut le
    chercher, le compter et le reprendre.
    """
    morceaux: list[str] = []

    for numero in range(1, nombre_pages + 1):
        disponible = io.unite_terminee(chemins.page_json(numero))
        texte = io.lire_texte_si_present(chemins.page_txt(numero)) if disponible else None

        if texte is None:
            morceaux.append(config.MARQUEUR_ECHEC_PAGE.format(numero=numero))
            continue

        entete = config.MARQUEUR_PAGE.format(numero=numero)
        morceaux.append(f"{entete}\n{texte.strip()}".strip())

    return config.SEPARATEUR_PAGE.join(morceaux).strip() + "\n"


# ============================================================
# 5. TRAITEMENT D'UN LIVRE
# ============================================================


def traiter_pdf(
    chemin_pdf: Path,
    journal: journalisation.Journal,
    limite_pages: int | None = None,
) -> ResultatLivre:
    """
    Transcrit un PDF entier, page par page, puis assemble `OCR.txt`.

    Les sorties sont écrites dans le dossier du PDF, ce qui reste correct que
    les PDF soient à plat ou rangés en sous-dossiers.
    """
    nom_livre = io.nom_livre_depuis_pdf(chemin_pdf)
    chemins = io.resoudre_chemins(nom_livre, chemin_pdf.parent)
    resultat = ResultatLivre(nom=nom_livre)

    journalisation.section(f"OCR — {nom_livre}")

    with journalisation.Chrono() as chrono:
        try:
            _transcrire_pages(
                chemin_pdf=chemin_pdf,
                chemins=chemins,
                journal=journal,
                resultat=resultat,
                limite_pages=limite_pages,
            )
        except Exception as erreur:
            # Un livre en erreur ne doit pas empêcher de traiter les suivants.
            resultat.statut = config.STATUT_ECHEC
            resultat.erreur = str(erreur)
            journalisation.echec(f"{nom_livre} : {erreur}")

    resultat.duree_secondes = chrono.secondes

    if resultat.statut != config.STATUT_ECHEC:
        resultat.statut = (
            config.STATUT_TERMINE if resultat.complet else config.STATUT_SUSPECT
        )
        _resumer(resultat, chemins)

    journal.resumer_livre(nom_livre, **resultat.champs_journal())
    journal.sauvegarder()

    return resultat


def _transcrire_pages(
    *,
    chemin_pdf: Path,
    chemins: io.CheminsLivre,
    journal: journalisation.Journal,
    resultat: ResultatLivre,
    limite_pages: int | None = None,
) -> None:
    """Boucle sur les pages d'un PDF déjà ouvert."""
    document = ouvrir_pdf(chemin_pdf)

    try:
        resultat.pages_du_pdf = document.page_count
        nombre_pages = pages_retenues(document.page_count, limite_pages)
        resultat.pages_totales = nombre_pages

        io.assurer_dossier(chemins.dossier_pages)

        if nombre_pages < resultat.pages_du_pdf:
            # Message volontairement voyant : produire un OCR.txt de dix pages
            # à partir d'un livre de trois cents serait une mauvaise surprise
            # si la limite avait été oubliée.
            journalisation.alerte(
                f"ESSAI LIMITÉ : {nombre_pages} page(s) sur "
                f"{resultat.pages_du_pdf}. Mettez LIMITE_PAGES à None pour "
                "traiter le livre entier."
            )
        else:
            journalisation.info(f"   {nombre_pages} page(s) à transcrire")

        compteurs = {
            PAGE_TERMINEE: 0,
            PAGE_SAUTEE: 0,
            PAGE_SUSPECTE: 0,
            PAGE_ECHOUEE: 0,
            PAGE_COUCHE_TEXTE: 0,
            PAGE_BLANCHE: 0,
        }

        for numero in range(1, nombre_pages + 1):
            statut = traiter_page(
                page=document.load_page(numero - 1),
                numero=numero,
                nombre_pages=nombre_pages,
                chemins=chemins,
                journal=journal,
                nom_livre=resultat.nom,
            )

            compteurs[statut] += 1

            if statut == PAGE_ECHOUEE:
                resultat.numeros_echoues.append(numero)

            if statut not in STATUTS_SANS_APPEL:
                # Le journal est sauvegardé à chaque page réellement traitée :
                # une coupure ne doit pas emporter la trace des appels payés.
                journal.sauvegarder()
                api.patienter()
            elif statut != PAGE_SAUTEE:
                # Aucun appel, donc aucune pause à respecter — mais le journal
                # doit tout de même garder la trace de la page.
                journal.sauvegarder()

            if numero % 10 == 0 or numero == nombre_pages:
                journalisation.progression(numero, nombre_pages, "pages")

        resultat.pages_traitees = compteurs[PAGE_TERMINEE]
        resultat.pages_couche_texte = compteurs[PAGE_COUCHE_TEXTE]
        resultat.pages_blanches = compteurs[PAGE_BLANCHE]
        resultat.pages_sautees = compteurs[PAGE_SAUTEE]
        resultat.pages_suspectes = compteurs[PAGE_SUSPECTE]
        resultat.pages_echouees = compteurs[PAGE_ECHOUEE]

    finally:
        document.close()


def _resumer(resultat: ResultatLivre, chemins: io.CheminsLivre) -> None:
    """Écrit `OCR.txt` et affiche le bilan du livre."""
    contenu = assembler_ocr(chemins, resultat.pages_totales)
    io.ecrire_texte_atomique(chemins.ocr, contenu)

    journalisation.succes(
        f"{chemins.ocr.name} — "
        f"{journalisation.formater_nombre(len(contenu))} caractères"
    )

    if resultat.pages_sautees:
        journalisation.saute(f"{resultat.pages_sautees} page(s) déjà transcrite(s)")

    if resultat.pages_suspectes:
        journalisation.alerte(
            f"{resultat.pages_suspectes} page(s) suspecte(s), reprises au "
            f"prochain passage"
        )

    if resultat.numeros_echoues:
        journalisation.echec(
            f"pages en échec : {resultat.numeros_echoues}"
        )


# ============================================================
# 5 bis. DIAGNOSTIC DES COUCHES TEXTE
# ============================================================


@dataclass
class DiagnosticLivre:
    """Ce qu'un PDF coûtera, avant d'avoir dépensé le moindre jeton."""

    nom: str
    pages_du_pdf: int = 0
    pages_totales: int = 0
    pages_exploitables: int = 0
    pages_a_ocriser: int = 0
    pages_deja_faites: int = 0
    raisons: dict[str, int] = field(default_factory=dict)
    erreur: str | None = None

    @property
    def part_gratuite(self) -> float:
        """Part des pages qui n'exigeront aucun appel API."""
        if not self.pages_totales:
            return 0.0

        return (self.pages_exploitables + self.pages_deja_faites) / self.pages_totales


def diagnostiquer_couches_texte(
    dossier: Path | None = None,
    limite_pages: int | None = None,
) -> list[DiagnosticLivre]:
    """
    Recense, sans aucun appel API, ce que chaque PDF coûtera réellement.

    Répond à une question concrète : beaucoup de PDF ont déjà été passés à l'OCR
    par un scanner ou par Acrobat, et il serait absurde de repayer leur
    transcription. Ce diagnostic est **entièrement local et gratuit** — il
    n'ouvre les PDF que pour en lire la couche texte.

    Il indique aussi, quand une couche texte est écartée, **pourquoi** elle l'a
    été : accents dépouillés, trop peu de lettres, page trop courte. C'est ce qui
    permet de juger s'il faut relâcher un seuil ou accepter de payer.

    Args:
        dossier: dossier à parcourir. `config.DOSSIER_DRIVE` par défaut.
    """
    base = dossier if dossier is not None else config.DOSSIER_DRIVE

    journalisation.titre("Diagnostic des couches texte (aucun appel API)")

    diagnostics: list[DiagnosticLivre] = []

    for chemin in io.lister_pdf(base):
        diagnostics.append(_diagnostiquer_pdf(chemin, limite_pages))

    _afficher_diagnostic(diagnostics)

    return diagnostics


def _diagnostiquer_pdf(
    chemin_pdf: Path,
    limite_pages: int | None = None,
) -> DiagnosticLivre:
    """Examine la couche texte de chaque page d'un PDF."""
    nom_livre = io.nom_livre_depuis_pdf(chemin_pdf)
    chemins = io.resoudre_chemins(nom_livre, chemin_pdf.parent)
    diagnostic = DiagnosticLivre(nom=nom_livre)

    try:
        document = ouvrir_pdf(chemin_pdf)
    except RuntimeError as erreur:
        diagnostic.erreur = str(erreur)
        return diagnostic

    try:
        diagnostic.pages_du_pdf = document.page_count
        diagnostic.pages_totales = pages_retenues(document.page_count, limite_pages)

        for numero in range(1, diagnostic.pages_totales + 1):
            if io.unite_terminee(chemins.page_json(numero)):
                diagnostic.pages_deja_faites += 1
                continue

            texte, raisons = evaluer_page_couche_texte(document.load_page(numero - 1))

            if couche_texte_retenue(texte, raisons):
                diagnostic.pages_exploitables += 1
                continue

            diagnostic.pages_a_ocriser += 1

            # On ne retient que la première raison : c'est la plus déterminante,
            # et un décompte par raison reste lisible.
            motif = raisons[0].split(" :")[0] if raisons else "couche texte absente"
            diagnostic.raisons[motif] = diagnostic.raisons.get(motif, 0) + 1

    finally:
        document.close()

    return diagnostic


def _afficher_diagnostic(diagnostics: list[DiagnosticLivre]) -> None:
    """Présente le diagnostic, livre par livre."""
    if not diagnostics:
        journalisation.alerte("aucun PDF dans ce dossier")
        return

    for diagnostic in diagnostics:
        journalisation.section(diagnostic.nom)

        if diagnostic.erreur:
            journalisation.echec(diagnostic.erreur)
            continue

        if diagnostic.pages_totales < diagnostic.pages_du_pdf:
            journalisation.alerte(
                f"ESSAI LIMITÉ : {diagnostic.pages_totales} page(s) "
                f"examinée(s) sur {diagnostic.pages_du_pdf}"
            )

        journalisation.info(f"   pages retenues          {diagnostic.pages_totales}")
        journalisation.info(
            f"   couche texte utilisable {diagnostic.pages_exploitables}"
        )
        journalisation.info(f"   déjà transcrites        {diagnostic.pages_deja_faites}")
        journalisation.info(f"   à passer à l'OCR        {diagnostic.pages_a_ocriser}")
        journalisation.info(
            f"   part sans appel API     {diagnostic.part_gratuite:.0%}"
        )

        if diagnostic.raisons:
            journalisation.info("")
            journalisation.info("   couches texte écartées, par motif :")
            for motif, nombre in sorted(
                diagnostic.raisons.items(), key=lambda item: -item[1]
            ):
                journalisation.info(f"      {nombre:>4}  {motif}")

    total_pages = sum(d.pages_totales for d in diagnostics)
    total_gratuites = sum(
        d.pages_exploitables + d.pages_deja_faites for d in diagnostics
    )

    journalisation.recapitulatif(
        {
            "Livres examinés": len(diagnostics),
            "Pages totales": total_pages,
            "Sans appel API": total_gratuites,
            "À facturer": total_pages - total_gratuites,
            "Économie": f"{(100 * total_gratuites / total_pages) if total_pages else 0:.0f} %",
            "Stratégie": config.STRATEGIE_COUCHE_TEXTE,
        }
    )


# ============================================================
# 6. POINT D'ENTRÉE DE L'ÉTAPE
# ============================================================


def executer(
    dossier: Path | None = None,
    limite_pages: int | None = None,
) -> list[ResultatLivre]:
    """
    Lance l'étape OCR sur tous les PDF du dossier de travail.

    Args:
        dossier: dossier à parcourir. `config.DOSSIER_DRIVE` par défaut.

    Returns:
        Un bilan par livre traité.
    """
    base = dossier if dossier is not None else config.DOSSIER_DRIVE

    journalisation.titre("Étape 1 — OCR Vision")

    pdfs = io.lister_pdf(base)
    journalisation.info(f"Dossier : {base}")
    journalisation.info(f"PDF trouvés : {len(pdfs)}")

    if not pdfs:
        journalisation.alerte("aucun PDF dans ce dossier")
        return []

    journal = journalisation.Journal.charger_ou_creer(
        NOM_ETAPE,
        base,
        {
            "modele": config.MODEL_OCR,
            "dpi": config.DPI_RASTERISATION,
            "strategie_couche_texte": config.STRATEGIE_COUCHE_TEXTE,
            "limite_pages": (
                config.LIMITE_PAGES if limite_pages is None else limite_pages
            ),
            "max_output_tokens": config.MAX_OUTPUT_TOKENS,
        },
    )

    resultats = [
        traiter_pdf(chemin, journal, limite_pages) for chemin in pdfs
    ]

    _afficher_recapitulatif(resultats, journal)

    return resultats


def _afficher_recapitulatif(
    resultats: list[ResultatLivre],
    journal: journalisation.Journal,
) -> None:
    """Affiche le bilan global de l'étape."""
    a_reprendre = [r.nom for r in resultats if not r.complet]

    journalisation.recapitulatif(
        {
            "Livres traités": len(resultats),
            "Pages transcrites (API)": sum(r.pages_traitees for r in resultats),
            "Pages sans appel API": sum(
                r.pages_couche_texte + r.pages_blanches for r in resultats
            ),
            "dont pages blanches": sum(r.pages_blanches for r in resultats),
            "Pages déjà faites": sum(r.pages_sautees for r in resultats),
            "Pages suspectes": sum(r.pages_suspectes for r in resultats),
            "Pages en échec": sum(r.pages_echouees for r in resultats),
            "Durée": journalisation.formater_duree(
                sum(r.duree_secondes for r in resultats)
            ),
            "Journal": journal.chemin.name,
        }
    )

    if a_reprendre:
        journalisation.info("")
        journalisation.alerte(
            f"à reprendre en relançant cette étape : {', '.join(a_reprendre)}"
        )
