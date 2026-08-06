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
    scenes: list[tuple[str, dict[str, int]]] = []  # (scène, {personnage: mots dits dans la scène})
    acte, label, presents, courant, offset = "", None, {}, None, 0

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
                label, presents, courant = f"{acte} {s.rstrip('.')}", {}, None
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
                                presents[perso] = presents.get(perso, 0) + m
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


def _court(label: str) -> str:
    m = re.match(r"ACTE\s+(\S+)\s+Sc[eè]ne\s+(\S+)", label, re.IGNORECASE)
    return f"{m.group(1)}.{m.group(2)}" if m else label


def _couleur(t: float) -> tuple[str, str]:
    """Blanc (rien) → vert foncé (charge maximale) ; texte clair quand le fond est sombre."""
    t = max(0.0, min(1.0, t))
    r, g, b = (int(255 + t * (c - 255)) for c in (30, 125, 60))
    return f"rgb({r},{g},{b})", ("#fff" if t > 0.55 else "#222")


def matrice_html(scenes, cast, alias, chemin, titre="Présence par scène"):
    """Écrit une matrice comédiens × scènes : rôles joués, mots, heatmap de charge."""
    role2com = {_canoniser(r, alias): com for com, roles in cast.items() for r in roles}
    comediens = sorted(cast)

    cellules: dict[str, dict[int, dict[str, int]]] = {c: {} for c in comediens}
    for i, (_, persos) in enumerate(scenes):
        for perso, mots in persos.items():
            com = role2com.get(perso)
            if com:
                case = cellules[com].setdefault(i, {})
                case[perso] = case.get(perso, 0) + mots

    maxi = max((sum(case.values()) for c in comediens for case in cellules[c].values()), default=1)
    totaux = {c: sum(sum(case.values()) for case in cellules[c].values()) for c in comediens}

    entete = "".join(f"<th>{_court(l)}</th>" for l, _ in scenes)
    corps = []
    for c in comediens:
        cellules_html = []
        for i in range(len(scenes)):
            case = cellules[c].get(i)
            if case:
                tot = sum(case.values())
                bg, fg = _couleur(tot / maxi)
                contenu = "<br>".join(
                    f"{r.title()} <b>{m}</b>" for r, m in sorted(case.items(), key=lambda x: -x[1])
                )
                cellules_html.append(f'<td style="background:{bg};color:{fg}">{contenu}</td>')
            else:
                cellules_html.append('<td class="vide"></td>')
        roles = " · ".join(r.title() for r in cast[c])
        corps.append(
            f'<tr><th>{c}<br><small>{roles}</small></th>{"".join(cellules_html)}'
            f'<td class="tot">{totaux[c]}</td></tr>'
        )

    html = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>{titre}</title>
<style>
 body{{font-family:"Segoe UI",system-ui,sans-serif;margin:1.5rem;color:#222}}
 h1{{font-size:1.15rem;margin:0 0 .2rem}} p{{color:#666;margin:.2rem 0 1rem;font-size:13px}}
 table{{border-collapse:collapse;font-size:12px}}
 th,td{{border:1px solid #e0e0e0;padding:4px 7px;text-align:center;vertical-align:middle}}
 thead th{{background:#f4f4f4}} td.vide{{background:#fbfbfb}}
 td.tot{{font-weight:bold;background:#eef2ff}} tbody th{{text-align:left;white-space:nowrap;background:#f4f4f4}}
 small{{color:#999;font-weight:normal}}
</style></head><body>
<h1>{titre}</h1>
<p>Chaque case : le·s rôle·s joué·s dans la scène et le nombre de mots de dialogue (après coupes). Le vert est d'autant plus soutenu que la scène est chargée pour ce·tte comédien·ne ; une case vide = absent·e.</p>
<table><thead><tr><th>Comédien</th>{entete}<th>Total</th></tr></thead>
<tbody>{"".join(corps)}</tbody></table>
</body></html>"""
    Path(chemin).write_text(html, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Bilan d'une distribution après coupes.")
    p.add_argument("source")
    p.add_argument("cast")
    p.add_argument("--coupes")
    p.add_argument("--relecteur")
    p.add_argument("--alias", action="append", default=[], metavar="A=B")
    p.add_argument("--matrice", metavar="FICHIER.html", help="écrit la matrice visuelle présence × scène")
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
    if options.matrice:
        matrice_html(scenes, cast, alias, options.matrice)
        print(f"\nMatrice visuelle écrite : {options.matrice}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
