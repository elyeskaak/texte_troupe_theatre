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

    python outils/docx_vers_repet.py "chemin/Pièce.docx" --dossier ../pieces

Relançable à volonté, sur un ou plusieurs DOCX à la fois : chaque exécution
repart du DOCX tel qu'il est sur le disque, quel que soit ce qui a changé
depuis la dernière fois. C'est la mise à jour « propre et facile » qu'une
pièce dont le texte évolue en dehors du pipeline demande.

**`../pieces/` est un dossier partagé**, entre `outil_repetition` et
`outil_lecture` : les deux consomment le même `REPET.json`, il n'y a donc
qu'un seul exemplaire à régénérer. Chaque appel réécrit aussi
`manifest.json` dans ce dossier — la liste de tout ce qui s'y trouve, lue par
les deux outils au démarrage pour proposer automatiquement toutes les
pièces disponibles (voir `regenerer_manifeste`).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from outils.docx_vers_edit import convertir_fichier  # noqa: E402
from theatre_editor import config, docx_export, liminaires, repet_export  # noqa: E402
from theatre_editor.utils import blocks, io  # noqa: E402
from theatre_editor.utils import logging as journalisation  # noqa: E402


def regenerer_repet(chemin_docx: Path, dossier: Path) -> Path:
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
            atterrissent. **Toujours requis**, et toujours différent du
            dossier du DOCX : `convertir_fichier` refuse d'écrire dans le même
            dossier que la source (§ son propre garde-fou), donc « celui du
            DOCX par défaut » n'est jamais un choix qui fonctionne.

    Returns:
        Le chemin du `REPET.json` écrit.
    """
    # `annoncer_etape_suivante=False` : la suggestion par défaut de
    # `convertir_fichier` pointe vers l'étape qui régénère un `.docx` — suivie
    # à la lettre, elle écrirait un second `.docx` dans le dossier partagé, à
    # côté du DOCX source. C'est précisément ce que ce module existe pour
    # éviter (voir le docstring du module).
    chemin_edit = convertir_fichier(chemin_docx, dossier, annoncer_etape_suivante=False)

    chemins = io.resoudre_chemins(chemin_docx.stem, dossier)
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


def regenerer_manifeste(dossier: Path) -> Path:
    """
    Réécrit `manifest.json`, la liste des `REPET.json` présents dans `dossier`.

    Recense **tout** ce qui s'y trouve, pas seulement les pièces traitées à
    cet appel : `docx_vers_repet.py` se relance pièce par pièce, et le
    manifeste doit refléter l'état réel du dossier à chaque fois — pas
    seulement le dernier lot converti, sous peine de faire disparaître de la
    liste toute pièce qu'on n'a pas retouchée aujourd'hui.

    Lu par `outil_repetition` et `outil_lecture` au démarrage pour proposer
    automatiquement toutes les pièces disponibles, sans import manuel un par
    un. Jamais versionné (`.gitignore`) : comme les `REPET.json` qu'il
    recense, il ne doit exister que localement.
    """
    pieces = []

    for chemin in sorted(dossier.glob(f"*{config.SUFFIXE_REPET}")):
        try:
            document = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as erreur:
            print(f"   [ALERTE]  manifeste : {chemin.name} ignoré ({erreur})")
            continue

        unites = document.get("unites", [])
        repliques = sum(
            1
            for unite in unites
            for element in unite.get("elements", [])
            if element.get("type") == "replique"
        )

        pieces.append(
            {
                "fichier": chemin.name,
                "piece": document.get("piece", chemin.stem),
                "unites": len(unites),
                "repliques": repliques,
                "personnages": len(document.get("personnages", [])),
            }
        )

    chemin_manifeste = dossier / "manifest.json"
    io.ecrire_sidecar(
        chemin_manifeste,
        {"genere_le": datetime.now().isoformat(timespec="seconds"), "pieces": pieces},
    )

    print(f"   {chemin_manifeste.name} — {len(pieces)} pièce(s) disponible(s)")

    return chemin_manifeste


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
        required=True,
        help=(
            "dossier de sortie du REPET.json — typiquement ../pieces, le "
            "dossier partagé entre outil_repetition et outil_lecture. "
            "Toujours requis : convertir_fichier refuse d'écrire dans le "
            "dossier du DOCX lui-même (§ son garde-fou)."
        ),
    )

    journalisation.preparer_console()

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

    # Un seul manifeste pour le dossier partagé, réécrit une fois à la fin —
    # pas après chaque pièce, ce qui ne changerait rien au résultat final et
    # ferait N écritures atomiques au lieu d'une.
    regenerer_manifeste(options.dossier)

    return 1 if echec else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
