# Notes par pièce

Ce fichier recense les cas où une pièce a demandé une correction **manuelle**
du `REPET.json`, en plus (ou à la place) de ce que `docx_vers_repet.py` sait
produire automatiquement. Il existe pour une raison précise : ces corrections
vivent dans `pieces/*_REPET.json` (dossier partagé, à la racine du dépôt —
voir `pieces/LISEZ-MOI.md`), qui n'est **jamais versionné** (`.gitignore`) —
sans cette note, la prochaine régénération écraserait la correction sans que
personne ne s'en souvienne.

**Avant de relancer `docx_vers_repet.py` sur une pièce listée ici**, relisez sa
section : soit le docx a depuis été corrigé à la source (auquel cas la note
peut être retirée), soit la correction manuelle est encore à refaire.

---

## La mastication des morts (Patrick Kermann)

### Le problème

Cette pièce est structurée comme ~150 monologues, un par villageois mort,
chacun annoncé par un nom en gras — la convention `**NOM.**` attendue par le
pipeline. Mais la pièce s'ouvre et se referme sur **deux monologues-cadre**
(un prologue et un épilogue) qui ne sont précédés d'aucun nom dans le docx :

- le **prologue** commence par « A Landon, je suis descendu de la micheline
  rouge… » et se termine juste avant le premier vrai personnage
  (« Gilles Rimey ») ;
- l'**épilogue** commence par « Aux aguets du moindre son murmuré… » et clôt
  la pièce, juste après le dernier vrai personnage (« Alain Dupont »).

Sans nom annoncé, `docx_vers_edit.py` les avale par sa règle de continuation
de paragraphes :

- le prologue se retrouve **fusionné avec les épigraphes de tête d'ouvrage**
  (citations de Michael Ranft, Jean Genet, Heiner Müller, note de l'auteur sur
  les droits) sous un faux personnage « La mastication des morts » — le titre
  de la pièce lui-même, mal classé faute d'acte pour délimiter les liminaires ;
- l'épilogue se retrouve **fusionné avec la dernière réplique d'Alain
  Dupont**, gonflant sa réplique de 17 à 241 mots.

### La correction appliquée (manuelle, dans le REPET.json actuel)

- Les épigraphes + note de l'auteur (1199 caractères, avant « A Landon, je
  suis descendu ») sont déplacés en liminaire (`type: "note"`), pas perdus.
- Le prologue et l'épilogue sont attribués à un personnage **NARRATEUR**
  ajouté manuellement (2 répliques, 4794 mots).
- Le texte d'Alain Dupont est restauré à sa vraie longueur (17 mots).
- Un avertissement explicite est ajouté dans le JSON pour le signaler.

### La vraie correction, à faire dans le docx

La correction ci-dessus est **manuelle et fragile** : `docx_vers_repet.py` ne
la connaît pas et l'écrasera à la prochaine régénération. La correction
durable est d'ajouter, directement dans le docx, un paragraphe en gras
`NARRATEUR` (ou le nom que la troupe préfère) juste avant chacun des deux
monologues-cadre :

- avant « A Landon, je suis descendu de la micheline rouge… » ;
- avant « Aux aguets du moindre son murmuré… ».

Une fois ce nom ajouté à la source, `docx_vers_repet.py` reproduira le bon
résultat automatiquement, sans script de rattrapage — et cette section pourra
être retirée de ce fichier.

### Repère annexe

Un second en-tête en gras, `**1914-1918**`, introduit une liste collective de
noms des morts de la Première Guerre mondiale (pas un monologue individuel).
Il apparaît dans la distribution comme un personnage à part entière ; non
corrigé pour l'instant faute de certitude sur l'intention scénique (lecture
collective ? simple séparateur ?). À trancher avec la troupe si besoin.
