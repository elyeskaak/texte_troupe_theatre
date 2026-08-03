"""
Usage:
  python analyze.py detect <fichier.docx|.pdf|.txt>
      -> rapport de structure à valider AVANT tout calcul

  python analyze.py compute <fichier> [--aliases aliases.json] [--cast cast.json] [--target 15000]
      -> comptage mots/répliques par personnage + matrice de présence par scène
      aliases.json : {"ALC.": "ALCESTE", "Le Prince": "PRINCE"} pour fusionner les variantes
      cast.json    : {"Comédien A": ["ALCESTE"], "Comédien B": ["PHILINTE", "LE PRINCE"]}
                     agrège le calcul par comédien (doublages inclus) plutôt que par personnage
      --target N   : signale l'écart au nombre de mots cible et classe les scènes par poids
                     décroissant pour repérer les meilleures candidates à une coupe large
"""
import sys
import json
import re
from collections import defaultdict, OrderedDict
from parser import extract_blocks, normalize_name


def word_count(text):
    return len(re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9']+", text))


def cmd_detect(path):
    blocks = extract_blocks(path)
    acts = [b for b in blocks if b['kind'] == 'act']
    scenes = [b for b in blocks if b['kind'] == 'scene']
    speakers = [b for b in blocks if b['kind'] == 'speaker']
    stage_dirs = [b for b in blocks if b['kind'] == 'stage_direction']

    speaker_freq = defaultdict(int)
    for s in speakers:
        speaker_freq[s['speaker_name']] += 1

    scenes_with_chars = sum(1 for s in scenes if s['scene_chars'])

    print(f"=== RAPPORT DE STRUCTURE : {path} ===\n")
    print(f"Blocs total analysés : {len(blocks)}")
    print(f"Actes détectés       : {len(acts)}")
    print(f"Scènes détectées     : {len(scenes)}  (dont {scenes_with_chars} avec liste de personnages en tête -> format classique)")
    print(f"Répliques détectées  : {len(speakers)}")
    print(f"Didascalies détectées: {len(stage_dirs)}\n")

    print("--- Personnages détectés (nom brut -> nb répliques) — À VALIDER ---")
    print("(vérifier les doublons de nom : variantes/typos à fusionner via un fichier aliases.json)\n")
    for name, count in sorted(speaker_freq.items(), key=lambda x: -x[1]):
        print(f"  {name:30s} {count:4d} répliques")

    if len(scenes) == 0:
        print("\n⚠️  Aucune scène détectée : impossible de construire une matrice de présence fiable.")
        print("   Vérifiez que les en-têtes de scène suivent bien un format du type 'SCÈNE 3' ou 'Scène III'.")
    elif scenes_with_chars < len(scenes) / 2:
        print("\nℹ️  Format majoritairement MODERNE : la présence par scène sera déduite des répliques")
        print("   effectivement prononcées (+ didascalies d'entrée/sortie si détectées), pas d'une liste en tête de scène.")
        print("   Fiabilité inférieure au format classique — à vérifier manuellement sur les scènes signalées comme limites.")
    else:
        print("\nℹ️  Format majoritairement CLASSIQUE : présence par scène basée sur les listes en tête de scène.")

    # lignes de dialogue qui ressemblent à des didascalies non détectées (contrôle qualité)
    suspicious = [b for b in blocks if b['kind'] == 'dialogue' and len(b['text'].split()) <= 6
                  and re.search(r'\b(entre|sort|sortent|entrent)\b', b['text'], re.IGNORECASE)]
    if suspicious:
        print(f"\n⚠️  {len(suspicious)} ligne(s) courte(s) mentionnant entrée/sortie mais classées comme dialogue —"
              f" à vérifier (peuvent être des didascalies mal détectées) :")
        for b in suspicious[:15]:
            print(f"    - {b['text'][:70]}")


def cmd_compute(path, aliases_path=None, cast_path=None, target=None):
    blocks = extract_blocks(path)
    aliases = {}
    if aliases_path:
        with open(aliases_path, encoding='utf-8') as f:
            raw = json.load(f)
        aliases = {normalize_name(k): normalize_name(v) for k, v in raw.items()}

    def canon(name):
        return aliases.get(name, name)

    # -- découpage en scènes --
    scene_key = None
    scene_order = []
    scene_declared_chars = {}
    current_speaker = None
    words_by_char = defaultdict(int)
    replicas_by_char = defaultdict(int)
    words_by_scene = defaultdict(int)
    presence = defaultdict(set)  # scene_key -> set(char)
    act_num = "?"

    for b in blocks:
        if b['kind'] == 'act':
            m = re.search(r'(ACTE|Acte)\s+([IVXLCDM]+|\d+)', b['text'])
            act_num = m.group(2) if m else act_num
            current_speaker = None
        elif b['kind'] == 'scene':
            m = re.search(r'(SC[ÈE]NE|Sc[èe]ne)\s+([IVXLCDM]+|\d+)', b['text'])
            scnum = m.group(2) if m else str(len(scene_order) + 1)
            scene_key = f"Acte {act_num} - Sc.{scnum}"
            scene_order.append(scene_key)
            if b['scene_chars']:
                scene_declared_chars[scene_key] = [canon(c) for c in b['scene_chars']]
                for c in scene_declared_chars[scene_key]:
                    presence[scene_key].add(c)
            current_speaker = None
        elif b['kind'] == 'speaker':
            current_speaker = canon(b['speaker_name'])
            replicas_by_char[current_speaker] += 1
            if scene_key:
                presence[scene_key].add(current_speaker)
        elif b['kind'] == 'dialogue':
            if current_speaker:
                wc = word_count(b['text'])
                words_by_char[current_speaker] += wc
                if scene_key:
                    words_by_scene[scene_key] += wc

    all_chars = sorted(set(list(words_by_char.keys()) + list(replicas_by_char.keys())))
    total_words = sum(words_by_char.values()) or 1
    total_scenes = len(scene_order) or 1

    print(f"=== ANALYSE : {path} ===\n")
    print(f"{len(all_chars)} personnages | {total_scenes} scènes | {total_words} mots de dialogue comptés\n")
    print(f"{'Personnage':25s} {'Mots':>7s} {'%':>6s} {'Répliques':>10s} {'Scènes prés.':>13s} {'% scènes':>9s}  Flag")
    print("-" * 90)

    rows = []
    for c in all_chars:
        w = words_by_char[c]
        r = replicas_by_char[c]
        pct_words = 100 * w / total_words
        scenes_present = sum(1 for sk in scene_order if c in presence[sk])
        pct_scenes = 100 * scenes_present / total_scenes
        rows.append((c, w, pct_words, r, scenes_present, pct_scenes))

    avg_pct = sum(row[2] for row in rows) / len(rows) if rows else 0

    for c, w, pct_words, r, scenes_present, pct_scenes in sorted(rows, key=lambda x: -x[1]):
        flag = ""
        if pct_words < avg_pct * 0.25 and pct_words < 3:
            flag = "⚠️ rôle creux"
        elif pct_words > avg_pct * 2.5 and pct_words > 15:
            flag = "⚠️ rôle hypertrophié"
        print(f"{c:25s} {w:7d} {pct_words:5.1f}% {r:10d} {scenes_present:13d} {pct_scenes:8.1f}%  {flag}")

    print(f"\n(moyenne de poids par personnage : {avg_pct:.1f}% du texte)")

    # matrice de présence, exportée en CSV à côté du fichier source
    import os
    out_csv = os.path.splitext(path)[0] + "_presence.csv"
    with open(out_csv, 'w', encoding='utf-8') as f:
        f.write("Scene," + ",".join(all_chars) + "\n")
        for sk in scene_order:
            row = [sk] + ["X" if c in presence[sk] else "" for c in all_chars]
            f.write(",".join(row) + "\n")
    print(f"\nMatrice de présence par scène exportée : {out_csv}")

    # -- agrégation par comédien (doublages) --
    if cast_path:
        with open(cast_path, encoding='utf-8') as f:
            cast_raw = json.load(f)
        char_to_actor = {}
        for actor, chars in cast_raw.items():
            for c in chars:
                char_to_actor[canon(normalize_name(c))] = actor

        actor_words = defaultdict(int)
        actor_replicas = defaultdict(int)
        unmapped = []
        for c, w, pct_words, r, scenes_present, pct_scenes in rows:
            actor = char_to_actor.get(c)
            if actor is None:
                unmapped.append(c)
                actor = f"[non mappé] {c}"
            actor_words[actor] += w
            actor_replicas[actor] += r

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

    # -- écart à la cible + scènes candidates à une coupe large --
    if target:
        excess = total_words - target
        print(f"\n=== CIBLE DE LONGUEUR ===\n")
        if excess <= 0:
            print(f"Déjà sous la cible de {target} mots (actuellement {total_words} mots). Aucune coupe nécessaire.")
        else:
            print(f"Cible : {target} mots | Actuel : {total_words} mots | À couper : {excess} mots ({100*excess/total_words:.0f}%)")
            print(f"\nDoctrine : prioriser les coupes chez les comédiens/rôles au-dessus de la cible d'équilibre,")
            print(f"pas uniquement au poids brut de la scène. Vérifier pour chaque scène candidate ci-dessous")
            print(f"si elle est structurellement sacrifiable :")
            print(f"  - une scène d'exposition qui semble creuse peut être indispensable à la mise en place")
            print(f"  - une scène hors-intrigue peut porter la farce/l'humour de la pièce")
            print(f"  -> signaler ces fonctions explicitement plutôt que de couper au seul critère du volume\n")
            print(f"{'Scène':20s} {'Mots':>7s} {'% du total':>11s}  Personnages présents")
            print("-" * 90)
            for sk, w in sorted(words_by_scene.items(), key=lambda x: -x[1])[:15]:
                pct = 100 * w / total_words
                chars_in = ", ".join(sorted(presence[sk]))
                print(f"{sk:20s} {w:7d} {pct:10.1f}%  {chars_in}")


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    mode = sys.argv[1]
    path = sys.argv[2]
    if mode == 'detect':
        cmd_detect(path)
    elif mode == 'compute':
        aliases_path = None
        cast_path = None
        target = None
        if '--aliases' in sys.argv:
            aliases_path = sys.argv[sys.argv.index('--aliases') + 1]
        if '--cast' in sys.argv:
            cast_path = sys.argv[sys.argv.index('--cast') + 1]
        if '--target' in sys.argv:
            target = int(sys.argv[sys.argv.index('--target') + 1])
        cmd_compute(path, aliases_path, cast_path, target)
    else:
        print(__doc__)
