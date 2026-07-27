"""
Accès au système de fichiers : chemins, lecture, écriture atomique, reprise.

Ce module est le **seul** à connaître l'organisation des fichiers sur le
disque. Aucun autre module ne construit un chemin : tous passent par
`resoudre_chemins()`. Renommer une convention de fichier est donc un
changement local à ce fichier.

Il porte également le mécanisme de reprise après interruption décrit dans
ARCHITECTURE.md §7. L'invariant à retenir :

    le sidecar JSON est TOUJOURS écrit après le fichier de contenu,
    et une unité n'est terminée que si son sidecar porte STATUT_TERMINE.

Une coupure entre les deux écritures laisse donc un `.txt` orphelin qui sera
simplement réécrit au prochain passage — jamais un travail faussement validé.
"""

from __future__ import annotations

import json
import os
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from theatre_editor import config

# Dossier des prompts, résolu relativement à ce fichier afin de fonctionner
# quel que soit le répertoire courant (notebook, CLI, test).
DOSSIER_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"


# ============================================================
# 1. RÉSOLUTION DES CHEMINS
# ============================================================


@dataclass(frozen=True)
class CheminsLivre:
    """
    Ensemble des chemins dérivés d'un même livre.

    Instance immuable : une fois résolus, les chemins d'un livre ne changent
    plus pendant l'exécution, ce qui écarte toute divergence entre l'endroit
    où une étape écrit et celui où la suivante lit.
    """

    nom: str
    dossier: Path

    # --- Étape 1 -----------------------------------------------------
    pdf: Path
    dossier_pages: Path
    ocr: Path

    # --- Étape 2 -----------------------------------------------------
    dossier_blocs: Path
    dossier_raccords: Path
    edit: Path

    # --- Étape 3 -----------------------------------------------------
    dossier_report: Path
    report: Path

    # --- Étape 4 -----------------------------------------------------
    docx: Path

    # ------------------------------------------------------------
    # Chemins des unités de travail.
    # Le format sur quatre chiffres garantit un tri alphabétique
    # identique au tri numérique, jusqu'à 9999 unités.
    # ------------------------------------------------------------

    def page_txt(self, numero: int) -> Path:
        """Texte OCR brut de la page `numero`."""
        return self.dossier_pages / f"page_{numero:04d}.txt"

    def page_json(self, numero: int) -> Path:
        """Sidecar de la page `numero`."""
        return self.dossier_pages / f"page_{numero:04d}.json"

    def bloc_txt(self, numero: int) -> Path:
        """Texte édité du bloc `numero` (avant raccord)."""
        return self.dossier_blocs / f"bloc_{numero:04d}.txt"

    def bloc_json(self, numero: int) -> Path:
        """Sidecar du bloc édité `numero`."""
        return self.dossier_blocs / f"bloc_{numero:04d}.json"

    def raccord_txt(self, numero: int) -> Path:
        """Texte du bloc `numero` après passe de raccord."""
        return self.dossier_raccords / f"bloc_{numero:04d}.txt"

    def raccord_json(self, numero: int) -> Path:
        """Sidecar de la jonction `numero` (entre blocs numero et numero+1)."""
        return self.dossier_raccords / f"raccord_{numero:04d}.json"

    def report_bloc_txt(self, numero: int) -> Path:
        """Constats de validation pour le bloc `numero`."""
        return self.dossier_report / f"bloc_{numero:04d}.txt"

    def report_bloc_json(self, numero: int) -> Path:
        """Sidecar de validation du bloc `numero`."""
        return self.dossier_report / f"bloc_{numero:04d}.json"


def resoudre_chemins(nom_livre: str, dossier: Path | None = None) -> CheminsLivre:
    """
    Construit tous les chemins d'un livre à partir de son nom.

    Args:
        nom_livre: nom sans extension, tel que dérivé du PDF source.
        dossier: dossier de travail. `config.DOSSIER_DRIVE` par défaut.

    Returns:
        L'ensemble des chemins du livre. Aucun dossier n'est créé ici :
        la résolution d'un chemin ne doit avoir aucun effet de bord.
    """
    base = dossier if dossier is not None else config.DOSSIER_DRIVE

    return CheminsLivre(
        nom=nom_livre,
        dossier=base,
        pdf=base / f"{nom_livre}.pdf",
        dossier_pages=base / f"{nom_livre}{config.SUFFIXE_OCR_PAGES}",
        ocr=base / f"{nom_livre}{config.SUFFIXE_OCR}",
        dossier_blocs=base / f"{nom_livre}{config.SUFFIXE_EDIT_BLOCS}",
        dossier_raccords=base / f"{nom_livre}{config.SUFFIXE_EDIT_RACCORDS}",
        edit=base / f"{nom_livre}{config.SUFFIXE_EDIT}",
        dossier_report=base / f"{nom_livre}{config.SUFFIXE_REPORT_BLOCS}",
        report=base / f"{nom_livre}{config.SUFFIXE_REPORT}",
        docx=base / f"{nom_livre}{config.SUFFIXE_DOCX}",
    )


def nom_livre_depuis_pdf(chemin: Path) -> str:
    """Déduit le nom du livre du nom de son PDF (« Le Malentendu.pdf » → « Le Malentendu »)."""
    return chemin.stem


def nom_livre_depuis_ocr(chemin: Path) -> str:
    """
    Déduit le nom du livre du nom de son fichier OCR.

    Raises:
        ValueError: si le nom ne porte pas le suffixe OCR attendu.
    """
    if not chemin.name.endswith(config.SUFFIXE_OCR):
        raise ValueError(
            f"« {chemin.name} » ne se termine pas par "
            f"« {config.SUFFIXE_OCR} » : impossible d'en déduire le nom du livre."
        )

    return chemin.name[: -len(config.SUFFIXE_OCR)]


# ============================================================
# 2. LECTURE ET ÉCRITURE
# ============================================================


def assurer_dossier(chemin: Path) -> Path:
    """Crée le dossier s'il n'existe pas, et le retourne."""
    chemin.mkdir(parents=True, exist_ok=True)
    return chemin


def ecrire_texte_atomique(chemin: Path, contenu: str) -> None:
    """
    Écrit un fichier texte de façon atomique.

    L'écriture passe par un fichier temporaire, suivi d'un `os.replace()`,
    qui est atomique au niveau du système de fichiers. Un lecteur ne peut
    donc jamais observer un fichier à moitié écrit — situation autrement
    fréquente sur un Google Drive monté en FUSE, où un flush interrompu
    laisse un fichier tronqué.

    `newline="\\n"` est explicite : sans lui, Python traduirait les fins de
    ligne en CRLF sous Windows, ce qui polluerait les textes édités et
    fausserait les comparaisons ligne à ligne de l'étape 3.
    """
    assurer_dossier(chemin.parent)

    temporaire = chemin.with_name(chemin.name + config.EXTENSION_TEMPORAIRE)

    with open(temporaire, "w", encoding="utf-8", newline="\n") as flux:
        flux.write(contenu)
        # Forcer l'écriture jusqu'au disque avant de publier le fichier :
        # sur Drive, un os.replace() suivi d'une coupure pourrait sinon
        # publier un contenu encore en mémoire tampon.
        flux.flush()
        os.fsync(flux.fileno())

    os.replace(temporaire, chemin)


def lire_texte(chemin: Path) -> str:
    """
    Lit un fichier texte en UTF-8, avec repli sur UTF-8 + BOM.

    Les fins de ligne sont normalisées en `\\n`. C'est indispensable : un
    fichier intermédiaire peut avoir été relu et corrigé à la main sous
    Windows, et un `\\r` résiduel casserait le découpage en lignes comme la
    reconnaissance des marqueurs.

    Raises:
        FileNotFoundError: si le fichier est absent.
    """
    try:
        texte = chemin.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        texte = chemin.read_text(encoding="utf-8-sig")

    return texte.replace("\r\n", "\n").replace("\r", "\n")


def lire_texte_si_present(chemin: Path) -> str | None:
    """Comme `lire_texte()`, mais retourne None si le fichier est absent."""
    if not chemin.exists():
        return None

    return lire_texte(chemin)


# ============================================================
# 3. SIDECARS ET REPRISE
# ============================================================


def ecrire_sidecar(chemin: Path, donnees: dict) -> None:
    """
    Écrit un sidecar JSON de façon atomique.

    À n'appeler qu'**après** l'écriture du fichier de contenu correspondant :
    c'est cet ordre qui garantit qu'une unité interrompue ne sera jamais tenue
    pour terminée (ARCHITECTURE.md §7).
    """
    ecrire_texte_atomique(
        chemin,
        json.dumps(donnees, ensure_ascii=False, indent=2) + "\n",
    )


def lire_sidecar(chemin: Path) -> dict | None:
    """
    Lit un sidecar JSON.

    Returns:
        Le contenu, ou None si le fichier est absent, illisible ou corrompu.
        Un sidecar corrompu est traité comme absent : l'unité sera refaite,
        ce qui est toujours préférable à une exception qui interromprait le
        traitement d'un livre entier.
    """
    if not chemin.exists():
        return None

    try:
        return json.loads(lire_texte(chemin))
    except (json.JSONDecodeError, OSError):
        return None


def unite_terminee(chemin_sidecar: Path) -> bool:
    """
    Détermine si une unité de travail est terminée et ne doit pas être refaite.

    C'est l'unique porte d'entrée de la reprise, partagée par les trois étapes
    IA. Une unité est terminée si et seulement si son sidecar existe et porte
    `STATUT_TERMINE` — un statut « suspect » ou « echec » entraîne donc une
    nouvelle tentative.
    """
    donnees = lire_sidecar(chemin_sidecar)

    if donnees is None:
        return False

    return donnees.get("statut") == config.STATUT_TERMINE


def statut_depuis_avertissements(avertissements: list[str]) -> str:
    """Déduit le statut d'une unité produite de la liste de ses avertissements."""
    return config.STATUT_TERMINE if not avertissements else config.STATUT_SUSPECT


# ============================================================
# 4. PROMPTS
# ============================================================


@lru_cache(maxsize=None)
def charger_prompt(nom: str) -> str:
    """
    Charge un prompt depuis `theatre_editor/prompts/<nom>.md`.

    Le résultat est mis en cache : un prompt est relu des centaines de fois
    au cours d'un livre, et son contenu ne change pas en cours d'exécution.

    Args:
        nom: nom du fichier sans extension, p. ex. « prompt_edition ».

    Raises:
        FileNotFoundError: avec la liste des prompts réellement disponibles,
            car l'erreur la plus probable est une faute de frappe sur le nom.
    """
    chemin = DOSSIER_PROMPTS / f"{nom}.md"

    if not chemin.exists():
        disponibles = sorted(p.stem for p in DOSSIER_PROMPTS.glob("*.md"))
        raise FileNotFoundError(
            f"Prompt introuvable : {chemin}\n"
            f"Prompts disponibles : {', '.join(disponibles) or 'aucun'}"
        )

    return lire_texte(chemin).strip()


# ============================================================
# 5. EXPLORATION DU DOSSIER DE TRAVAIL
# ============================================================


def _est_fichier_utile(chemin: Path) -> bool:
    """
    Écarte les fichiers parasites d'un dossier Drive.

    Google Drive et les suites bureautiques déposent des fichiers cachés
    (`.DS_Store`), des verrous (`~$…`) et nos propres fichiers temporaires.
    Les traiter comme des sources produirait des erreurs incompréhensibles.
    """
    nom = chemin.name

    return (
        chemin.is_file()
        and not nom.startswith(".")
        and not nom.startswith("~$")
        and not nom.endswith(config.EXTENSION_TEMPORAIRE)
    )


def _trier(chemins: list[Path]) -> list[Path]:
    """Trie des chemins de façon stable et indépendante de la casse."""
    return sorted(chemins, key=lambda c: c.name.lower())


def _parcourir(dossier: Path) -> list[Path]:
    """Liste les fichiers du dossier, récursivement selon la configuration."""
    motif = "**/*" if config.SCAN_RECURSIF else "*"
    return [c for c in dossier.glob(motif) if _est_fichier_utile(c)]


def lister_pdf(dossier: Path | None = None) -> list[Path]:
    """Liste les PDF du dossier de travail, triés par nom."""
    base = dossier if dossier is not None else config.DOSSIER_DRIVE
    verifier_dossier_travail(base)

    return _trier(
        [c for c in _parcourir(base) if c.suffix.lower() == ".pdf"]
    )


def lister_fichiers_ocr(dossier: Path | None = None) -> list[Path]:
    """Liste les fichiers `*_OCR.txt` du dossier de travail, triés par nom."""
    base = dossier if dossier is not None else config.DOSSIER_DRIVE
    verifier_dossier_travail(base)

    return _trier(
        [c for c in _parcourir(base) if c.name.endswith(config.SUFFIXE_OCR)]
    )


def verifier_dossier_travail(dossier: Path) -> None:
    """
    Vérifie que le dossier de travail est accessible.

    Échoue immédiatement et bruyamment : poursuivre sans dossier de travail
    produirait des sorties dans un emplacement inattendu, ou des « aucun
    fichier trouvé » trompeurs. Le message indique quoi faire, pas seulement
    ce qui a échoué.

    Raises:
        FileNotFoundError: dossier absent (cause la plus fréquente : Drive
            non monté).
        NotADirectoryError: le chemin existe mais n'est pas un dossier.
    """
    if not dossier.exists():
        raise FileNotFoundError(
            f"Dossier de travail introuvable :\n    {dossier}\n\n"
            "Vérifiez que :\n"
            "  1. Google Drive est bien monté "
            "(drive.mount('/content/drive')) ;\n"
            "  2. config.DOSSIER_DRIVE désigne le bon dossier.\n"
            "Attention aux accents et aux espaces du nom de dossier."
        )

    if not dossier.is_dir():
        raise NotADirectoryError(
            f"Ce chemin existe mais n'est pas un dossier :\n    {dossier}"
        )


def verifier_entree_etape(
    chemin: Path,
    etape: str,
    etape_precedente: str,
) -> None:
    """
    Vérifie qu'un fichier d'entrée produit par l'étape précédente existe.

    Raises:
        FileNotFoundError: message indiquant quelle étape doit être relancée.
    """
    if not chemin.exists():
        raise FileNotFoundError(
            f"L'étape « {etape} » a besoin de ce fichier, qui est absent :\n"
            f"    {chemin}\n\n"
            f"Lancez d'abord l'étape « {etape_precedente} »."
        )


# ============================================================
# 6. CLÉ API
# ============================================================


def charger_cle_api() -> str:
    """
    Récupère la clé API, depuis les secrets Colab puis l'environnement.

    Raises:
        RuntimeError: message expliquant comment renseigner la clé selon le
            contexte d'exécution.
    """
    # Contexte Colab : le secret est la méthode recommandée, la clé n'apparaît
    # alors jamais dans le notebook ni dans son historique de sortie.
    try:
        from google.colab import userdata  # type: ignore[import-not-found]

        cle = userdata.get(config.NOM_CLE_API)
        if cle:
            return cle
    except Exception:
        # Hors Colab, ou secret non autorisé : on tente l'environnement.
        pass

    cle = os.environ.get(config.NOM_CLE_API)
    if cle:
        return cle

    raise RuntimeError(
        f"Clé API introuvable ({config.NOM_CLE_API}).\n\n"
        "Dans Google Colab :\n"
        "  panneau latéral « 🔑 Secrets » → ajouter "
        f"{config.NOM_CLE_API} → activer l'accès au notebook.\n\n"
        "En local :\n"
        f"  définir la variable d'environnement {config.NOM_CLE_API}."
    )


# ============================================================
# 7. UTILITAIRE DE NOMMAGE
# ============================================================


def sans_accents(texte: str) -> str:
    """
    Retire les diacritiques d'une chaîne (« SCÈNE » → « SCENE »).

    Placé ici et non dans `blocks` : le nommage de fichiers en a besoin autant
    que la classification structurelle, et dupliquer une décomposition Unicode
    serait une source de divergence silencieuse.
    """
    decompose = unicodedata.normalize("NFD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c))
