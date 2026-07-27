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


# ============================================================
# 1. RÉSULTATS
# ============================================================


@dataclass
class ResultatLivre:
    """Bilan du traitement d'un PDF."""

    nom: str
    statut: str = config.STATUT_TERMINE
    pages_totales: int = 0
    pages_traitees: int = 0
    pages_sautees: int = 0
    pages_suspectes: int = 0
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
            "pages_totales": self.pages_totales,
            "pages_traitees": self.pages_traitees,
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

    if io.unite_terminee(chemins.page_json(numero)):
        return PAGE_SAUTEE

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
    page_vide = texte.strip() == config.MENTION_PAGE_SANS_TEXTE

    if page_vide:
        # On enregistre une page vide, et non le marqueur : celui-ci est un
        # signal de protocole, pas du contenu à transmettre à l'étape 2.
        texte = ""

    avertissements += resultat.avertissements
    avertissements += _controler_transcription(texte, page_vide)

    statut = io.statut_depuis_avertissements(avertissements)

    # Contenu d'abord, sidecar ensuite : l'ordre porte l'invariant de reprise.
    io.ecrire_texte_atomique(chemins.page_txt(numero), texte)
    io.ecrire_sidecar(
        chemins.page_json(numero),
        {
            "statut": statut,
            "unite": "page",
            "numero": numero,
            "date_traitement": journalisation.horodatage(),
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
) -> None:
    """Boucle sur les pages d'un PDF déjà ouvert."""
    document = ouvrir_pdf(chemin_pdf)

    try:
        nombre_pages = document.page_count
        resultat.pages_totales = nombre_pages

        io.assurer_dossier(chemins.dossier_pages)
        journalisation.info(f"   {nombre_pages} page(s) à transcrire")

        compteurs = {
            PAGE_TERMINEE: 0,
            PAGE_SAUTEE: 0,
            PAGE_SUSPECTE: 0,
            PAGE_ECHOUEE: 0,
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

            if statut != PAGE_SAUTEE:
                # Le journal est sauvegardé à chaque page réellement traitée :
                # une coupure ne doit pas emporter la trace des appels payés.
                journal.sauvegarder()
                api.patienter()

            if numero % 10 == 0 or numero == nombre_pages:
                journalisation.progression(numero, nombre_pages, "pages")

        resultat.pages_traitees = compteurs[PAGE_TERMINEE]
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
        f"{chemins.ocr.name} — {len(contenu):,} caractères".replace(",", " ")
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
# 6. POINT D'ENTRÉE DE L'ÉTAPE
# ============================================================


def executer(dossier: Path | None = None) -> list[ResultatLivre]:
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
            "max_output_tokens": config.MAX_OUTPUT_TOKENS,
        },
    )

    resultats = [traiter_pdf(chemin, journal) for chemin in pdfs]

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
            "Pages transcrites": sum(r.pages_traitees for r in resultats),
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
