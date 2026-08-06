# Doctrine — équilibrage et coupes de pièces de théâtre

Contexte : troupe de 10 comédiens (5H/5F), spectacle de 1h30-2h. Critère prioritaire absolu : aucun comédien ne doit se retrouver avec un rôle disproportionné.

## Source : le `_REPET.json`, jamais le docx/pdf/txt brut

`outil_coupes` lit exclusivement `pieces/<Pièce>_REPET.json` (schéma
`repetition/2`, produit par `outil_edition`, étape 4 — voir
`../outil_edition/ARCHITECTURE.md` §5.7). Ce fichier porte déjà des
personnages canonisés (les variantes de graphie sont fusionnées à la source,
et signalées dans son champ `avertissements` si c'est le cas) et un texte
parlé déjà séparé des didascalies. Il n'y a donc plus d'ambiguïté de
classification à valider à la main avant de compter : si le docx/pdf de la
pièce a changé, régénérez le `_REPET.json` via `outil_edition` avant de
relancer une analyse — ne jamais couper sur un `_REPET.json` périmé.

Ne jamais estimer les poids de personnages "à la lecture" pour un texte de plus de quelques pages — toujours passer par `analyze.py`. La lecture reste appropriée pour le jugement dramaturgique (où couper, quelle scène est faible), pas pour le comptage.

### Étape 1 — Détection

```bash
python analyze.py detect pieces/<Pièce>_REPET.json
```

Produit : nombre d'unités jouables (scènes classiques ou unités séparées par `***` en texte contemporain), personnages avec répliques/mots déjà agrégés, et les avertissements remontés par `outil_edition` (graphies fusionnées, texte sans personnage annoncé, classement de titre incertain).

**Toujours vérifier avant de continuer :** les avertissements affichés — un classement de titre resté incertain côté `outil_edition` peut signifier qu'une scène entière s'est retrouvée fondue dans la mauvaise unité.

### Étape 2 — Calcul

```bash
python analyze.py compute pieces/<Pièce>_REPET.json [--cast cast.json] [--target 15000]
```

Produit : tableau mots/%/répliques/présence par unité jouable et par personnage, avec flags "rôle creux" (< 25% du poids moyen ET < 3% du total) / "rôle hypertrophié" (> 2.5x le poids moyen ET > 15% du total), et un CSV de matrice de présence unité × personnage.

**`--cast cast.json`** (distribution déjà connue, doublages inclus) :

```json
{ "Comédien A": \["ALCESTE"], "Comédien B": \["PHILINTE", "LE PRINCE"] }
```

Agrège par comédien (pas par personnage), compare à la cible réelle (100% / nb comédiens, ex. 10% pour 10). C'est ce tableau qui sert de référence pour les coupes une fois la distribution fixée.

**`--target <mots>`** : affiche l'écart à combler et classe les scènes par poids décroissant, pour repérer les candidates à une coupe large.

Toujours recalculer (étape 1 + 2) après chaque passe de coupe — ne jamais réutiliser un ancien comptage après modification du texte.

## Doctrine de coupe (distribution fixée)

Couper en priorité chez les rôles les plus au-dessus de la cible d'équilibre (\~10% pour 10 comédiens), pour les ramener progressivement vers cette cible. Les rôles déjà proches ou en dessous de la cible ne sont pas des candidats à la coupe.

**2-3 passes, pas un rabotage ligne à ligne répété à l'infini :**

1. Passe structurelle : scènes/sous-intrigues entières chez les rôles surchargés, viser \~70-80% du volume à couper dès cette passe
2. Passe d'ajustement fin : ligne à ligne pour la cible exacte
3. Passe de rééquilibrage si une passe précédente a trop vidé un rôle

**Avant de sacrifier une scène entière, vérifier sa fonction dramaturgique, pas seulement son poids en mots :**

* une scène d'exposition qui paraît "sans intérêt" peut être nécessaire à la mise en place
* une scène hors-intrigue peut porter la farce ou l'humour de la pièce

Toujours signaler explicitement la fonction identifiée (exposition / farce / intrigue) pour chaque scène proposée à la coupe large.

## Format de restitution des coupes

`.docx` à suivi de modifications Word (`<w:del>`), texte intégral conservé et visible en barré : on relit dans Word et on accepte/rejette chaque coupe. Rien n'est effacé.

`appliquer_coupes.py` produit ce fichier **à partir du `.docx` mis en forme d'origine** : il n'y insère que les marques de suppression, sans toucher à la police, aux tailles ni aux styles — le format est préservé par construction, pas reproduit à l'approximation. Les coupes sont décrites dans `sorties/coupes_<pièce>.json` — une liste de `{passe, debut, fin}` (couper de la 1ʳᵉ occurrence de `debut` jusqu'à la fin de `fin`) ou `{passe, texte}` (couper ce passage exact) :

    python appliquer_coupes.py <Pièce.docx> sorties/coupes_<pièce>.json --sortie <Pièce>_coupes.docx

Les ancres sont cherchées dans la concaténation des runs du document (paragraphes séparés par un saut de ligne). Une ancre introuvable ou ambiguë arrête le programme : une coupe mal ancrée doit se voir, pas se poser au hasard. Un nom de personnage dont toute la réplique est coupée est emporté avec elle.

Les coupes se mènent en **deux passes**, distinguées dans le `.docx` par leur couleur (deux auteurs de révision distincts, donc acceptables/rejetables séparément dans Word) :

* 🔴 **passe 1, rouge** — coupes structurelles (scènes/tirades entières chez les surchargés) ;
* 🔵 **passe 2, bleu** — rabotage fin pour atteindre la cible exacte.

Le registre lisible des coupes validées, scène par scène, vit dans `sorties/coupes_<pièce>.md` (avec la distribution `cast.json` et les matrices de présence). Ce dossier `sorties/` est un espace de travail par production, non versionné.

### Relecture croisée : fusionner coupes humaines et calculées

Quand un relecteur a déjà proposé ses coupes dans un `.docx` (suivi de modifications), `fusion_coupes.py` les superpose aux coupes calculées, en trois couleurs, sur le texte source — pour arbitrer d'un coup d'œil :

    python fusion_coupes.py <source.docx> <relecteur.docx> sorties/coupes_<pièce>.json --sortie <fusion.docx>

* les coupes du **relecteur → vert**, et **prioritaires** : un passage coupé par les deux lui revient ;
* mes coupes **passe 1 → rouge**, **passe 2 → bleu** — elles ne marquent donc que *mes ajouts*, ce que le relecteur n'avait pas coupé.

Le format d'origine est préservé (on part du `.docx` source). L'alignement des coupes du relecteur sur la source tolère ses propres retouches (insertions, corrections) : rapide par lignes, puis fin caractère par caractère sur les seules lignes qu'il a modifiées. On relit ensuite **le rouge et le bleu** dans Word — le vert est déjà la décision du relecteur.

C'est le moyen concret d'appliquer la règle « recalculer après chaque passe » à quatre mains : le relecteur voit ses coupes conservées et n'a plus qu'à trancher les propositions supplémentaires.



## Limites connues

* La présence par unité est déduite des seules répliques prononcées : un personnage présent mais silencieux sur toute une unité n'y apparaît pas. Hérité du `_REPET.json` lui-même, pas de `analyze.py`.
* Un classement de titre resté incertain côté `outil_edition` (règle 7 par défaut : « personnage ») peut faire apparaître dans le tableau une entrée qui n'est pas un vrai rôle (ex. un titre de pièce mal classé). Toujours croiser avec les avertissements de l'étape 1 avant de traiter une entrée marginale comme un personnage réel.
* La réplique collective (« TOUS. ») n'est comptée pour aucun personnage précis : elle est ignorée dans les poids et la présence, et seulement signalée en nombre d'unités concernées.

## Restitution

Tableau synthétique (personnage / mots / % / verdict), pas de longue prose. Citer les scènes précises (Acte/Sc.) où un personnage est absent sur une plage anormalement longue, en s'appuyant sur le CSV de présence.

