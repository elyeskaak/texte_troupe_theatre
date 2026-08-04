# ARCHITECTURE — outil de lecture interactive projetée

> **Statut : validé le 2026-08-03.** Les deux décisions structurantes (§2) et
> les quatre décisions secondaires (§13) ont toutes été tranchées par
> l'utilisateur. L'implémentation peut commencer à l'étape 2 du
> [plan de livraison](#14-plan-de-livraison).

Ce document répond au prompt `prompt-outil-lecture-projetee.md`, en le révisant
sur son point le plus structurant : le format d'entrée.

---

## Table des matières

1. [Objectif et principes directeurs](#1-objectif-et-principes-directeurs)
2. [Révision du prompt initial](#2-révision-du-prompt-initial)
3. [Vue d'ensemble](#3-vue-densemble)
4. [Arborescence](#4-arborescence)
5. [Le modèle en mémoire](#5-le-modèle-en-mémoire)
6. [Attribution des personnages aux slots (remplace `#CAST`)](#6-attribution-des-personnages-aux-slots-remplace-cast)
7. [La fenêtre de contrôle et sa synchronisation](#7-la-fenêtre-de-contrôle-et-sa-synchronisation)
8. [Rendu projeté](#8-rendu-projeté)
9. [Navigation](#9-navigation)
10. [Persistance](#10-persistance)
11. [Gestion des erreurs](#11-gestion-des-erreurs)
12. [Configuration](#12-configuration)
13. [Décisions validées](#13-décisions-validées)
14. [Plan de livraison](#14-plan-de-livraison)

---

## 1. Objectif et principes directeurs

Lire une pièce à plusieurs voix, en direct, projetée au vidéoprojecteur. Chaque
lecteur reconnaît ses répliques par une couleur et une étiquette de slot
(H1-H5, F1-F5), qu'il joue un ou plusieurs personnages.

Trois principes, hérités de `outil_repetition` et assumés ici aussi :

- **P1 — Le texte de l'auteur n'est jamais modifié.** L'outil lit le
  `REPET.json`, n'y écrit rien. L'attribution des personnages aux slots et les
  prénoms des lecteurs vivent dans des clés `localStorage` séparées.
- **P2 — Aucune erreur silencieuse.** Un fichier non conforme est refusé avant
  tout affichage, avec un message nommant le champ fautif. Une popup bloquée
  se signale, ne reste pas un bouton inerte.
- **P3 — Zéro installation.** Un seul fichier HTML, ouvrable par double-clic,
  sans serveur ni build. C'est la contrainte qui gouverne §2 et §4.

## 2. Révision du prompt initial

Deux décisions ont été prises en échangeant avec l'utilisateur avant ce
document, parce qu'elles changent toute la suite :

### 2.1 Format d'entrée : `REPET.json`, pas un `.txt` `#CAST`/`#SCENE`

Le prompt décrivait un format `.txt` autonome (`#CAST:`, `#SCENE:`,
`PERSONNAGE: texte`, `[didascalie]`) avec un parseur strict ligne à ligne. En
vérifiant l'existant, ce format ne correspond **ni** au `REPET.json` que
produit déjà `outil_edition` pour chaque pièce éditée (consommé par
`outil_repetition`), **ni** à l'`EDIT.txt` intermédiaire du pipeline (qui
utilise `**PERSONNAGE.**` / `*didascalie*`). L'écrire tel quel aurait obligé à
ressaisir à la main chaque pièce déjà éditée.

**Décision : l'outil de lecture consomme le `REPET.json`** (schéma
`repetition/1`, voir `outil_edition/theatre_editor/repet_export.py` et
`outil_repetition/js/schema.js`), exactement la même donnée que l'outil de
répétition. Conséquence directe : **tout le bloc « parsing strict du `.txt` »
du prompt disparaît**. Ce qu'il reste à faire à la place :

- valider le JSON importé (schéma, champs requis) — même esprit que
  `schema.js`, réécrit ici en une fonction autonome (§11), pour ne dépendre
  d'aucun fichier de `outil_repetition/js/` (voir §4, raison d'isolement) ;
  aucune écriture n'aura jamais lieu dans `outil_repetition/`, dont
  `index.html`, `js/app.js` et `js/rendu.js` sont en cours de modification par
  ailleurs — l'outil de lecture n'y touche jamais, y compris en lecture à
  l'exécution (aucun `<script src="../outil_repetition/...">`) ;
- remplacer le bloc `#CAST` par un écran d'attribution personnage → slot,
  construit à partir du champ `personnages` déjà présent dans le JSON (§6) ;
  plus besoin de détecter les personnages en scannant du texte : ils sont déjà
  dénombrés par `repet_export.py`.

Ce que le prompt demandait **au-delà** du strict texte parlé est conservé et
même simplifié par ce choix : les didascalies (`type: "didascalie"` et
`type: "lieu"`) et les répliques en vers (`vers: true`, retours à la ligne
signifiants) sont déjà distingués dans le JSON, sans qu'il faille les
redétecter par une heuristique sur des crochets.

Un point que le prompt n'anticipait pas et que le JSON introduit : certaines
répliques portent des **didascalies internes** (`didascalies_internes`, un jeu
de scène au milieu d'une phrase — *« Je t'attendais, elle se lève, depuis une
heure »*). Le rendu projeté doit les insérer au bon endroit dans la réplique,
en style distinct (§8.3) ; c'est un peu plus de travail que le prompt initial,
mais nécessaire pour ne pas faire disparaître silencieusement un jeu de scène
écrit par l'auteur (P1).

### 2.2 Un seul fichier HTML, sans découpage en modules

`outil_repetition` découpe sa logique en douze fichiers pour la rendre
testable par `node --test` (voir son `ARCHITECTURE.md` §3.2) — mais il est
servi en HTTPS et n'a pas besoin d'ouverture par double-clic. L'outil de
lecture, lui, doit s'ouvrir depuis un poste nomade branché à un
vidéoprojecteur, potentiellement sans réseau : les modules ES ne se chargent
pas depuis `file://`.

**Décision confirmée avec l'utilisateur : un seul fichier `index.html`**,
scripts classiques (pas de `type="module"`), CSS inclus. Le prix assumé : pas
de `node --test` sur cette logique-là (contrairement à `outil_repetition`).
Le fichier reste organisé en sections `// ====…` nettement séparées à
l'intérieur, pour rester lisible malgré l'absence de découpage physique
(§4.2).

---

## 3. Vue d'ensemble

```
        écran de préparation (fenêtre principale, avant lecture)
        ┌───────────────────────────────────────────────────┐
        │ import REPET.json → validerRepet()                │
        │ écran d'attribution personnage → slot (§6)         │
        │ bouton « ouvrir la fenêtre de contrôle »           │
        └───────────────────────────────────────────────────┘
                              │ clic « démarrer la lecture »
                              ▼
   ┌─────────────────────────────┐   BroadcastChannel   ┌──────────────────────────┐
   │ fenêtre de PROJECTION       │◀────────────────────▶│ fenêtre de CONTRÔLE       │
   │ index.html (défaut)         │  'lecture:v1'         │ index.html?fenetre=controle│
   │ plein écran, clavier only   │                       │ 10 champs prénom, souris  │
   │ aucune UI de contrôle       │                       │ rappel scène/slot en cours│
   └─────────────────────────────┘                       └──────────────────────────┘
```

Les deux fenêtres sont **la même page** : `index.html?fenetre=controle` bascule
sur le rendu de contrôle au chargement (§7.1). Ceci tient la promesse « un seul
fichier » sans dupliquer le HTML.

---

## 4. Arborescence

```
outil_lecture/
├── index.html      coque + CSS + tout le JS, sections séparées (§2.2, §4.2)
├── README.md        usage, limites (écrit en dernier, §14 étape 6)
└── pieces/          JAMAIS versionné (.gitignore) — REPET.json chargés localement
```

### 4.1 Pourquoi pas de fichier séparé pour la validation du JSON

`outil_repetition/js/schema.js` fait déjà ce travail. Il n'est **pas importé**
ici : un `<script src="../outil_repetition/js/schema.js">` créerait une
dépendance entre deux sous-projets censés être indépendants (le README du
dépôt les présente comme tels), et surtout **un couplage avec un fichier
actuellement modifié par un autre processus** — un mauvais moment pour y
accrocher un import. La fonction de validation est donc réécrite, à l'identique
dans son esprit (refuser tôt, nommer le champ fautif), dans `index.html`.
C'est une duplication assumée, pas un oubli.

### 4.2 Sections internes du fichier unique

Pour garder la lisibilité sans modules, `index.html` est organisé en sections
commentées, dans cet ordre de dépendance (chacune ne lit que les précédentes) :

```js
// ============================================================
// 1. CONFIG        — constantes, aucune logique
// 2. VALIDATION     — validerRepet(json)
// 3. MODELE         — aplatirEnElements(piece), calculerSommaire(piece)
// 4. ETAT           — position courante, mode fenêtre, transitions
// 5. STOCKAGE       — localStorage, clés lecture:v1:*
// 6. SYNCHRO        — BroadcastChannel, protocole de messages
// 7. RENDU PROJECTION
// 8. RENDU CONTROLE
// 9. RENDU PREPARATION
// 10. CABLAGE        — écouteurs clavier/souris, point d'entrée
// ============================================================
```

Les sections 2 à 4 n'accèdent ni au DOM ni à `window` : elles ne sont pas
extraites en fichiers séparés (§2.2), mais restent des fonctions pures
appelables isolément — un futur passage à `node --test` (si le besoin s'en
fait sentir) n'exigerait qu'un copier-coller, pas une réécriture.

---

## 5. Le modèle en mémoire

`aplatirEnElements(piece)` parcourt `piece.unites[].elements[]` une fois et
produit une liste plate, unité de navigation et de rendu :

```js
[
  { kind: 'scene', uniteId, acte, scene, implicite },   // un par unité, sauf implicite
  { kind: 'lieu', texte },
  { kind: 'didascalie', texte },
  { kind: 'texte_sans_personnage', texte },              // §11, style distinct + avertissement
  { kind: 'replique', id, personnages, texte, vers, didascaliesInternes },
  …
]
```

C'est cette liste, pas `piece.unites` directement, que la navigation clavier
parcourt par index : un `kind: 'scene'` en tête de chaque unité non implicite
donne gratuitement la marque de transition de scène demandée par le prompt
(§8 du prompt initial), sans logique de détection séparée.

**Révision à l'usage — deux schémas, une seule forme interne :** le
`REPET.json` a changé de schéma en cours de route (`repetition/1` →
`repetition/2`) pour distinguer une réplique dite par un seul personnage
d'une réplique dite par plusieurs à la fois (une exclamation collective,
par exemple) : `personnage: string` devient `personnages: string[]`.
`_elementAplati` absorbe cette différence à la source — `personnages:
Array.isArray(el.personnages) ? el.personnages : [el.personnage]` — pour
que **tout le reste du code** (pagination, rendu, cast, contrôle) ne
connaisse plus qu'un tableau, jamais les deux formes d'origine. `validerRepet`
accepte les deux schémas (`CONFIG.SCHEMAS_ACCEPTES`) et, au niveau de chaque
réplique, l'un ou l'autre champ — jamais aucun des deux, jamais un tableau
vide.

`calculerSommaire(piece)` — `[{ uniteId, acte, scene, position }]` — sert à la
barre de progression (§8.4) : « scène 2 / 5 » se lit par recherche de la
dernière entrée dont `position <= positionCourante`.

---

## 6. Attribution des personnages aux slots (remplace `#CAST`)

Le `REPET.json` fournit déjà `piece.personnages` (`{ nom, repliques, mots }`,
triés par volume). L'écran de préparation en fait une liste de menus
déroulants, un par personnage, valeurs `— choisir —, H1..H5, F1..F5` :

- plusieurs personnages peuvent pointer vers le même slot (un lecteur joue
  plusieurs rôles) — aucune contrainte d'unicité ;
- **aucune valeur par défaut devinée** : un slot non choisi bloque le bouton
  « démarrer la lecture », avec la liste des personnages non assignés — dans
  l'esprit strict du prompt (« pas de détection heuristique »), transposé ici
  à l'attribution plutôt qu'au parsing ;
- si la pièce a déjà été lue (même `piece`, voir §10.1 pour l'identifiant),
  l'attribution précédente est proposée pré-remplie et reste modifiable.

C'est un renommage fonctionnel du bloc `#CAST` du prompt, pas un
appauvrissement : la seule chose qui change est que l'utilisateur clique un
menu déroulant au lieu d'écrire `PERSO = H1` dans un fichier texte — exactement
le repli que le prompt prévoyait déjà pour un `#CAST` absent ou incomplet
(§ « Format d'entrée » du prompt), généralisé ici au cas normal.

**Révision à l'usage :** l'écran de préparation restait sur le thème clair
par défaut du navigateur (fond blanc, texte noir), en rupture avec le fond
sombre de la projection et de la fenêtre de contrôle. Les trois écrans
partagent désormais la même charte — fond `--fond-projection`, texte
`--texte-clair`, accents `--attenue` — déclarée une seule fois en `:root`
et reprise par les boutons, champs et menus déroulants (règle générique sur
`button, select, input`), pas seulement par la projection.

**Deuxième passe, esthétique :** chaque section (import, attribution,
fenêtre de contrôle) devient une carte distincte (`--fond-releve`, bordure,
coins arrondis) plutôt qu'un simple empilement de titres et de champs sur
le fond de page. Une couleur d'accent (`--accent`, un bleu neutre, choisi
en dehors de la palette des dix slots pour ne pas laisser croire à un onzième
slot) marque les titres de section et le bouton principal. États `:hover` /
`:focus` sur les boutons, champs et menus déroulants, pour que l'écran
réagisse visuellement à l'interaction — aucun de ces détails n'est
fonctionnel, ils ne font que rendre l'écran moins austère.

**Ajout à l'usage :** les options du menu déroulant n'affichaient que le
code de slot (« H1 »), alors que la fenêtre de contrôle (§7.3) connaît
peut-être déjà un prénom pour ce slot — d'une session précédente, puisque
`lecture:v1:prenoms` est global et non lié à une pièce (§13, point 4).
`etiquetteSlot(slot, prenoms)` (déjà écrite, mais devenue orpheline après
la fusion de l'en-tête projeté en §8.2) reprend du service ici : chaque
option affiche « H1 (Émile) » si ce prénom est connu, pour reconnaître le
bon slot par un prénom plutôt que par un code abstrait. Changé au passage
de format (« H1 — Émile » → « H1 (Émile) ») pour rester cohérent avec le
reste de l'outil, qui utilise désormais les parenthèses partout ailleurs.

---

## 7. La fenêtre de contrôle et sa synchronisation

### 7.1 Une seule page, deux rendus

`index.html` lit `new URLSearchParams(location.search).get('fenetre')` au
chargement :

- absent → **rendu projection** (défaut, celui qu'on double-clique) ;
- `'controle'` → **rendu contrôle**.

Le bouton « ouvrir la fenêtre de contrôle » appelle
`window.open(location.pathname + '?fenetre=controle', 'lecture-controle', …)`.
Popup bloquée → message inline + bouton « réessayer », qui reste affiché tant
que la fenêtre n'a pas confirmé sa présence (`postMessage` ou l'ouverture
elle-même selon ce que retourne `window.open`) — jamais un bouton qui a l'air
d'avoir marché.

### 7.2 Protocole `BroadcastChannel('lecture:v1')`

Deux messages suffisent, dans les deux sens :

```js
// projection → contrôle, à chaque navigation
{ type: 'position', uniteId, scene, acte, slotQuiParle }

// contrôle → projection, à chaque frappe dans un champ prénom
{ type: 'prenoms', H1: 'Émile', H2: '', … }
```

La fenêtre de contrôle envoie aussi son état complet à l'ouverture
(`{ type: 'bonjour' }`), pour que la projection lui renvoie sa position
courante sans attendre la prochaine navigation — sinon le rappel de scène
resterait vide jusqu'à la flèche suivante.

### 7.3 Ce que la fenêtre de contrôle affiche

Dix champs texte (toujours visibles, jamais de repli/dépli), plus une ligne
discrète : *« Scène 2 — SIR ROWLAND (H1) »*. Toute frappe est diffusée
immédiatement (pas de bouton « valider ») ; côté projection, un champ vide
retombe sur le nom brut du slot — jamais une chaîne vide affichée à la place
d'un nom.

**Ajout à l'usage :** chaque champ affiche aussi, entre parenthèses, les
personnages que ce slot joue dans la pièce chargée — *« H1 (Hugo) »* —
pour qu'un lecteur découvrant son slot sache qui il va jouer avant même de
saisir son prénom. `chargerRolesParSlot()` lit `lecture:v1:session` (le
`pieceSlug` actif) puis `lecture:v1:cast:<pieceSlug>`, et regroupe par slot
(`rolesParSlot`, fonction pure). Si le contrôle s'ouvre avant qu'une lecture
démarre, ce champ reste vide au chargement, puis se complète tout seul :
`diffuserPosition()` (§7.2) inclut désormais `roles` dans chaque message
`position` — pas seulement en réponse à `bonjour` —, donc un contrôle déjà
ouvert avant le démarrage se met à jour au premier changement de position.
Coût négligeable : `rolesParSlot` ne parcourt qu'une quinzaine de
personnages tout au plus.

**Fermeture sur iPhone :** la fenêtre de contrôle n'est, sur iPhone, qu'un
onglet Safari ordinaire — pas de fenêtre séparée à faire glisser sur un
second écran, ni de bouton natif évident pour la refermer une fois la
lecture terminée. Un bouton « Fermer cette fenêtre » appelle
`window.close()`, qui fonctionne ici précisément parce que cet onglet a été
ouvert par un script (`window.open`, §7.1) — c'est la condition que les
navigateurs exigent pour l'autoriser à se refermer lui-même. Si l'onglet a
été ouvert autrement (URL tapée à la main, marque-page), l'appel ne fait
rien silencieusement, sans erreur détectable côté script ; un texte d'aide
sous le bouton couvre ce cas (« fermez depuis le sélecteur d'onglets »),
plutôt que de laisser un bouton qui a l'air d'avoir marché sans l'avoir dit
(P3).

---

## 8. Rendu projeté

### 8.1 Montage

La liste plate (§5) est longue mais une pièce de théâtre reste de l'ordre de
quelques centaines à quelques milliers d'éléments, pas des dizaines de
milliers de répliques individuelles comme dans `outil_repetition` (qui gère
aussi les mots à trous, mot par mot). **Pas de montage paresseux ici** : le
DOM entier est monté une fois à l'import, cohérent avec P3 (zéro complexité
qui n'est pas déjà exigée par l'usage réel).

**Révision à l'usage (première pièce réelle projetée) :** la version initiale
n'affichait qu'une diapo à la fois (`display: none` sauf `.actif`, positionnée
en plein écran). À l'essai, ça isole trop la réplique courante : le lecteur
suivant ne voit pas venir son tour, et le fil de la scène disparaît entre deux
répliques. Toutes les diapos restent donc **montées dans le flux normal**
(`#contenu-projection` défile, `overflow-y: auto`), en permanence visibles.

**Deuxième révision à l'usage :** un premier essai distinguait trois paliers
fixes par classe — `.actif` (pleine taille), `.suivant` (taille
intermédiaire), le reste (réduit) — mais ça donnait l'impression que deux
répliques se disputaient l'attention, plutôt qu'une seule mise en avant
nette. Remplacé par `appliquerGradient(diapos, position)` : un **dégradé
continu**, calculé en JS et posé en variables CSS (`--opacite`, `--echelle`)
sur chaque diapo, qui décroît progressivement avec la distance à la position
courante jusqu'à un plancher au-delà de `CONFIG.PORTEE_GRADIENT` diapos (6 par
défaut). Le CSS ne fait que lire ces variables, avec un repli (`opacity: var(
--opacite, 0.25)`) pour les diapos jamais touchées.

Pour rester bon marché même sur une pièce de plusieurs milliers d'éléments,
`appliquerGradient` n'écrit **que sur une fenêtre bornée** autour de la
position (2 × portée + 1 indices), jamais sur la liste entière : la fenêtre
du tour précédent est effacée (`style.removeProperty`) avant d'appliquer la
nouvelle, pour qu'un grand saut (clic sur une diapo lointaine, sommaire §8.6)
ne laisse jamais une diapo agrandie par erreur loin de la position réelle.

Depuis la fusion des pages d'une réplique en un seul bloc (§8.5), plusieurs
index consécutifs peuvent partager le même élément DOM. `appliquerGradient`
parcourt donc la fenêtre **du plus éloigné vers le plus proche** de la
position : pour un élément partagé, la dernière écriture — celle qui compte
— vient ainsi toujours de son sous-index le plus proche, jamais d'un plus
lointain qui sous-évaluerait sa mise en avant.

Changer de réplique reste borné et cohérent avec le principe de §6 de
`outil_repetition/ARCHITECTURE.md` : jamais de reconstruction du DOM, une
écriture de classe (`.actif`, ancre du défilement et sélecteur de taille de
police, §8.2) plus un nombre constant d'écritures de style. Un défilement
doux (`scrollIntoView`) recentre la diapo courante à chaque navigation.

### 8.2 Couleur et étiquette

Palette fixe de 10 couleurs (§12), indexée par slot, jamais par prénom : une
règle CSS `[data-slot="H1"] { --couleur: … }` habille la réplique. L'étiquette
est injectée dans un `<span class="qui">`, mis à jour par la synchro de
contrôle (§7.2) sans toucher au reste du DOM.

**Révision à l'usage :** l'étiquette affichait le prénom *à la place* du
slot une fois saisi (« Émile » seul). Un lecteur qui ne joue le rôle actif
qu'occasionnellement perdait alors le repère fixe (couleur + H1-H5/F1-F5)
qui lui permet de reconnaître ses répliques d'un coup d'œil. Corrigé une
première fois pour toujours afficher les deux (« H1 » sans prénom, « H1 —
Émile » avec, `etiquetteSlot`).

**Deuxième révision, sur l'ordre cette fois :** l'en-tête montrait le slot
en avant (pastille) et le personnage en petit sous-titre dessous. Retour
d'usage : ce qu'on lit en premier devrait être *qui parle dans la pièce*,
le lecteur qui prête sa voix n'étant qu'un détail entre parenthèses.
`etiquetteReplique(personnage, slot, prenoms)` remplace `etiquetteSlot`
pour cet usage. Le sous-titre `.personnage` séparé disparaît, fusionné dans
la même pastille — un seul élément, plus de doublon visuel.
`formaterPersonnage` convertit au passage la casse d'imprimerie du
`REPET.json` (« CLARISSA ») en casse de lecture (« Clarissa »).

**Troisième révision, sur le contenu de la parenthèse :** *« Clarissa
(Caroline — H1) »* devient *« Clarissa (Caroline) »* — le code de slot
retiré de l'affichage projeté, sur demande directe. Il ne sert plus
qu'en interne (couleur, `data-slot`, et la fenêtre de contrôle, §7.3, où
il reste nécessaire pour savoir quel champ correspond à quel lecteur).
Sans prénom saisi, l'en-tête retombe sur le seul nom du personnage, sans
parenthèses vides : *« Clarissa »* — l'état normal avant que quiconque
n'ait rempli la fenêtre de contrôle, pas un cas d'erreur à signaler.

Conséquence sur la mise à jour en direct (§7.2) : `mettreAJourPrenoms` ne
peut plus se contenter de relire le slot, il lui faut aussi le personnage
pour recalculer l'étiquette entière. `data-personnage`, posé sur la diapo
au montage aux côtés de `data-slot`, le lui fournit sans avoir à
retransmettre le `cast` complet à chaque frappe.

### 8.3 Didascalies internes

`inserer(texte, didascaliesInternes)` découpe `texte` sur les espaces,
insère chaque didascalie au mot d'index `avant_mot`, dans un
`<span class="didascalie-interne">`. Fonction pure, testable isolément malgré
l'absence de suite de tests formelle (§2.2).

### 8.4 Barre de progression

`position courante / longueur de la liste plate`, et le libellé de scène tiré
de `calculerSommaire` (§5). Discrète, en pied de fenêtre, jamais superposée au
texte en cours.

### 8.5 Pagination des longues tirades

**Révision à l'usage :** une tirade longue, même réduite en taille (§8.1),
pouvait encore déborder du bas de l'écran, et la seule parade (`scrollIntoView`
aligné en haut) laissait le lecteur devoir faire défiler manuellement — la
pire des solutions pour un outil pensé « aucune souris nécessaire ».

`paginerElements(elements, motsParPageParReplique)` s'insère entre
l'aplatissement (§5) et le calcul du sommaire : toute réplique dont le quota
de mots par page (déterminé réplique par réplique, voir plus bas) est dépassé
est coupée en plusieurs éléments `kind: 'replique'` logiques, un par page. La
coupe préfère un saut de ligne (un vers) une fois 60 % du quota atteint —
pour ne jamais trancher un vers en deux — et se force à 140 % du quota
sinon, pour qu'une tirade en prose sans retour à la ligne ne parte pas en
une seule page démesurée (`paginerSegments`, fonction pure, testée).

**Deux révisions à l'usage sur la façon de montrer ces pages,** l'une après
l'autre, capture à l'appui :

1. La première version montait chaque page dans sa **propre diapo**, avec
   son propre en-tête (pastille de slot + personnage). Résultat : deux pages
   de la même réplique se lisaient comme deux répliques distinctes du même
   personnage — le même défaut que celui déjà corrigé pour le dégradé (§8.1),
   mais pour une autre cause.
2. Seule la première page a alors gardé l'en-tête complet, les suivantes un
   indicateur discret sans pastille dupliquée. **Insuffisant** : même sans
   doublon d'en-tête, deux pages restaient deux blocs DOM séparés — bordure,
   espacement — donc une vraie coupure visuelle subsistait entre elles.

**Solution retenue : fusionner toutes les pages d'une réplique en un seul
bloc DOM continu.** `grouperPagesReplique(elements)` regroupe les indices
consécutifs d'une même réplique paginée ; `construireDiapoRepliqueFusionnee`
construit **un seul** conteneur — un en-tête unique, un seul `<div
class="texte">` qui concatène les segments de toutes les pages, sans aucune
coupure visuelle. Une ancre invisible (`<span class="ancre-page">`) est
insérée à chaque frontière de page : c'est elle, et non le conteneur entier,
que la navigation cible pour la page 2 et les suivantes. Avancer dans une
longue tirade fait ainsi défiler *à l'intérieur* du même bloc continu — un
vrai défilement, comme demandé, sans jamais montrer de coupure.

Conséquence sur le modèle de navigation (§8) : `diapos[i]` n'est plus un
nœud DOM mais `{ element, ancre }` — plusieurs index consécutifs peuvent
partager le même `element` (les pages d'une réplique fusionnée), chacun avec
sa propre `ancre` à faire défiler. `.actif` se pose sur `element` (reste
donc actif tout le temps qu'on avance dans les pages d'une même réplique) ;
`afficherPosition` fait défiler vers `ancre`, pas vers `element`. Le clic
sur une réplique fusionnée (§8.6) saute toujours à sa première page — cliquer
n'importe où dans le bloc revient à en cibler le début, cohérent avec le
fait que ce soit maintenant visuellement une seule entité.

**Point d'ordre critique :** la pagination doit s'exécuter *avant*
`calculerSommaire` et le montage, jamais après — sans quoi les positions du
sommaire (§8.6) et les indices `data-index` des diapos ne correspondraient
plus à la même liste, et cliquer une scène sauterait au mauvais endroit dès
qu'une réplique précédente aurait été coupée en plusieurs pages. Le pipeline
est donc figé dans cet ordre : `aplatirEnElements` → `paginerElements` →
`calculerSommaire` → `monterProjection`.

**Troisième révision, sur la taille cette fois :** `tailleActiveReplique`
réduisait la police selon le nombre de mots — d'abord de la tirade entière,
puis, après la première fusion des pages (ci-dessus), de la somme des mots
de **toutes** les pages fusionnées. Effet pervers découvert à l'usage : une
tirade longue affichait un texte plus *petit* qu'une réplique courte
voisine simplement parce qu'elle n'était pas encore active — l'inverse de
l'effet recherché. La cause : cette réduction datait d'avant la fusion des
pages, quand il fallait faire tenir toute une tirade sur un seul écran.
Une fois les pages fusionnées et navigables par défilement d'ancres
(ci-dessus), ce problème n'existe plus — la longueur du texte n'a donc plus
aucune raison d'influencer sa taille. `tailleActiveReplique` est supprimée ;
la taille de la réplique active est désormais **fixe** (`clamp(1.2rem,
2.4vw, 2.2rem)`), qu'elle fasse 3 mots ou 300.

**Quatrième révision, sur le seuil de pagination lui-même :** avec la
fusion des pages et la taille fixe ci-dessus, une réplique n'a plus besoin
de tenir seule sur l'écran pour rester confortable — seule une tirade
*vraiment* longue justifie encore un arrêt intermédiaire. Retour d'usage :
`MOTS_PAR_PAGE` à 45 (coupure forcée à 63) coupait des répliques d'une
soixantaine de mots qui tenaient pourtant très bien à l'écran, voisines
comprises. Relevé à 100 (coupure forcée à 140) — mais annoncé dès cette
révision comme une approximation par nombre de mots, pas par hauteur
réellement mesurée, à corriger si l'usage le demandait.

**Cinquième révision : remplacer le nombre de mots fixe par une mesure
réelle.** L'usage l'a effectivement demandé, et pour la raison prévue :
un seuil en mots ne peut être juste que pour *un* gabarit d'écran, or le
rendu diffère forcément entre un petit écran et un vidéoprojecteur (même
taille en `vw` : proportionnelle à des viewports de largeurs et ratios
différents). `CONFIG.MOTS_PAR_PAGE` (constante unique) est remplacée par
`CONFIG.PART_ECRAN_CIBLE` (0.6, soit 60 % de la hauteur de fenêtre) et
`mesurerMotsParPage(elements, cast)`, qui :

1. monte chaque réplique **seule**, texte complet non paginé, à la taille
   `.actif`, dans un conteneur hors-champ mais réellement rendu
   (`visibility: hidden`, jamais `display: none` — sans layout,
   `scrollHeight` vaudrait toujours zéro) ;
2. mesure sa hauteur réellement rendue dans **le navigateur courant**, à
   **la résolution courante** ;
3. si elle dépasse `CONFIG.PART_ECRAN_CIBLE × window.innerHeight`, calcule
   combien de pages seraient nécessaires (`Math.ceil(hauteur / cible)`) et
   en déduit un quota de mots par page **propre à cette réplique** —
   jamais une constante globale.

`paginerElements` accepte donc désormais une `Map<idRéplique, motsParPage>`
au lieu d'un nombre unique ; une réplique absente de la map (celles qui
tiennent déjà) n'est jamais coupée.

Pour rester rapide même sur une pièce de plusieurs centaines de répliques,
les écritures DOM (montage de toutes les répliques dans le conteneur de
mesure) sont groupées, puis les lectures (`scrollHeight`) le sont aussi :
alterner écriture et lecture forcerait une mise en page du navigateur par
réplique (« layout thrashing »), le tout groupé n'en force qu'une seule.
Mesuré sur la pièce complète utilisée pour les tests (1206 répliques,
44 scènes) : environ 25 ms — un aller-retour imperceptible à l'ouverture
d'une pièce, jamais pendant la lecture elle-même.

Limite assumée : `mesurerMotsParPage` s'exécute une fois, à l'ouverture de
la pièce, avec la fenêtre à sa taille du moment. Un redimensionnement en
cours de lecture (rotation d'écran, changement de sortie vidéo) ne
redéclenche pas la mesure — cohérent avec le reste de l'outil, qui ne gère
pas non plus le redimensionnement à chaud ailleurs.

**Sixième révision, sur le seuil lui-même : 0.6 → 0.95.** Retour d'usage :
une réplique qui tenait très bien, seule, sur l'écran était quand même
coupée. La raison tient à la fusion des pages (ci-dessus) : une fois
fusionnées en un seul bloc continu, couper ou non ne change **rien** à
l'affichage tant que le bloc entier tient à l'écran — les deux pages sont
montrées de toute façon, sans coupure visible. Viser 60 % de la fenêtre
(pour garder de la place pour la réplique suivante) coupait donc des
répliques qui n'avaient besoin d'aucune aide au défilement : la pagination
ne coûte plus une coupure visuelle depuis la fusion, seulement une pression
de flèche inutile pour la traverser. Le critère devient : ne paginer que si
la réplique **déborde réellement** de l'écran — 0.95, marge de 5 % pour la
barre de progression (non comptée dans la mesure, qui ne porte que sur la
réplique elle-même).

### 8.6 Sommaire cliquable

**Révision à l'usage :** avancer réplique par réplique jusqu'à un point
lointain de la pièce était trop lent en répétition. Deux ajouts, tous deux
en complément du clavier, jamais en remplacement (§9) :

- cliquer n'importe quelle diapo y saute directement (délégation d'un seul
  écouteur sur `#contenu-projection`, pas un écouteur par diapo) ;
- un panneau plein écran (`#panneau-sommaire`, touche `S` ou bouton dédié)
  liste les entrées de `calculerSommaire` sous forme de boutons cliquables,
  chacun portant sa position en `data-position` ; un clic y saute et referme
  le panneau.

Ceci relâche le principe initial « aucune interface de contrôle sur la
fenêtre de projection » (voir le prompt d'origine) : en usage réel, la
personne qui navigue regarde cet écran, pas un deuxième — lui refuser une
aide à la navigation directement là où elle regarde n'aurait servi qu'une
pureté de principe, pas l'usage.

### 8.7 Réplique à plusieurs personnages

Ajouté avec le schéma `repetition/2` (§5) : une réplique peut être dite par
plusieurs personnages à la fois (une exclamation collective, dans la pièce
réelle testée — deux ou quatre personnages selon les cas). Décision prise
avec l'utilisateur : **un badge `.qui` par personnage**, chacun dans la
couleur de son propre slot, plutôt qu'une couleur unique pour tout le
groupe qui aurait effacé la distinction entre les voix.

`_construireBadgeQui(personnage, cast, prenoms)` construit un badge —
`etiquetteReplique`, couleur, `data-slot` et `data-personnage` posés sur le
badge lui-même, pas sur la diapo — et `construireDiapoRepliqueFusionnee`
en pose un par entrée de `elPremiere.personnages` dans un conteneur
`.entete-replique` (`display: flex; flex-wrap: wrap`, pour que plusieurs
badges se répartissent ou reviennent à la ligne sans jamais déborder). La
barre d'accent de `.texte` (`--couleur`) reste simplifiée à la couleur du
premier personnage du groupe — les badges portent la distinction utile,
cette bordure n'est que décorative.

Conséquence sur les fonctions qui parlaient jusqu'ici « du » slot d'une
réplique, désormais potentiellement plusieurs :

- `mettreAJourPrenoms` interroge directement `.qui[data-slot="H1"]` (les
  badges), plus `[data-slot="H1"] .qui` (la diapo puis son unique badge) —
  chaque badge se recalcule indépendamment, sans toucher aux autres badges
  de la même réplique ;
- `diffuserPosition` recueille tous les badges de la diapo active
  (`diapo.querySelectorAll('.qui')`) et diffuse un tableau `slots`, plus un
  seul `slotQuiParle` ;
- `texteRappelControle(scene, slots, prenoms)` joint les lecteurs concernés
  par « + » dans le rappel de la fenêtre de contrôle.

L'écran d'attribution (§6) n'a besoin d'aucun changement : `piece.personnages`
liste déjà chaque personnage individuellement, qu'il parle seul ou en groupe
dans telle ou telle réplique — l'attribution reste un slot par personnage,
jamais par groupe.

---

## 9. Navigation

Clavier en usage principal sur ordinateur, complété par la souris pour les
sauts longs (§8.6, révision à l'usage) et par le défilement libre (roulette,
tactile) — indispensable sur un appareil sans clavier physique, comme un
iPhone :

| Entrée | Effet |
|---|---|
| `→` | élément suivant dans la liste plate |
| `←` | élément précédent |
| `F` | plein écran (`requestFullscreen`), utile si le clic initial est requis par le navigateur — **inopérant sur iOS**, voir plus bas |
| `S` | ouvre/ferme le panneau de sommaire (§8.6) |
| `Échap` | ferme le panneau de sommaire |
| clic sur une diapo | saute directement à cette diapo (§8.6) |
| clic sur une entrée du sommaire | saute à cette scène, referme le panneau |
| roulette de souris / glissement tactile | fait défiler librement ; la diapo qui occupe le centre de l'écran devient active (ci-dessous) |

### 9.1 Défilement libre (roulette, tactile — iPhone)

**Retour d'usage :** rien ne suivait un défilement manuel de
`#contenu-projection` (`overflow-y: auto`, natif depuis §8.1) — la roulette
de souris ou un glissement tactile faisaient bien défiler l'écran, mais la
diapo `.actif` restait celle laissée par la dernière flèche ou le dernier
clic. Sur iPhone, sans clavier physique, c'était plus grave : la flèche
n'existe pas, donc la seule navigation restante (clic, sommaire) imposait
de viser précisément une diapo à chaque geste.

`activerSuiviDefilement()` observe toutes les diapos montées avec un
`IntersectionObserver`, `rootMargin` réduit à une bande fine autour du
centre vertical de l'écran (`-45% 0px -45% 0px`) : la diapo qui traverse
cette bande devient active via `suivreDefilement(index)` — même écriture de
classe et dégradé que la navigation habituelle (`afficherPosition`), mais
**sans jamais déclencher son propre défilement** (`afficherPosition(diapos,
position, false)`, §8.1) : on suit le geste de la personne qui lit, on ne
le contrarie jamais avec un second défilement programmatique qui
partirait dans une autre direction.

**Point délicat : distinguer un défilement libre d'un défilement
programmatique.** `allerA` et le démarrage appellent aussi
`scrollIntoView` (via `afficherPosition`, `defiler = true`) pour amener la
diapo choisie par flèche/clic/sommaire à l'écran — et cette animation
traverse elle aussi la bande centrale, donc déclencherait l'observateur en
retour si rien ne l'en empêchait, avec le risque qu'une diapo intermédiaire
croisée en cours d'animation supplante la cible réelle.
`marquerDefilementProgrammatique()` pose une fenêtre de 600 ms (une
animation `smooth` n'a pas de durée standardisée, cette marge est
confortable) pendant laquelle l'observateur s'ignore lui-même. Vérifié avec
un `IntersectionObserver` simulé en Node (pas de vrai layout hors
navigateur, §8.5) : une intersection simulée pendant la fenêtre
programmatique n'a aucun effet ; une fois la fenêtre passée, elle déplace
correctement la diapo active.

**Repli, jamais un blocage :** si `IntersectionObserver` est absent (très
vieux navigateur), `activerSuiviDefilement` ne fait rien silencieusement —
la navigation clavier, le clic et le sommaire restent pleinement
utilisables sans lui (§11), le défilement libre n'est qu'un confort de
plus, jamais le seul chemin.

**Limite assumée sur iOS :** `requestFullscreen()` n'existe pas dans Safari
iOS pour un élément arbitraire (limite de la plate-forme, pas de contournement
possible depuis une page web). La touche `F` y reste sans effet ; la lecture
sur iPhone se fait donc dans la fenêtre du navigateur, jamais en plein écran
au sens strict — `-webkit-overflow-scrolling: touch` sur `#contenu-projection`
et `#panneau-sommaire` assure au moins un défilement tactile fluide.

### 9.2 Ne jamais s'arrêter sur une transition de scène

**Révision à l'usage :** les éléments `kind: 'scene'` étaient au départ
traversés comme les autres — un simple décalage d'index, sans cas
particulier — ce qui les rendait `.actif` (§8.1) au même titre qu'une
réplique : zoomés, mis en avant, une pression de flèche à part entière pour
les dépasser. Or une transition de scène n'est pas du contenu à lire, c'est
un repère ; s'y arrêter interrompt le rythme de lecture pour rien.

`eviterScene(elements, position, direction, longueur)` (fonction pure,
testée) corrige ceci : après tout calcul de position (`irA`), si le résultat
tombe sur une scène, on continue dans le sens du mouvement jusqu'au premier
élément réel. `allerA` infère la direction de la comparaison entre la
position visée et la position courante — pas besoin de la faire porter par
chaque appelant (flèches, clic sur une diapo, clic sur le sommaire
partagent donc tous le même comportement sans code dupliqué). Une scène
reste visible dans le flux comme repère (§8.1, dégradé compris), mais ne
devient jamais la diapo active. Une seule exception assumée, à la toute
première position de la pièce : si elle commence par une scène et qu'on
recule au-delà, il n'y a rien d'autre avant elle vers quoi continuer.

---

## 10. Persistance

### 10.1 Clés

```
lecture:v1:piece:<pieceSlug>          le REPET.json importé, écrit une fois
lecture:v1:cast:<pieceSlug>           { PERSONNAGE: 'H1', … }
lecture:v1:prenoms                    { H1: 'Émile', … } — global, pas par pièce (§13, point 4)
lecture:v1:session                    { pieceSlug, position } — reprise après un rechargement
```

`pieceSlug` : le champ `piece` du JSON, mis en minuscules, accents retirés,
espaces remplacés par `-`. Pas de hachage de contenu comme dans
`outil_repetition` (§10.2 de son `ARCHITECTURE.md`) : ce document ne suit pas
de progression individuelle à faire migrer entre deux réimports d'une même
pièce corrigée — le seul besoin ici est de retrouver l'attribution de la
dernière fois. Un slug par nom suffit (§13, point 1, pour le cas de collision).

### 10.2 Quand écrire

`piece` et `cast` : à l'import et à la validation de l'écran de préparation.
`prenoms` : différée de courte durée après chaque frappe dans la fenêtre de
contrôle. `session` : différée après chaque navigation clavier, pour que
rouvrir la fenêtre de projection reprenne à la bonne réplique (§13, point 3).

---

## 11. Gestion des erreurs

| Cas | Traitement |
|---|---|
| JSON importé non conforme | refus avant affichage ; message nommant le champ (schéma inconnu, `unites` vide, `personnages` absent…) — même esprit que `schema.js` |
| personnage sans slot attribué | bouton « démarrer » désactivé, liste des personnages manquants affichée |
| popup de contrôle bloquée | message inline + bouton « réessayer », jamais un bouton inerte |
| `BroadcastChannel` absent (navigateur très ancien) | message explicite « la fenêtre de contrôle ne se synchronisera pas », l'outil continue de fonctionner en projection seule |
| `localStorage` plein ou indisponible | bandeau « la pièce et l'attribution ne seront pas conservées », l'outil continue sans persistance (P4, même logique que `outil_repetition`) |
| élément `texte_sans_personnage` rencontré | affiché en style neutre distinct, jamais masqué ni fondu dans la réplique précédente |

**Bug corrigé à l'usage :** `#section-bandeau-stockage` (où s'affiche le
message ci-dessus) ne portait pas `hidden` dans le HTML de départ — vide en
l'absence d'erreur de stockage, elle s'affichait quand même comme une carte
vide (§6, cartes de section) une fois le style de section appliqué à toutes
les `<section>` sans distinction. Corrigé en la cachant par défaut ; le
JavaScript qui la peuple la rend déjà visible au bon moment
(`cible.hidden = false`), ce mécanisme existait déjà et n'a pas changé.

---

## 12. Configuration

```js
const CONFIG = Object.freeze({
  SCHEMAS_ACCEPTES: Object.freeze(['repetition/1', 'repetition/2']), // §5, §8.7
  SLOTS: Object.freeze(['H1','H2','H3','H4','H5','F1','F2','F3','F4','F5']),
  COULEURS_SLOT: Object.freeze({ H1: '#…', H2: '#…', /* … 10 couleurs contrastées */ }),
  PREFIXE_STOCKAGE: 'lecture:v1',
  DELAI_ECRITURE_MS: 500,
  CANAL_SYNCHRO: 'lecture:v1',
  PART_ECRAN_CIBLE: 0.95, // §8.5, remplace un ancien MOTS_PAR_PAGE fixe (45 puis 100)
  PORTEE_GRADIENT: 6, // §8.1, portée du dégradé continu autour de la position
});
```

---

## 13. Décisions validées

Tranchées le **2026-08-03**. Aucune ne change la structure du fichier — elles
portent sur quelques clés de stockage et une fonctionnalité optionnelle
(point 2).

| # | Question | Retenu |
|---|---|---|
| 1 | Collision de `pieceSlug` (deux pièces au même nom) | **Risque accepté** : pas de suffixe dérivé de `genere_le`. `pieceSlug` reste le nom de la pièce, mis en minuscules et sans accents (§10.1 inchangé) |
| 2 | Écran-titre avant la scène 1, à partir de `piece.liminaires` | **Omis.** Hors périmètre du prompt initial ; `piece.liminaires` n'est lu par aucune partie de l'outil. À reconsidérer si le besoin se manifeste à l'usage |
| 3 | Reprise de position à la réouverture de la fenêtre de projection | **Implémentée**, comme rédigé en §10 : `lecture:v1:session` écrit après chaque navigation, relu à l'ouverture pour reprendre à la bonne réplique |
| 4 | Portée de `lecture:v1:prenoms` | **Globale**, comme rédigé en §10.1 : indépendante de la pièce, ce sont les lecteurs présents ce jour-là |

Un seul point à noter sur la portée de ces choix : le point 2 est celui qui
retire le plus de surface — `piece.liminaires` est validé par aucune fonction
de §11 et n'a donc pas besoin d'être mentionné dans le modèle de §5.

**La prochaine étape est l'étape 2 du plan de livraison** (§14) : les sections
pures de `index.html` (config, validation, modèle, état, stockage), avant tout
DOM.

---

## 14. Plan de livraison

| # | Livrable | Vérifiable par |
|---|---|---|
| 1 | ✅ *fait* — ce document, validé, décisions de §13 tranchées | relecture |
| 2 | ✅ *fait* — sections pures (config, validation, modèle, état, stockage) | vérifié contre `outil_repetition/tests/exemple-repet.json` |
| 3 | ✅ *fait* — rendu projection (§8), navigation clavier | pièce d'essai affichée, DOM simulé en Node |
| 4 | ✅ *fait* — écran de préparation + attribution personnage → slot (§6), reprise de session | import → attribution → démarrage → reprise, vérifié de bout en bout |
| 5 | ✅ *fait* — fenêtre de contrôle + `BroadcastChannel` (§7) | prénom diffusé, popup bloquée gérée |
| 6 | ✅ *fait* — `README.md`, `.gitignore` (`outil_lecture/pieces/`), lien depuis le `README.md` racine | relecture |

**Les six étapes sont livrées.** Reste, à l'usage réel (vidéoprojecteur,
deuxième écran, plusieurs lecteurs), à confirmer la lisibilité de la
palette de couleurs et l'ergonomie de la fenêtre de contrôle — hors du
périmètre vérifiable sans matériel.

L'ordre 2 → 3 → 4 → 5 garde la même logique que `outil_repetition` : la
donnée avant l'écran, l'écran de projection avant le confort de contrôle.
