"""
Bilan d'une distribution APRÈS coupes : équilibre par comédien, conflits de
présence et changements de costume.

C'est la règle « recalculer après chaque passe » appliquée à la distribution :
on ne juge pas des coupes sur le texte intégral, mais sur ce qui reste réellement
à jouer. L'outil recompte le dialogue non coupé par personnage, l'agrège par
comédien via un `cast.json`, puis vérifie la faisabilité scénique du multi-rôles.

    python bilan_distribution.py <source.docx> <cast.json> \
        [--coupes coupes.json] [--relecteur relecteur.docx] [--alias "UN SEIGNEUR=ANTONIO"]

- `source.docx` : le texte mis en forme d'origine ;
- `cast.json` : `{"C1": ["RÔLE A", "RÔLE B"], …}` (doublages inclus) ;
- `--coupes` / `--relecteur` : les coupes à appliquer avant de compter (les deux
  se cumulent) ; sans elles, le bilan porte sur le texte intégral ;
- `--alias` : un rôle anonyme joué sous les traits d'un autre (même costume),
  répétable — pour ne pas compter un faux changement de costume.

Limite : la présence est déduite des répliques (qui **parle**). Un personnage
présent mais muet n'est pas vu — à recouper avec les entrées/sorties.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from docx import Document

import appliquer_coupes as ac
import fusion_coupes as fc

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_TITRE = re.compile(r"^(ACTE|SC[EÈ]NE|Sc[eè]ne)\b", re.IGNORECASE)
_JONCTION = re.compile(r"\s*/\s*|\s+et\s+", re.IGNORECASE)


def _canoniser(nom: str, alias: dict[str, str]) -> str:
    nom = re.split(r"\s*[\[(]", nom)[0]
    c = re.sub(r"[.,:;!?\s]+$", "", nom.strip()).replace("’", "'").upper().strip()
    return alias.get(c, c)


def masque_coupe(document, texte, paras, coupes, relecteur):
    """Masque booléen : True là où un caractère est coupé (coupes ∪ relecteur)."""
    coupe = [False] * len(texte)
    if coupes:
        for plage in ac.propager_noms(paras, ac.resoudre_plages(texte, coupes)):
            for i in range(plage.debut, plage.fin):
                coupe[i] = True
    if relecteur:
        texte_rel, brut = fc.masque_relecteur(relecteur)
        for i, c in enumerate(fc.aligner_masque(texte, texte_rel, brut)):
            if c:
                coupe[i] = True
    return coupe


def parcourir(document, coupe, alias):
    """
    Un seul parcours du document → (mots restants par personnage, présence par scène).

    Pour chaque réplique, on ne compte que les mots des runs non italiques et non
    coupés (le dialogue effectivement dit). Le personnage courant est le dernier
    nom en gras rencontré ; un titre d'acte/scène le remet à zéro.
    """
    poids: dict[str, int] = {}
    scenes: list[tuple[str, set[str]]] = []
    acte, label, presents, courant, offset = "", None, set(), None, 0

    for para in document.paragraphs:
        runs = [r for r in para.runs if r.text]
        texte = "".join(r.text for r in para.runs)
        s = texte.strip()
        gras = bool(runs) and all(r.bold for r in runs)
        ital = bool(runs) and all(r.italic for r in runs)

        if gras and s:
            if re.match(r"^ACTE\b", s, re.IGNORECASE):
                acte, courant = s.rstrip("."), None
            elif _TITRE.match(s):
                if label:
                    scenes.append((label, presents))
                label, presents, courant = f"{acte} {s.rstrip('.')}", set(), None
            else:
                courant = [_canoniser(n, alias) for n in _JONCTION.split(texte)]
        elif s and not ital and courant:
            o = offset
            for r in para.runs:
                if r.text and not r.italic:
                    restant = "".join(c for k, c in enumerate(r.text) if not coupe[o + k])
                    m = len(re.findall(r"\S+", restant))
                    if m:
                        for perso in courant:
                            if perso and perso != "TOUS":
                                poids[perso] = poids.get(perso, 0) + m
                                presents.add(perso)
                o += len(r.text)
        offset += sum(len(r.text) for r in para.runs) + 1

    if label:
        scenes.append((label, presents))
    return poids, scenes


def afficher_equilibre(poids, cast, alias):
    role2com = {_canoniser(r, alias): com for com, roles in cast.items() for r in roles}
    par_com: dict[str, int] = {}
    orphelins: dict[str, int] = {}
    for perso, m in poids.items():
        com = role2com.get(perso)
        (par_com if com else orphelins)[com or perso] = (par_com if com else orphelins).get(com or perso, 0) + m

    total = sum(par_com.values()) + sum(orphelins.values()) or 1
    cible = 100 / len(cast)
    print(f"\n=== ÉQUILIBRE PAR COMÉDIEN ({sum(poids.values())} mots de dialogue restants) ===")
    print(f"Cible : {cible:.1f}% chacun\n{'Comédien':10} {'mots':>7} {'%':>7}  écart")
    print("-" * 40)
    for com in sorted(par_com, key=lambda c: -par_com[c]):
        pct = 100 * par_com[com] / total
        print(f"{com:10} {par_com[com]:7d} {pct:6.1f}% {pct - cible:+6.1f}")
    if orphelins:
        print(f"\n⚠️  rôles non distribués : { {k: v for k, v in sorted(orphelins.items())} }")


def afficher_faisabilite(scenes, cast, alias):
    role2com = {_canoniser(r, alias): com for com, roles in cast.items() for r in roles}
    multi = {c for c in cast if len(cast[c]) > 1}

    print("\n=== CONFLITS DE PRÉSENCE (bloquants) ===")
    conflit = False
    for label, presents in scenes:
        par_com: dict[str, list[str]] = {}
        for perso in presents:
            com = role2com.get(perso)
            if com:
                par_com.setdefault(com, []).append(perso)
        for com, roles in sorted(par_com.items()):
            if len(roles) > 1:
                conflit = True
                print(f"  {label:22} {com} : {' + '.join(sorted(roles))}")
    if not conflit:
        print("  aucun.")

    print("\n=== CHANGEMENTS DE COSTUME (rôle différent, scènes qui s'enchaînent) ===")
    par_scene: dict[str, dict[int, set]] = {}
    for i, (label, presents) in enumerate(scenes):
        for perso in presents:
            com = role2com.get(perso)
            if com in multi:
                par_scene.setdefault(com, {}).setdefault(i, set()).add(perso)
    for com in sorted(par_scene):
        sc = par_scene[com]
        for a, b in zip(sorted(sc), sorted(sc)[1:]):
            if b == a + 1 and sc[a].isdisjoint(sc[b]):
                meme_acte = scenes[a][0].split()[:2] == scenes[b][0].split()[:2]
                tag = "  ← même acte, RAPIDE" if meme_acte else ""
                print(f"  {com}: {scenes[a][0]} [{'/'.join(sorted(sc[a]))}] → "
                      f"{scenes[b][0]} [{'/'.join(sorted(sc[b]))}]{tag}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Bilan d'une distribution après coupes.")
    p.add_argument("source")
    p.add_argument("cast")
    p.add_argument("--coupes")
    p.add_argument("--relecteur")
    p.add_argument("--alias", action="append", default=[], metavar="A=B")
    options = p.parse_args(argv)

    alias = {}
    for a in options.alias:
        cle, _, valeur = a.partition("=")
        alias[cle.strip().upper()] = valeur.strip().upper()

    document = Document(options.source)
    texte, runs, paras = ac.lire_document(document)
    coupes = json.load(open(options.coupes, encoding="utf-8"))["coupes"] if options.coupes else None
    coupe = masque_coupe(document, texte, paras, coupes, options.relecteur)

    poids, scenes = parcourir(document, coupe, alias)
    cast = json.load(open(options.cast, encoding="utf-8"))
    afficher_equilibre(poids, cast, alias)
    afficher_faisabilite(scenes, cast, alias)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
