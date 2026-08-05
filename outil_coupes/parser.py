"""
Chargement des `<Livre>_REPET.json` produits par `outil_edition` (schéma
`repetition/2`, voir `../outil_edition/ARCHITECTURE.md` §5.7).

outil_coupes ne reparse plus le texte brut (docx/pdf/txt) : la structure —
personnages déjà canonisés, unités jouables, texte parlé déjà séparé des
didascalies — est résolue une fois pour toutes par
`outil_edition/theatre_editor/repet_export.py`. Ce module se limite au
chargement et à la validation du format attendu.
"""
import json
import re

SCHEMA_ATTENDU = "repetition/2"

# Marque une réplique collective (« TOUS. ») : ne nomme aucun personnage
# précis, donc exclue de toute présence par personnage (voir analyze.py).
JOKER_TOUS = "*"

MOTIF_MOT = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9']+")


def compter_mots(texte: str) -> int:
    return len(MOTIF_MOT.findall(texte))


def charger_repet(chemin: str) -> dict:
    """Charge et valide un `<Livre>_REPET.json`.

    Lève `ValueError` si le fichier n'a pas le schéma attendu, plutôt que de
    laisser analyze.py produire un rapport silencieusement faux sur un fichier
    d'un autre type (ex. un `LIMINAIRES.json` passé par erreur).
    """
    with open(chemin, encoding="utf-8") as f:
        document = json.load(f)

    schema = document.get("schema")
    if schema != SCHEMA_ATTENDU:
        raise ValueError(
            f"{chemin} : schéma {schema!r} inattendu — outil_coupes ne lit que "
            f"des REPET.json {SCHEMA_ATTENDU!r} (régénérez-le via outil_edition, "
            "étape 4)."
        )

    return document


def libelle_unite(unite: dict) -> str:
    """Libellé lisible d'une unité jouable, toujours unique.

    L'id est systématiquement inclus : un séparateur `***` sans titre ouvre
    une unité qui hérite de l'acte/scène courants, donc plusieurs unités
    peuvent légitimement partager le même acte et la même scène.
    """
    acte = unite.get("acte")
    scene = unite.get("scene")
    base = " - ".join(p for p in (acte, scene) if p) or "Unité sans titre"
    return f"{base} [{unite['id']}]"


if __name__ == "__main__":
    import sys

    doc = charger_repet(sys.argv[1])
    print(f"{doc['piece']} — {len(doc['unites'])} unités, {len(doc['personnages'])} personnages")
