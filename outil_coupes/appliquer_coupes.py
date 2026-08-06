"""
Matérialise des coupes sur le `.docx` d'une pièce, **en préservant son format**.

L'outil ne régénère rien : il ouvre le `.docx` mis en forme d'origine (police,
tailles, marges, styles) et se contente d'y **envelopper les passages coupés
dans une marque de suppression Word** (`<w:del>`). Le texte intégral reste, en
barré, dans exactement la même mise en forme qu'avant — c'est le format de
restitution imposé par `DOCTRINE.md`. On relit dans Word et on accepte/rejette
chaque coupe.

Deux séries de coupes coexistent, distinguées par la couleur et par l'auteur de
révision (Word colore par auteur ; on force en plus la couleur du texte barré) :

- **passe 1** (coupes structurelles) → rouge, auteur « Coupe passe 1 » ;
- **passe 2** (rabotage fin) → bleu, auteur « Coupe passe 2 ».

Usage :

    python appliquer_coupes.py <source.docx> <coupes.json> --sortie <fichier.docx>

`coupes.json` : `{"coupes": [{"passe": 1, "debut": "…", "fin": "…"}, …]}`. Chaque
coupe désigne une plage du texte, par un couple `debut`/`fin` (de la première
occurrence de `debut` jusqu'à la fin de `fin`) ou par un `texte` exact. Le texte
sur lequel les ancres sont cherchées est la concaténation des runs du document,
paragraphes séparés par un saut de ligne. Une ancre introuvable ou ambiguë
arrête le programme : une coupe mal ancrée doit se voir, pas se poser au hasard.
"""

from __future__ import annotations

import argparse
import copy
import itertools
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

COULEURS = {1: "C00000", 2: "0070C0"}  # rouge, bleu
AUTEURS = {1: "Coupe passe 1", 2: "Coupe passe 2"}

_compteur_revision = itertools.count(1)


# ============================================================
# 1. RÉSOLUTION DES COUPES EN PLAGES DE CARACTÈRES
# ============================================================


@dataclass(frozen=True)
class Plage:
    """Une coupe résolue : intervalle [debut, fin) du texte plat, et sa passe."""

    debut: int
    fin: int
    passe: int


# Normalisations appliquées avant de chercher une ancre. Toutes remplacent un
# caractère par un autre de **même longueur** : les offsets restent donc valides
# sur le texte d'origine. On peut ainsi écrire les ancres simplement — apostrophe
# droite, espaces ordinaires — sans se soucier de la graphie exacte du document :
#
# - apostrophes typographiques → droite (le document mêle les deux) ;
# - saut de ligne → espace : une réplique en vers est faite de paragraphes
#   séparés, donc de sauts de ligne ; une ancre écrite d'un trait les traverse ;
# - espace insécable → espace : la typographie française en met avant « ! ? : ; »
#   et dans les guillemets, invisibles à la saisie d'une ancre.
_NORMALISATION = {
    0x2019: "'", 0x2018: "'", 0x02BC: "'",
    0x0A: " ", 0x0D: " ", 0x00A0: " ", 0x202F: " ",
}


def _normaliser(texte: str) -> str:
    return texte.translate(_NORMALISATION)


def _localiser_unique(texte: str, motif: str, etiquette: str) -> int:
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
    texte = _normaliser(texte)
    plages: list[Plage] = []

    for numero, coupe in enumerate(coupes, start=1):
        passe = coupe["passe"]
        if passe not in COULEURS:
            raise ValueError(f"coupe {numero} : passe {passe!r} inconnue (attendu 1 ou 2)")

        if "texte" in coupe:
            debut = _localiser_unique(texte, _normaliser(coupe["texte"]), f"coupe {numero}")
            fin = debut + len(coupe["texte"])
        else:
            debut = _localiser_unique(texte, _normaliser(coupe["debut"]), f"coupe {numero}, début")
            fin = _localiser_unique(texte, _normaliser(coupe["fin"]), f"coupe {numero}, fin") + len(coupe["fin"])
            if fin <= debut:
                raise ValueError(f"coupe {numero} : « fin » précède « début »")

        plages.append(Plage(debut, fin, passe))

    plages.sort(key=lambda p: p.debut)
    for precedente, suivante in zip(plages, plages[1:]):
        if suivante.debut < precedente.fin:
            raise ValueError(
                f"deux coupes se chevauchent (fin {precedente.fin} > début {suivante.debut})"
            )
    return plages


def passe_a_position(position: int, plages: list[Plage]) -> int:
    """Passe de coupe couvrant cette position (0 si conservée)."""
    for plage in plages:
        if plage.debut <= position < plage.fin:
            return plage.passe
    return 0


# ============================================================
# 2. LECTURE DU DOCX : TEXTE PLAT, RUNS, PARAGRAPHES
# ============================================================


@dataclass
class InfoRun:
    offset: int
    run: object  # docx.text.run.Run


@dataclass
class InfoParagraphe:
    offset: int
    texte: str
    gras: bool
    italique: bool


def _est_gras(paragraphe) -> bool:
    runs = [r for r in paragraphe.runs if r.text]
    return bool(runs) and all(r.bold for r in runs)


def _est_italique(paragraphe) -> bool:
    runs = [r for r in paragraphe.runs if r.text]
    return bool(runs) and all(r.italic for r in runs)


def lire_document(document):
    """
    Concatène les runs en un texte plat et note l'emplacement de chacun.

    Les paragraphes sont séparés par un saut de ligne — les ancres de dialogue,
    elles, n'en contiennent pas, mais une coupe peut ainsi couvrir plusieurs
    paragraphes consécutifs (nom + réplique, ou plusieurs répliques).
    """
    parts: list[str] = []
    runs: list[InfoRun] = []
    paras: list[InfoParagraphe] = []
    offset = 0

    for paragraphe in document.paragraphs:
        debut_para = offset
        texte_para: list[str] = []
        for run in paragraphe.runs:
            if run.text:
                runs.append(InfoRun(offset, run))
                parts.append(run.text)
                texte_para.append(run.text)
                offset += len(run.text)
        paras.append(
            InfoParagraphe(debut_para, "".join(texte_para),
                           _est_gras(paragraphe), _est_italique(paragraphe))
        )
        parts.append("\n")
        offset += 1

    return "".join(parts), runs, paras


# ============================================================
# 3. PROPAGATION : COUPER LE NOM D'UN PERSONNAGE ENTIÈREMENT COUPÉ
# ============================================================


def _para_entierement_coupe(para: InfoParagraphe, plages: list[Plage]) -> bool:
    if not para.texte:
        return False
    return all(passe_a_position(para.offset + i, plages) for i in range(len(para.texte)))


def propager_noms(paras: list[InfoParagraphe], plages: list[Plage]) -> list[Plage]:
    """
    Ajoute une plage couvrant le nom d'un personnage dont toute la réplique est coupée.

    Un nom de personnage est un paragraphe en gras suivi de paragraphes de
    dialogue (ni gras ni italique). S'ils sont tous entièrement coupés, le nom
    n'a plus de réplique et doit disparaître avec elle, dans la même couleur. Les
    titres d'acte ou de scène (gras aussi) ne sont jamais suivis directement de
    dialogue : ils ne sont donc pas emportés.
    """
    ajouts: list[Plage] = []

    for i, para in enumerate(paras):
        if not para.gras or not para.texte or _para_entierement_coupe(para, plages):
            continue

        repliques = []
        j = i + 1
        while j < len(paras) and not paras[j].gras and not paras[j].italique and paras[j].texte:
            repliques.append(paras[j])
            j += 1

        if repliques and all(_para_entierement_coupe(r, plages) for r in repliques):
            passe = passe_a_position(repliques[0].offset, plages)
            ajouts.append(Plage(para.offset, para.offset + len(para.texte), passe))

    return sorted(plages + ajouts, key=lambda p: p.debut)


# ============================================================
# 4. APPLICATION : ENVELOPPER LES RUNS COUPÉS DANS <w:del>
# ============================================================


def _nouveau_run(rpr, texte: str, *, supprime: bool, passe: int, date_iso: str):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run = OxmlElement("w:r")
    if rpr is not None:
        proprietes = copy.deepcopy(rpr)
        if supprime:
            for ancien in proprietes.findall(qn("w:color")):
                proprietes.remove(ancien)
            couleur = OxmlElement("w:color")
            couleur.set(qn("w:val"), COULEURS[passe])
            proprietes.append(couleur)
        run.append(proprietes)

    element_texte = OxmlElement("w:delText" if supprime else "w:t")
    element_texte.set(qn("xml:space"), "preserve")
    element_texte.text = texte
    run.append(element_texte)

    if not supprime:
        return run

    element_del = OxmlElement("w:del")
    element_del.set(qn("w:id"), str(next(_compteur_revision)))
    element_del.set(qn("w:author"), AUTEURS[passe])
    element_del.set(qn("w:date"), date_iso)
    element_del.append(run)
    return element_del


def appliquer_sur_run(info: InfoRun, plages: list[Plage], date_iso: str) -> None:
    """Découpe un run selon les plages et enveloppe les portions coupées."""
    from docx.oxml.ns import qn

    texte = info.run.text
    passes = [passe_a_position(info.offset + i, plages) for i in range(len(texte))]
    if not any(passes):
        return

    # segments consécutifs de même passe
    segments: list[list] = []
    for caractere, passe in zip(texte, passes):
        if segments and segments[-1][1] == passe:
            segments[-1][0] += caractere
        else:
            segments.append([caractere, passe])

    element = info.run._element
    rpr = element.find(qn("w:rPr"))
    for seg_texte, passe in segments:
        element.addprevious(
            _nouveau_run(rpr, seg_texte, supprime=bool(passe), passe=passe, date_iso=date_iso)
        )
    element.getparent().remove(element)


def construire_document(source: str, coupes: list[dict]):
    """Ouvre le DOCX source, applique les coupes, retourne le document modifié."""
    from docx import Document

    document = Document(source)
    texte, runs, paras = lire_document(document)
    plages = resoudre_plages(texte, coupes)
    plages = propager_noms(paras, plages)

    date_iso = datetime.now().isoformat(timespec="seconds")
    for info in runs:
        appliquer_sur_run(info, plages, date_iso)

    return document, texte, plages


# ============================================================
# 5. POINT D'ENTRÉE
# ============================================================


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(description="Matérialise des coupes en .docx à suivi de modifications.")
    analyseur.add_argument("source", help="le .docx mis en forme d'origine")
    analyseur.add_argument("coupes", help="fichier JSON des coupes")
    analyseur.add_argument("--sortie", required=True, help="chemin du .docx à écrire")
    options = analyseur.parse_args(argv)

    with open(options.coupes, encoding="utf-8") as f:
        coupes = json.load(f)["coupes"]

    document, texte, plages = construire_document(options.source, coupes)
    document.save(options.sortie)

    mots = sum(len(re.findall(r"\S+", texte[p.debut:p.fin])) for p in plages)
    par_passe = {passe: sum(1 for p in plages if p.passe == passe) for passe in (1, 2)}
    print(f"{options.sortie} écrit.")
    print(f"{len(plages)} coupes après propagation ({par_passe[1]} passe 1, {par_passe[2]} passe 2), "
          f"~{mots} mots barrés.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
