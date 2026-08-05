"""
Usage:
  python analyze.py detect <fichier_REPET.json>
      -> rapport de structure : unités, personnages, avertissements déjà
         remontés par outil_edition (rien à valider côté classification —
         c'est déjà fait dans le REPET.json).

  python analyze.py compute <fichier_REPET.json> [--cast cast.json] [--target 15000]
      -> comptage mots/répliques par personnage + matrice de présence par
         unité jouable
      cast.json    : {"Comédien A": ["ALCESTE"], "Comédien B": ["PHILINTE", "LE PRINCE"]}
                     agrège le calcul par comédien (doublages inclus) plutôt que par personnage
      --target N   : signale l'écart au nombre de mots cible et classe les unités par poids
                     décroissant pour repérer les meilleures candidates à une coupe large
"""
import sys
import json
from collections import defaultdict

from parser import charger_repet, compter_mots, libelle_unite, JOKER_TOUS

# La console Windows par défaut (cp1252) ne sait pas encoder les accents
# combinés à l'emoji ⚠️ ni certaines majuscules accentuées : sans ceci, le
# rapport plante au premier personnage flagué plutôt que de simplement
# s'afficher.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def cmd_detect(path):
    doc = charger_repet(path)
    unites = doc["unites"]

    n_implicites = sum(1 for u in unites if u["implicite"])
    n_repliques = sum(1 for u in unites for e in u["elements"] if e["type"] == "replique")
    n_didascalies = sum(1 for u in unites for e in u["elements"] if e["type"] == "didascalie")
    n_sans_personnage = sum(
        1 for u in unites for e in u["elements"] if e["type"] == "texte_sans_personnage"
    )

    print(f"=== RAPPORT DE STRUCTURE : {doc['piece']} ===\n")
    print(f"Source          : {path} (schéma {doc['schema']})")
    print(f"Généré le       : {doc.get('genere_le', '?')} par {doc.get('outil', '?')}\n")
    print(f"Unités jouables : {len(unites)}  (dont {n_implicites} sans titre d'acte/scène — séparateurs ***)")
    print(f"Répliques       : {n_repliques}")
    print(f"Didascalies     : {n_didascalies}")
    print(f"Personnages     : {len(doc['personnages'])}\n")

    print("--- Personnages (nom canonique -> répliques, mots) ---")
    for p in doc["personnages"]:
        print(f"  {p['nom']:30s} {p['repliques']:4d} répliques  {p['mots']:5d} mots")

    if n_sans_personnage:
        print(f"\n⚠️  {n_sans_personnage} ligne(s) de texte sans personnage annoncé, conservée(s) "
              "mais non attribuée(s) à un personnage — voir avertissements ci-dessous.")

    if doc["avertissements"]:
        print(f"\n--- Avertissements remontés par outil_edition ({len(doc['avertissements'])}) ---")
        for a in doc["avertissements"]:
            print(f"  - {a}")
    else:
        print("\nAucun avertissement remonté par outil_edition.")

    if unites and n_implicites == len(unites):
        print("\nℹ️  Aucun titre d'acte/scène dans cette pièce (texte contemporain découpé par ***) : "
              "la matrice de présence utilisera chaque unité jouable comme grain, faute de titre à afficher.")


def cmd_compute(path, cast_path=None, target=None):
    doc = charger_repet(path)
    unites = doc["unites"]

    total_words = sum(p["mots"] for p in doc["personnages"]) or 1
    total_unites = len(unites) or 1

    # -- présence par unité + mots par unité (grain le plus fin disponible) --
    presence = defaultdict(set)  # id d'unité -> {personnages}
    words_by_unite = defaultdict(int)
    unites_avec_tous = 0

    for u in unites:
        for perso in u["personnages"]:
            if perso == JOKER_TOUS:
                unites_avec_tous += 1
                continue
            presence[u["id"]].add(perso)
        for e in u["elements"]:
            if e["type"] == "replique":
                words_by_unite[u["id"]] += compter_mots(e["texte"])

    print(f"=== ANALYSE : {doc['piece']} ===\n")
    print(f"{len(doc['personnages'])} personnages | {total_unites} unités jouables | {total_words} mots de dialogue comptés\n")
    print(f"{'Personnage':25s} {'Mots':>7s} {'%':>6s} {'Répliques':>10s} {'Unités prés.':>13s} {'% unités':>9s}  Flag")
    print("-" * 90)

    rows = []
    for p in doc["personnages"]:
        nom, w, r = p["nom"], p["mots"], p["repliques"]
        pct_words = 100 * w / total_words
        unites_presentes = sum(1 for u in unites if nom in presence[u["id"]])
        pct_unites = 100 * unites_presentes / total_unites
        rows.append((nom, w, pct_words, r, unites_presentes, pct_unites))

    avg_pct = sum(row[2] for row in rows) / len(rows) if rows else 0

    for nom, w, pct_words, r, unites_presentes, pct_unites in sorted(rows, key=lambda x: -x[1]):
        flag = ""
        if pct_words < avg_pct * 0.25 and pct_words < 3:
            flag = "⚠️ rôle creux"
        elif pct_words > avg_pct * 2.5 and pct_words > 15:
            flag = "⚠️ rôle hypertrophié"
        print(f"{nom:25s} {w:7d} {pct_words:5.1f}% {r:10d} {unites_presentes:13d} {pct_unites:8.1f}%  {flag}")

    print(f"\n(moyenne de poids par personnage : {avg_pct:.1f}% du texte)")

    if unites_avec_tous:
        print(f"\nℹ️  {unites_avec_tous} unité(s) contiennent une réplique collective (« TOUS. ») "
              "non attribuée à un personnage précis — ignorée dans les comptages et la présence.")

    # matrice de présence, exportée en CSV à côté du fichier source
    import os
    all_chars = [p["nom"] for p in doc["personnages"]]
    out_csv = os.path.splitext(path)[0] + "_presence.csv"
    with open(out_csv, "w", encoding="utf-8") as f:
        f.write("Unite," + ",".join(all_chars) + "\n")
        for u in unites:
            row = [libelle_unite(u)] + ["X" if c in presence[u["id"]] else "" for c in all_chars]
            f.write(",".join(row) + "\n")
    print(f"\nMatrice de présence par unité exportée : {out_csv}")

    # -- agrégation par comédien (doublages) --
    if cast_path:
        with open(cast_path, encoding="utf-8") as f:
            cast_raw = json.load(f)
        char_to_actor = {}
        for actor, chars in cast_raw.items():
            for c in chars:
                char_to_actor[c] = actor

        actor_words = defaultdict(int)
        unmapped = []
        for nom, w, pct_words, r, unites_presentes, pct_unites in rows:
            actor = char_to_actor.get(nom)
            if actor is None:
                unmapped.append(nom)
                actor = f"[non mappé] {nom}"
            actor_words[actor] += w

        n_actors = len(cast_raw) or 1
        ideal_pct = 100 / n_actors

        print(f"\n=== RÉPARTITION PAR COMÉDIEN (cible d'équilibre : {ideal_pct:.1f}% chacun pour {n_actors} comédiens) ===\n")
        print(f"{'Comédien':25s} {'Mots':>7s} {'%':>6s} {'Écart vs cible':>15s}  Priorité de coupe")
        print("-" * 90)
        for actor, w in sorted(actor_words.items(), key=lambda x: -x[1]):
            pct = 100 * w / total_words
            ecart = pct - ideal_pct
            if pct > ideal_pct * 1.3:
                prio = "COUPER EN PRIORITÉ (ramener vers la cible)"
            elif pct < ideal_pct * 0.6:
                prio = "rôle creux — ne pas couper, envisager d'ajouter"
            else:
                prio = ""
            print(f"{actor:25s} {w:7d} {pct:5.1f}% {ecart:+14.1f}%  {prio}")

        if unmapped:
            print(f"\n⚠️  Personnages non mappés dans cast.json (ignorés dans le calcul par comédien) : {sorted(set(unmapped))}")

    # -- écart à la cible + unités candidates à une coupe large --
    if target:
        excess = total_words - target
        print(f"\n=== CIBLE DE LONGUEUR ===\n")
        if excess <= 0:
            print(f"Déjà sous la cible de {target} mots (actuellement {total_words} mots). Aucune coupe nécessaire.")
        else:
            print(f"Cible : {target} mots | Actuel : {total_words} mots | À couper : {excess} mots ({100*excess/total_words:.0f}%)")
            print(f"\nDoctrine : prioriser les coupes chez les comédiens/rôles au-dessus de la cible d'équilibre,")
            print(f"pas uniquement au poids brut de l'unité. Vérifier pour chaque unité candidate ci-dessous")
            print(f"si elle est structurellement sacrifiable :")
            print(f"  - une scène d'exposition qui semble creuse peut être indispensable à la mise en place")
            print(f"  - une scène hors-intrigue peut porter la farce/l'humour de la pièce")
            print(f"  -> signaler ces fonctions explicitement plutôt que de couper au seul critère du volume\n")
            print(f"{'Unité':30s} {'Mots':>7s} {'% du total':>11s}  Personnages présents")
            print("-" * 90)
            libelles = {u["id"]: libelle_unite(u) for u in unites}
            for uid, w in sorted(words_by_unite.items(), key=lambda x: -x[1])[:15]:
                pct = 100 * w / total_words
                chars_in = ", ".join(sorted(presence[uid]))
                print(f"{libelles[uid]:30s} {w:7d} {pct:10.1f}%  {chars_in}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    mode = sys.argv[1]
    path = sys.argv[2]
    if mode == "detect":
        cmd_detect(path)
    elif mode == "compute":
        cast_path = None
        target = None
        if "--cast" in sys.argv:
            cast_path = sys.argv[sys.argv.index("--cast") + 1]
        if "--target" in sys.argv:
            target = int(sys.argv[sys.argv.index("--target") + 1])
        cmd_compute(path, cast_path, target)
    else:
        print(__doc__)
