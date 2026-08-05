"""
Reconstruit un `.docx` mis en forme à partir d'un `<Livre>_REPET.json`.

**À quoi cela sert.** L'étape 4 (`docx_export.executer`) écrit le `.docx` et le
`REPET.json` ensemble, à partir des mêmes lignes classées — c'est le chemin
normal, et il reste le seul qui produise un document fidèle à 100 % (voir
ARCHITECTURE.md §D16). Cet outil sert pour le cas contraire : vous n'avez plus
que le `REPET.json` (le `.docx` ou l'`EDIT.txt` sont perdus, ou le JSON a été
retouché à la main) et vous voulez un document imprimable qui en reprenne le
contenu, avec la même police et les mêmes tailles que `config.py`.

    python outils/repet_vers_docx.py "pieces/Ma pièce_REPET.json" --dossier reconstitutions/

**C'est une reconstruction, pas un aller-retour parfait.** Le `REPET.json` a
délibérément perdu, à l'écriture, des informations que le DOCX portait :

- `didascalie`, `didascalie_longue` et `prologue` sont tous les trois rendus
  sous le seul type `"didascalie"` dans le JSON (voir
  `repet_export.TYPES_ELEMENT_SIMPLE`). Cet outil retrouve la variante longue
  par la même règle de longueur que le classement d'origine
  (`config.LONGUEUR_DIDASCALIE_LONGUE`), mais ne peut pas distinguer un
  `prologue` d'une didascalie longue ordinaire : les deux reviennent en
  `didascalie_longue`.
- Le séparateur entre personnages d'une réplique collective est toujours
  réémis avec `/` (la convention actuelle), même si le document source
  écrivait « et » ou « ET ».
- Le point final d'un nom de personnage, retiré par `repet_export.nom_personnage`,
  est simplement rajouté à la réécriture.
- Un séparateur `***` immédiatement suivi d'un titre d'acte ou de scène, sans
  aucun contenu entre les deux, ne laisse aucune trace dans le JSON : l'unité
  qu'il aurait ouverte est vide, et `repet_export` l'écarte avant l'écriture
  (voir `repet_export._ouvrir_unite`). Le titre qui suit est bien réémis ; le
  `*` qui le précédait dans le DOCX d'origine, lui, ne l'est pas.

Aucune de ces pertes ne change le texte joué ni sa structure acte/scène/
personnage — seules des nuances de mise en forme peuvent différer de
l'original.

**N'écrit jamais dans `pieces/`.** `--dossier` est obligatoire et doit désigner
un dossier distinct de celui qui contient les `REPET.json` : le but est de ne
jamais risquer d'écraser un `.docx` canonique, produit par le chemin normal,
avec cette reconstruction approximative.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parent.parent

if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from theatre_editor import config, docx_export, repet_export  # noqa: E402
from theatre_editor.utils import blocks  # noqa: E402
from theatre_editor.utils import logging as journalisation  # noqa: E402

# Isole les mots d'un texte, séparateur compris, pour réinsérer une didascalie
# interne exactement au mot qu'annonce son `avant_mot` (voir `_marquer_jeu`).
_MOTIF_ESPACES = re.compile(r"(\s+)")


# ============================================================
# 1. LECTURE ET VALIDATION DU JSON
# ============================================================


def charger_repet(chemin: Path) -> dict[str, Any]:
    """Charge un `REPET.json` et vérifie qu'il est de la version attendue."""
    document = json.loads(chemin.read_text(encoding="utf-8"))

    schema = document.get("schema")
    if schema != config.SCHEMA_REPET:
        raise ValueError(
            f"{chemin.name} : schéma « {schema} » inattendu — "
            f"cet outil ne sait lire que « {config.SCHEMA_REPET} »"
        )

    return document


# ============================================================
# 2. RECONSTRUCTION DU DOCUMENT
# ============================================================


def construire_document(repet: dict[str, Any]):
    """
    Reconstruit un document `python-docx` à partir d'un `REPET.json` chargé.

    Repose entièrement sur `docx_export.creer_document()` et
    `docx_export.ajouter_paragraphe()` : ce sont eux qui portent la police, les
    tailles, les marges et le découpage des emphases internes. Dupliquer cette
    logique ici l'exposerait à diverger du DOCX produit par le chemin normal.
    """
    document = docx_export.creer_document()

    for liminaire in repet.get("liminaires", []):
        _ajouter_ligne(document, liminaire["texte"], blocks.TypeLigne(liminaire["type"]))

    _ajouter_unites(document, repet.get("unites", []))

    return document


def _ajouter_ligne(document, texte: str, type_ligne: blocks.TypeLigne) -> None:
    ligne = blocks.LigneClassee(brut=texte, texte=texte, type=type_ligne)
    docx_export.ajouter_paragraphe(document, ligne)


def _ajouter_separateur(document) -> None:
    ligne = blocks.LigneClassee(brut="", texte="", type=blocks.TypeLigne.SEPARATEUR)
    docx_export.ajouter_paragraphe(document, ligne)


def _ajouter_unites(document, unites: list[dict[str, Any]]) -> None:
    """
    Rejoue les unités jouables, en réémettant les titres d'acte et de scène
    qui les ont ouvertes côté source.

    Une unité ne porte que l'acte et la scène **courants** — pas la ligne qui
    les a annoncés. Le titre à réémettre se déduit donc par comparaison avec
    l'unité précédente : si `acte` diffère, c'est qu'un `**ACTE...**` a été lu
    entre les deux ; de même pour `scene`. `None, None` en sentinelle de départ
    couvre aussi bien une pièce classique (première unité déjà titrée qu'une
    pièce qui commence directement en scène 2, cf. l'exemple d'ARCHITECTURE.md
    §5.7) que celle d'un acte et d'une scène qui changent au même endroit — un
    « ACTE II » aussitôt suivi d'une scène, sans contenu propre entre les deux,
    ne laisse dans le JSON qu'une seule unité portant les deux changements à la
    fois (l'unité d'acte, vide, a été supprimée par `repet_export`).
    """
    acte_precedent: str | None = None
    scene_precedente: str | None = None

    for indice, unite in enumerate(unites):
        if unite.get("implicite") and indice > 0:
            _ajouter_separateur(document)

        acte = unite.get("acte")
        scene = unite.get("scene")

        if acte is not None and acte != acte_precedent:
            _ajouter_ligne(document, acte, blocks.TypeLigne.TITRE_ACTE)
            # Un nouvel acte remet la scène à zéro côté source (voir
            # `repet_export._ouvrir_unite`) : un changement de scène qui
            # suivrait immédiatement doit donc être réémis lui aussi, pas
            # confondu avec la scène qu'on vient de quitter.
            scene_precedente = None

        if scene is not None and scene != scene_precedente:
            _ajouter_ligne(document, scene, blocks.TypeLigne.TITRE_SCENE)

        acte_precedent, scene_precedente = acte, scene

        for element in unite.get("elements", []):
            _ajouter_element(document, element)


def _ajouter_element(document, element: dict[str, Any]) -> None:
    type_element = element["type"]

    if type_element == "lieu":
        _ajouter_ligne(document, element["texte"], blocks.TypeLigne.LIEU)
        return

    if type_element == "didascalie":
        est_longue = len(element["texte"]) > config.LONGUEUR_DIDASCALIE_LONGUE
        type_ligne = blocks.TypeLigne.DIDASCALIE_LONGUE if est_longue else blocks.TypeLigne.DIDASCALIE
        _ajouter_ligne(document, element["texte"], type_ligne)
        return

    if type_element == "texte_sans_personnage":
        _ajouter_ligne(document, element["texte"], blocks.TypeLigne.TEXTE)
        return

    if type_element == "replique":
        _ajouter_replique(document, element)
        return

    raise ValueError(f"type d'élément inconnu dans le REPET.json : « {type_element} »")


def _ajouter_replique(document, element: dict[str, Any]) -> None:
    _ajouter_ligne(document, _label_personnages(element["personnages"]), blocks.TypeLigne.PERSONNAGE)

    texte_marque = _marquer_jeu(element["texte"], element.get("didascalies_internes", []))

    # Une réplique en vers tient sur plusieurs lignes dans `texte`, séparées
    # par `\n` (voir `repet_export.separer_parole_et_jeu`) : chacune redevient
    # ici le paragraphe distinct qu'elle était dans l'`EDIT.txt` d'origine.
    for ligne in texte_marque.split("\n"):
        _ajouter_ligne(document, ligne, blocks.TypeLigne.TEXTE)


def _label_personnages(personnages: list[str]) -> str:
    """Réécrit le label de personnage, point final compris."""
    if personnages == [repet_export.JOKER_TOUS]:
        return f"{repet_export.MARQUEUR_TOUS}."

    return "/".join(personnages) + "."


def _marquer_jeu(texte: str, didascalies: list[dict[str, Any]]) -> str:
    """
    Réinsère les didascalies internes dans le texte, sous forme `*jeu*`.

    Inverse de `repet_export.separer_parole_et_jeu()` : chaque didascalie est
    replacée juste avant le mot compté par `avant_mot`, pour que
    `blocks.decouper_en_runs()` — appelé par `docx_export` sur toute ligne de
    type TEXTE — la retrouve et la rende en italique, exactement comme elle
    l'était dans l'`EDIT.txt` d'origine.
    """
    if not didascalies:
        return texte

    par_position: dict[int, list[str]] = {}
    for didascalie in didascalies:
        par_position.setdefault(didascalie["avant_mot"], []).append(didascalie["texte"])

    jetons = _MOTIF_ESPACES.split(texte)
    resultat: list[str] = []
    compteur = 0

    for jeton in jetons:
        if not jeton or jeton.isspace():
            resultat.append(jeton)
            continue

        for texte_didascalie in par_position.get(compteur, []):
            resultat.append(f"*{texte_didascalie}* ")

        resultat.append(jeton)
        compteur += 1

    for texte_didascalie in par_position.get(compteur, []):
        resultat.append(f" *{texte_didascalie}*")

    return "".join(resultat)


# ============================================================
# 3. CONVERSION D'UN FICHIER
# ============================================================


def convertir_fichier(chemin_json: Path, dossier_sortie: Path) -> Path:
    """
    Reconstruit le `.docx` d'un `REPET.json` et l'écrit dans `dossier_sortie`.

    Returns:
        Le chemin du `.docx` écrit.
    """
    repet = charger_repet(chemin_json)

    document = construire_document(repet)

    dossier_sortie.mkdir(parents=True, exist_ok=True)
    chemin_docx = dossier_sortie / f"{repet['piece']}{config.SUFFIXE_DOCX}"
    document.save(str(chemin_docx))

    print(f"   {chemin_docx.name} — reconstruit depuis {chemin_json.name}")

    for avertissement in repet.get("avertissements", []):
        print(f"   [ALERTE]  {avertissement}")

    return chemin_docx


# ============================================================
# 4. POINT D'ENTRÉE DE L'ÉTAPE
# ============================================================


def main(arguments: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(
        description=(
            "Reconstruit un .docx à partir d'un ou plusieurs REPET.json — "
            "une approximation utile quand le .docx ou l'EDIT.txt d'origine "
            "ont été perdus (voir le docstring du module pour les pertes "
            "connues)."
        )
    )
    analyseur.add_argument(
        "repet", type=Path, nargs="+", help="le ou les REPET.json à convertir"
    )
    analyseur.add_argument(
        "--dossier",
        type=Path,
        required=True,
        help=(
            "dossier de sortie du .docx reconstruit — toujours requis, et "
            "toujours différent du dossier des REPET.json, pour ne jamais "
            "risquer d'écraser un .docx canonique avec cette reconstruction "
            "approximative."
        ),
    )

    journalisation.preparer_console()

    options = analyseur.parse_args(arguments)
    echec = False

    for chemin in options.repet:
        if not chemin.is_file():
            print(f"introuvable : {chemin}", file=sys.stderr)
            echec = True
            continue

        try:
            convertir_fichier(chemin, options.dossier)
        except ValueError as erreur:
            print(f"{chemin} : {erreur}", file=sys.stderr)
            echec = True

        print()

    return 1 if echec else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
