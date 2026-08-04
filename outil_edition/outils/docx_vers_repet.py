"""
Régénère `<Livre>_REPET.json` à partir d'un DOCX déjà mis en forme, **sans
jamais produire ni écraser de `.docx`**.

**À quoi cela sert.** `docx_vers_edit.py` fait entrer un DOCX propre dans le
pipeline en écrivant `EDIT.txt` ; l'étape 4 (`docx_export.executer`) produit
ensuite le `.docx` *et* le `REPET.json` ensemble — c'est son rôle normal.
Mais une troupe qui répète depuis un DOCX déjà fini, entretenu à la main dans
Word, n'a besoin que du second : régénérer aussi le `.docx` écrirait un
fichier qu'il faudrait ensuite concilier avec l'original, ou pire, qui
risquerait de l'écraser si on le replace au même endroit par erreur.

Cet outil enchaîne exactement les deux étapes utiles et s'arrête là :

    python outils/docx_vers_repet.py "chemin/Pièce.docx" \\
        --dossier ../outil_repetition/pieces

Relançable à volonté, sur un ou plusieurs DOCX à la fois : chaque exécution
repart du DOCX tel qu'il est sur le disque, quel que soit ce qui a changé
depuis la dernière fois. C'est la mise à jour « propre et facile » qu'une
pièce dont le texte évolue en dehors du pipeline demande.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from outils.docx_vers_edit import _preparer_console, convertir_fichier  # noqa: E402
from theatre_editor import docx_export, liminaires, repet_export  # noqa: E402
from theatre_editor.utils import blocks, io  # noqa: E402


def regenerer_repet(chemin_docx: Path, dossier: Path | None = None) -> Path:
    """
    Régénère `<Livre>_REPET.json` à partir d'un DOCX, sans toucher au `.docx`.

    Reprend exactement le chemin que suivrait l'étape 4 pour produire le
    JSON — `docx_export.lignes_classees()` puis `repet_export.ecrire_repet()`,
    les deux mêmes fonctions, pour que le JSON ne puisse pas diverger d'un
    DOCX régénéré par ailleurs — en sautant la partie qui écrit un `.docx` :
    ce module n'en a pas besoin.

    Args:
        chemin_docx: le document à convertir.
        dossier: dossier de travail, où `EDIT.txt` et le `REPET.json`
            atterrissent. Celui du DOCX par défaut — voir `convertir_fichier`.

    Returns:
        Le chemin du `REPET.json` écrit.
    """
    chemin_edit = convertir_fichier(chemin_docx, dossier)

    base = dossier if dossier is not None else chemin_docx.parent
    chemins = io.resoudre_chemins(chemin_docx.stem, base)
    assert chemins.edit == chemin_edit  # les deux dérivations doivent s'accorder

    texte = io.lire_texte(chemins.edit)
    roles = liminaires.charger_roles(chemins)
    index = blocks.construire_index_structure(texte)
    lignes = docx_export.lignes_classees(texte, index, roles)

    document = repet_export.ecrire_repet(chemins, lignes, index)
    totaux = repet_export.compter(document)

    print(
        f"   {chemins.repet.name} — {totaux['unites']} unité(s), "
        f"{totaux['repliques']} réplique(s), {totaux['personnages']} personnage(s)"
    )

    for avertissement in document["avertissements"]:
        print(f"   [ALERTE]  {avertissement}")

    return chemins.repet


def main(arguments: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(
        description=(
            "Régénère <Livre>_REPET.json à partir d'un ou plusieurs DOCX déjà "
            "mis en forme, sans jamais produire ni écraser de .docx."
        )
    )
    analyseur.add_argument(
        "docx", type=Path, nargs="+", help="le ou les documents à convertir"
    )
    analyseur.add_argument(
        "--dossier",
        type=Path,
        default=None,
        help="dossier de sortie du REPET.json (celui du DOCX par défaut)",
    )

    _preparer_console()

    options = analyseur.parse_args(arguments)
    echec = False

    for chemin in options.docx:
        if not chemin.is_file():
            print(f"introuvable : {chemin}", file=sys.stderr)
            echec = True
            continue

        # `convertir_fichier` (appelé par `regenerer_repet`) annonce déjà la
        # conversion : pas la peine de le refaire ici.
        regenerer_repet(chemin, options.dossier)
        print()

    return 1 if echec else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
