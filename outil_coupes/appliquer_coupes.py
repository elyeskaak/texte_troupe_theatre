"""
Matérialise des coupes sur le texte d'une pièce en un `.docx` à suivi de
modifications Word — le texte intégral est conservé, les passages coupés
apparaissent barrés, colorés selon la passe de coupe.

C'est le format de restitution imposé par `DOCTRINE.md` : rien n'est effacé, on
relit dans Word et on accepte/rejette chaque coupe. Ici, deux séries de coupes
coexistent, distinguées par la couleur et par l'auteur de révision, pour qu'on
puisse traiter les deux niveaux indépendamment :

- **passe 1** (coupes structurelles validées en premier) → rouge, auteur « Coupe passe 1 » ;
- **passe 2** (rabotage fin) → bleu, auteur « Coupe passe 2 ».

Usage :

    python appliquer_coupes.py <source.txt> <coupes.json> --sortie <fichier.docx>

`source.txt` est l'`EDIT.txt` de la pièce (convention typographique : `**titre
ou personnage**`, `*didascalie*`, `***` séparateur, texte nu pour les répliques).

`coupes.json` :

    {
      "coupes": [
        {"passe": 1, "debut": "A-t-il fondu en larmes", "fin": "voir pleurer !"},
        {"passe": 2, "texte": "un passage exact à retirer en entier"}
      ]
    }

Chaque coupe désigne une plage du texte source, soit par un couple `debut`/`fin`
(de la première occurrence de `debut` jusqu'à la fin de `fin`), soit par un
`texte` exact. Toute ancre introuvable ou ambiguë (présente plusieurs fois)
arrête le programme : une coupe mal ancrée doit se voir, pas se poser au hasard.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime

# La console Windows par défaut (cp1252) ne sait pas encoder les guillemets
# typographiques ni les accents du texte : sans ceci, un message d'erreur citant
# une ancre planterait au lieu de s'afficher.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Une couleur et un auteur de révision par passe. Word colore les marques de
# révision par auteur ; on force en plus la couleur du texte barré, pour que la
# distinction tienne quel que soit le réglage d'affichage du lecteur.
COULEURS = {1: "C00000", 2: "0070C0"}  # rouge, bleu
AUTEURS = {1: "Coupe passe 1", 2: "Coupe passe 2"}

_compteur_revision = itertools.count(1)


# ============================================================
# 1. RÉSOLUTION DES COUPES EN PLAGES DE CARACTÈRES
# ============================================================


@dataclass(frozen=True)
class Plage:
    """Une coupe résolue : intervalle [debut, fin) du texte, et sa passe."""

    debut: int
    fin: int
    passe: int


def _localiser_unique(texte: str, motif: str, etiquette: str) -> int:
    """Position de l'unique occurrence de `motif`, ou erreur explicite."""
    premiere = texte.find(motif)
    if premiere == -1:
        raise ValueError(f"ancre introuvable ({etiquette}) : « {motif[:60]} »")
    if texte.find(motif, premiere + 1) != -1:
        raise ValueError(
            f"ancre ambiguë ({etiquette}), présente plusieurs fois : "
            f"« {motif[:60]} » — allongez-la pour la rendre unique."
        )
    return premiere


def resoudre_plages(texte: str, coupes: list[dict]) -> list[Plage]:
    """Convertit les coupes en plages de caractères, triées et sans chevauchement."""
    plages: list[Plage] = []

    for numero, coupe in enumerate(coupes, start=1):
        passe = coupe["passe"]
        if passe not in COULEURS:
            raise ValueError(f"coupe {numero} : passe {passe!r} inconnue (attendu 1 ou 2)")

        if "texte" in coupe:
            debut = _localiser_unique(texte, coupe["texte"], f"coupe {numero}")
            fin = debut + len(coupe["texte"])
        else:
            debut = _localiser_unique(texte, coupe["debut"], f"coupe {numero}, début")
            pos_fin = _localiser_unique(texte, coupe["fin"], f"coupe {numero}, fin")
            fin = pos_fin + len(coupe["fin"])
            if fin <= debut:
                raise ValueError(f"coupe {numero} : « fin » précède « début »")

        plages.append(Plage(debut, fin, passe))

    plages.sort(key=lambda p: p.debut)
    for precedente, suivante in zip(plages, plages[1:]):
        if suivante.debut < precedente.fin:
            raise ValueError(
                "deux coupes se chevauchent — vérifiez le registre "
                f"(fin {precedente.fin} > début {suivante.debut})"
            )

    return plages


def passe_a_position(position: int, plages: list[Plage]) -> int:
    """Passe de coupe couvrant cette position (0 si le caractère est conservé)."""
    for plage in plages:
        if plage.debut <= position < plage.fin:
            return plage.passe
    return 0


# ============================================================
# 2. DÉCOUPAGE D'UNE LIGNE EN FRAGMENTS STYLÉS
# ============================================================


@dataclass
class Fragment:
    """Un morceau de ligne homogène : même style et même statut de coupe."""

    texte: str
    gras: bool
    italique: bool
    passe: int  # 0 = conservé


def _fragments(
    contenu: str,
    passes: list[int],
    *,
    gras: bool,
    inline_italique: bool,
    italique_base: bool = False,
) -> list[Fragment]:
    """
    Découpe `contenu` en fragments homogènes.

    `passes[i]` donne la passe de coupe du caractère `contenu[i]`. Si
    `inline_italique`, les `*` basculent l'italique et ne s'affichent pas (usage
    des répliques). `italique_base` fixe l'italique de départ : à `True` pour une
    didascalie, dont tout le contenu est en italique.
    """
    fragments: list[Fragment] = []
    italique = italique_base

    for caractere, passe in zip(contenu, passes):
        if inline_italique and caractere == "*":
            italique = not italique
            continue

        if fragments and fragments[-1].gras == gras and fragments[-1].italique == italique \
                and fragments[-1].passe == passe:
            fragments[-1].texte += caractere
        else:
            fragments.append(Fragment(caractere, gras, italique, passe))

    return fragments


def analyser_ligne(ligne: str, passes: list[int]) -> tuple[str, list[Fragment]]:
    """
    Classe une ligne (convention typographique) et la découpe en fragments.

    Retourne le type (`titre`, `didascalie`, `separateur`, `replique`) et les
    fragments à rendre, marqueurs `**`/`*` retirés.
    """
    strip = ligne.strip()

    if strip == "***":
        return "separateur", [Fragment("* * *", False, False, max(passes) if passes else 0)]

    if len(strip) >= 4 and strip.startswith("**") and strip.endswith("**"):
        return "titre", _fragments(strip[2:-2], passes[2:-2], gras=True, inline_italique=False)

    if len(strip) >= 2 and strip.startswith("*") and strip.endswith("*"):
        return "didascalie", _fragments(
            strip[1:-1], passes[1:-1], gras=False, inline_italique=False, italique_base=True
        )

    return "replique", _fragments(strip, passes, gras=False, inline_italique=True)


# ============================================================
# 3. GÉNÉRATION DU DOCX À SUIVI DE MODIFICATIONS
# ============================================================


def _ajouter_fragment(paragraphe, fragment: Fragment, date_iso: str) -> None:
    """Ajoute un fragment au paragraphe : run normal, ou run supprimé si coupé."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    if not fragment.texte:
        return

    if fragment.passe == 0:
        run = paragraphe.add_run(fragment.texte)
        run.bold = fragment.gras or None
        run.italic = fragment.italique or None
        return

    # Run supprimé : <w:del><w:r><w:delText>… enveloppé dans une marque de
    # révision. python-docx n'a pas d'API pour cela, on construit l'XML.
    element_del = OxmlElement("w:del")
    element_del.set(qn("w:id"), str(next(_compteur_revision)))
    element_del.set(qn("w:author"), AUTEURS[fragment.passe])
    element_del.set(qn("w:date"), date_iso)

    run = OxmlElement("w:r")
    proprietes = OxmlElement("w:rPr")
    if fragment.gras:
        proprietes.append(OxmlElement("w:b"))
    if fragment.italique:
        proprietes.append(OxmlElement("w:i"))
    couleur = OxmlElement("w:color")
    couleur.set(qn("w:val"), COULEURS[fragment.passe])
    proprietes.append(couleur)
    run.append(proprietes)

    texte_supprime = OxmlElement("w:delText")
    texte_supprime.set(qn("xml:space"), "preserve")
    texte_supprime.text = fragment.texte
    run.append(texte_supprime)

    element_del.append(run)
    paragraphe._p.append(element_del)


def construire_document(texte: str, plages: list[Plage]):
    """Construit le document Word à partir du texte source et des plages coupées."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    document = Document()
    date_iso = datetime.now().isoformat(timespec="seconds")

    offset = 0
    for ligne in texte.splitlines(keepends=True):
        longueur = len(ligne)
        contenu = ligne.rstrip("\n")

        if contenu.strip():
            passes = [passe_a_position(offset + i, plages) for i in range(len(contenu))]
            type_ligne, fragments = analyser_ligne(contenu, passes)

            paragraphe = document.add_paragraph()
            if type_ligne in ("titre", "separateur"):
                paragraphe.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for fragment in fragments:
                _ajouter_fragment(paragraphe, fragment, date_iso)

        offset += longueur

    return document


# ============================================================
# 4. POINT D'ENTRÉE
# ============================================================


def charger_coupes(chemin: str) -> list[dict]:
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)["coupes"]


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    analyseur.add_argument("source", help="EDIT.txt de la pièce")
    analyseur.add_argument("coupes", help="fichier JSON des coupes")
    analyseur.add_argument("--sortie", required=True, help="chemin du .docx à écrire")
    options = analyseur.parse_args(argv)

    with open(options.source, encoding="utf-8") as f:
        texte = f.read()

    plages = resoudre_plages(texte, charger_coupes(options.coupes))

    document = construire_document(texte, plages)
    document.save(options.sortie)

    mots_coupes = sum(
        len(re.findall(r"\S+", texte[p.debut:p.fin])) for p in plages
    )
    par_passe = {passe: sum(1 for p in plages if p.passe == passe) for passe in (1, 2)}
    print(f"{options.sortie} écrit.")
    print(f"{len(plages)} coupes ({par_passe[1]} en passe 1, {par_passe[2]} en passe 2), "
          f"~{mots_coupes} mots barrés.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
