# ARCHITECTURE — outil de répétition

> **Statut : validé le 2026-08-03.** Les quatre décisions ouvertes ont été
> tranchées ; le relevé figure en [§15](#15-décisions-validées). L'implémentation
> peut commencer à l'étape 3 du [plan de livraison](#14-plan-de-livraison).
>
> Ce document réalise le [cahier des charges](CAHIER_DES_CHARGES.md) et en révise
> un point : le découpage en fichiers (§3.2, révision du §11.1 du cahier).
>
> Révision notable depuis la première rédaction : le **repli par enregistrement
> audio est retiré du périmètre**, `voix.js` ne porte plus que Web Speech.

---

## Table des matières

1. [Objectif et principes directeurs](#1-objectif-et-principes-directeurs)
2. [Vue d'ensemble](#2-vue-densemble)
3. [Arborescence](#3-arborescence)
4. [Rôle de chaque module](#4-rôle-de-chaque-module)
5. [Le modèle en mémoire](#5-le-modèle-en-mémoire)
6. [Le rendu : le masquage est du CSS](#6-le-rendu--le-masquage-est-du-css)
7. [Persistance](#7-persistance)
8. [Reconnaissance vocale](#8-reconnaissance-vocale)
9. [Comparaison de texte](#9-comparaison-de-texte)
10. [Problèmes délicats et leur résolution](#10-problèmes-délicats-et-leur-résolution)
11. [Gestion des erreurs](#11-gestion-des-erreurs)
12. [Configuration](#12-configuration)
13. [Tests](#13-tests)
14. [Plan de livraison](#14-plan-de-livraison)
15. [Décisions validées](#15-décisions-validées)

---

## 1. Objectif et principes directeurs

Apprendre et répéter mon texte, sur iPhone 15 en priorité, sans installation ni
backend.

Six principes gouvernent les décisions de ce document. Trois d'entre eux
répondent directement à des défauts constatés dans l'existant.

### P1 — Le texte de l'auteur n'est jamais modifié

L'outil lit le `REPET.json` et n'y écrit rien. Annotations, statuts et scores
vivent dans des clés séparées, indexées par identifiant de réplique (§7). Même
principe que `outil_edition` : l'outil sert l'œuvre, il ne la réécrit pas.

### P2 — Utilisable hors ligne et sans micro

La reconnaissance vocale exige le réseau sur iOS et échoue de façon capricieuse
(§8). Elle est donc un **supplément**. Tout le reste — chargement d'une pièce,
six modes de masquage, progression, annotations, bilan — fonctionne en mode
avion. Un test de recette l'exige explicitement (§14, étape 8).

### P3 — Aucune erreur silencieuse

C'est la leçon de l'existant : `window.storage.get()` entouré d'un
`catch { return null }` donne l'illusion d'une sauvegarde qui n'a jamais eu lieu.
Corollaires tenus partout :

- aucun `catch` ne se contente d'un `return null` ou d'un `return ''` ;
- toute défaillance est **soit** affichée à l'écran, **soit** consignée dans un
  journal consultable depuis les réglages ;
- une capacité absente (micro, Wake Lock) **retire son bouton** au lieu de le
  laisser inerte.

### P4 — La progression est précieuse, jamais critique

Sa perte n'empêche jamais de répéter. Elle est exportable (§7.4), et Safari la
purge après 7 jours d'inactivité. L'outil doit donc démarrer normalement sur un
stockage vide, et ne jamais faire dépendre l'affichage du texte de la présence
d'un statut.

### P5 — Aucune dépendance, aucune étape de build

Pas de npm, pas de bundler, pas de framework. Du JavaScript de module natif,
servi tel quel. Ce qui est écrit est ce qui s'exécute — condition pour qu'un
correctif en coulisses reste possible, et pour que le projet soit encore
modifiable dans deux ans.

### P6 — La logique pure est séparée du DOM

Les modules de `js/` marqués **purs** ne touchent ni `document`, ni `window`, ni
`localStorage`, ni `Math.random`, ni l'horloge. Ils sont importables par
`node --test` sans navigateur, et leur pureté est vérifiée mécaniquement (§13).
C'est la transposition directe de `utils/blocks.py` dans `outil_edition`, dont la
pureté est contrôlée par analyse AST.

---

## 2. Vue d'ensemble

```
                 GitHub Pages (HTTPS)
   ┌──────────────────────────────────────────────┐
   │ index.html + js/ + sw.js  ← coque, mise en   │
   │                              cache hors ligne│
   └──────────────────────────────────────────────┘
                        │
   REPET.json ──────────┤  collé / importé / fetch local
   (outil_edition)      │
                        ▼
              ┌───────────────────┐
              │ schema.valider()  │  refus explicite si non conforme
              └───────────────────┘
                        ▼
              ┌───────────────────┐
              │ modele.indexer()  │  PUR — tops, mes scènes, ordre
              └───────────────────┘
                        ▼
   ┌────────────────────────────────────────────────────┐
   │ etat  ──▶ rendu.monter()   une fois par unité      │
   │       ──▶ data-mode        changement de mode = 0  │
   │                            re-rendu (§6)           │
   └────────────────────────────────────────────────────┘
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
   stockage.js       voix.js        (export JSON)
   localStorage    Web Speech
```

Le point à retenir : **changer de mode, de personnage ou de difficulté ne
reconstruit rien.** C'est le défaut central de l'existant, dont `renderScript()`
vide et reconstruit tout le DOM à chaque bascule. Invisible sur une pièce de 90
pages, ce défaut deviendrait rédhibitoire avec 300 pages, des annotations et des
statuts par réplique.

---

## 3. Arborescence

### 3.1 Les fichiers

```
outil_repetition/
├── index.html               coque HTML + tout le CSS. Aucune logique métier.
├── manifest.webmanifest     nom, icône, plein écran à l'écran d'accueil
├── sw.js                    service worker — ouverture hors ligne
├── icone.svg                icône d'écran d'accueil
├── package.json             AUCUNE dépendance — voir plus bas
│
├── js/
│   ├── config.js       PUR  toutes les constantes. Aucune logique.
│   ├── schema.js       PUR  validation du REPET.json
│   ├── texte.js        PUR  normalisation, amorces, découpage en mots
│   ├── comparaison.js  PUR  alignement mot à mot, score
│   ├── modele.js       PUR  index dérivé : tops, mes scènes, spot check
│   ├── tirage.js       PUR  générateur pseudo-aléatoire à graine (§10.4)
│   ├── etat.js         PUR  état + transitions
│   ├── stockage.js          localStorage, export / import
│   ├── voix.js              Web Speech uniquement
│   ├── rendu.js             DOM
│   └── app.js               câblage, écouteurs, orchestration
│
├── tests/
│   ├── purete.test.js       contrôle mécanique de la pureté (§13)
│   ├── contrat.test.js      le contrat avec outil_edition (§13.1)
│   ├── exemple-repet.json   REPET.json réel, produit par repet_export.py
│   └── <module>.test.js     un fichier par module pur
│
└── pieces/                  JAMAIS versionné (.gitignore) — usage local
```

**`package.json` ne déclare aucune dépendance.** Il existe pour une seule
raison : sans `"type": "module"`, Node traite les `.js` comme du CommonJS et
refuse leurs `export`. Le navigateur, lui, n'en a pas besoin —
`<script type="module">` suffit. `npm install` n'a jamais à être lancé, et
`node_modules/` n'existera pas.

### 3.2 Révision du §11.1 du cahier des charges

Le cahier annonçait 4 fichiers, toute la logique dans `index.html`. **Je propose
d'en faire une quinzaine**, pour une raison qui pèse plus que le compte de
fichiers : **sans découpage, rien n'est testable.**

`outil_edition` compte 551 tests, et sa logique la plus délicate est isolée dans
un module pur dont l'absence d'I/O est vérifiée par analyse AST. Le même souci
appliqué ici demande que la normalisation du français, l'alignement mot à mot, le
calcul des tops et la validation du schéma soient importables **sans navigateur**.
Un fichier unique de 2 500 lignes rend cela impossible.

Ce que la révision ne change pas :

- **aucune étape de build** — les modules ES sont natifs, servis tels quels (P5) ;
- **aucune dépendance** ;
- **une seule URL à ouvrir** — l'objectif réel du « fichier unique » du prompt
  initial était l'absence d'installation, et il est tenu ;
- **le service worker précharge les 12 fichiers**, donc un seul aller-retour
  réseau au premier chargement, et zéro ensuite.

Ce que la révision coûte : les modules ES n'étant pas chargeables depuis
`file://` (politique d'origine), l'outil ne s'ouvre plus par double-clic sur
`index.html`. Il faut l'URL HTTPS, ou `python -m http.server` en local. C'est
sans conséquence : le micro imposait déjà HTTPS (§4.1 du cahier).

Validé en [§15](#15-décisions-validées), décision 1.

---

## 4. Rôle de chaque module

| Module | Responsabilité unique | Pur ? | Touche le DOM ? |
|---|---|---|---|
| `config.js` | constantes | oui | non |
| `schema.js` | valider un `REPET.json`, refuser clairement | **oui** | non |
| `texte.js` | normaliser, découper en mots, extraire une amorce | **oui** | non |
| `comparaison.js` | aligner récité / attendu, produire un score | **oui** | non |
| `modele.js` | index dérivé du JSON : tops, mes scènes, ordre, spot check | **oui** | non |
| `tirage.js` | aléatoire reproductible à partir d'une graine | **oui** | non |
| `etat.js` | l'état de session et ses transitions | **oui** | non |
| `stockage.js` | `localStorage`, export / import, quota | non | non |
| `voix.js` | Web Speech et permission micro | non | non |
| `rendu.js` | montage et mise à jour du DOM | non | **oui** |
| `app.js` | câblage, écouteurs, cycle de vie | non | oui |

Deux invariants se lisent dans ce tableau, et ce sont eux qui rendent le projet
tenable :

- **sept modules sur onze sont purs.** Toute la logique délicate — comparaison de
  français parlé, calcul des tops, validation de schéma — est testable sans
  navigateur, sans micro, sans stockage ;
- **un seul module touche le DOM.** `rendu.js` est le seul endroit où une erreur
  d'affichage peut se trouver, et `voix.js` le seul où une API capricieuse peut
  se cacher.

---

## 5. Le modèle en mémoire

### 5.1 L'index dérivé

`modele.indexer(json, mesRoles)` produit, en une passe et sans effet de bord, ce
que le rendu et la navigation demanderaient sinon en boucle :

```js
{
  unites: [ { id, acte, scene, implicite, mienne, personnages, elements } ],
  repliques: Map<id, { unite, position, personnage, texte, mienne }>,
  ordreRepliques: [ id, … ],          // ordre de jeu, toutes unités
  mesRepliques: [ id, … ],            // sous-ensemble, pour les sauts de top
  tops: Map<idReplique, Top>,         // §10.1
  sommaire: [ { unite, titre, mienne, nbMesRepliques } ]
}
```

`unite.mienne` est calculé une fois, par intersection de `unite.personnages`
(précalculé dans le JSON) avec **l'ensemble de mes rôles dans la pièce**. Replier
tout un acte devient alors instantané, même sur 300 pages.

**L'index dépend de `mesRoles`, pas du rôle actif.** C'est la distinction du §6
du cahier : mes rôles décident ce qui est une de mes scènes, le rôle actif décide
ce qui est masqué. Le premier est structurel et entre dans l'index ; le second
est présentationnel et reste dans le CSS (§6). Changer de rôle actif en cours de
session ne réindexe donc rien.

### 5.2 L'état de session

```js
{
  pieceId,
  mesRoles: Set<string>,       // ce que je joue dans cette pièce
  roleActif: Set<string>,      // ce que je répète maintenant (⊆ mesRoles)
  mode,                        // lecture | masquage | amorce | trous | aveugle | top
  mesScenesSeules: bool,
  difficulte: 0..100,
  uniteCourante,
  reglages: { taillePolice, vitesseDefilement, sombre },
  revelees: Set<idReplique>    // volatile : vidé au changement de mode
}
```

`etat.js` est pur : il expose des transitions `(etat, action) → etat` et ne
connaît ni le DOM ni le stockage. Ce qui est **volatile** (`revelees`) et ce qui
est **persistant** (tout le reste) est séparé explicitement, pour qu'aucune
réplique révélée hier ne se retrouve révélée demain.

---

## 6. Le rendu : le masquage est du CSS

C'est la décision d'architecture la plus conséquente du document.

### 6.1 Le constat

Six modes de masquage, deux réglages de repli de scènes, un rôle actif
changeable : à traiter en JavaScript, cela fait une combinatoire qui reconstruit
le DOM à chaque geste. C'est ce que fait l'existant, et c'est ce qui ne passera
pas l'échelle.

Or **le masquage est une question de présentation, pas de contenu.** Le texte
d'une réplique est le même dans les six modes ; seule sa visibilité change.

### 6.2 La conséquence : monter une fois, décorer en CSS

Chacune de mes répliques est montée **une seule fois**, découpée de façon à ce que
les six modes soient exprimables en CSS :

```html
<div class="replique mienne" data-id="r_8f3a1c" data-perso="JAN">
  <div class="qui">JAN</div>
  <div class="texte">
    <span class="amorce"><span class="mot">Je</span> <span class="mot">t'attendais</span>
      <span class="mot">depuis</span></span>
    <span class="suite"><span class="mot" data-trou="1">une</span>
      <span class="mot">heure</span>.</span>
  </div>
</div>
```

Le mode vit dans un attribut de la racine, et chaque mode est une règle :

```css
[data-mode="masquage"] .replique.actif  .texte      { visibility: hidden }
[data-mode="amorce"]   .replique.actif  .suite      { visibility: hidden }
[data-mode="trous"]    .replique.actif  [data-trou="1"] { color: transparent;
                                                          background: var(--trou) }
[data-mode="aveugle"]  .replique.actif  .texte      { visibility: hidden }
[data-mode="top"]      .replique:not(.top)          { display: none }
.replique.revelee .texte, .mot.revelee              { visibility: visible !important }
[data-mes-scenes="1"] .unite:not(.mienne) .elements { display: none }
```

`.actif` marque les répliques du rôle actif. Il est posé par un sélecteur
d'attribut, sans parcours JS :

```css
.replique[data-perso="JAN"] { /* … */ }
```

`app.js` injecte une unique règle dans une feuille de style dédiée quand le rôle
actif change. **Changer de rôle actif, de mode ou replier les scènes coûte donc
une écriture d'attribut ou une règle CSS** — jamais un re-rendu.

### 6.3 Ce qui reste en JavaScript

| Geste | Coût |
|---|---|
| changer de mode | 1 écriture d'attribut |
| changer de rôle actif | 1 règle CSS réécrite |
| replier / déplier mes scènes | 1 écriture d'attribut |
| changer la difficulté des trous | N écritures de `data-trou` sur l'unité visible |
| révéler une réplique | 1 classe |
| annoter, changer un statut | 1 nœud modifié |
| naviguer vers une autre unité | montage paresseux (§6.4) |

### 6.4 Montage paresseux par unité

Une pièce de 300 pages où j'ai 800 répliques de 25 mots ferait 20 000 `<span>`
si tout était monté d'emblée. Le DOM est donc borné :

- l'unité jouable (§3.2 du cahier) est **l'unité de montage** — c'est déjà l'unité
  de repli et de sommaire ;
- une unité est montée à la demande : navigation par sommaire, ou approche au
  défilement détectée par `IntersectionObserver` ;
- au-delà de `UNITES_MONTEES_MAX` unités montées, les plus lointaines sont
  démontées ; leur hauteur est conservée par un bloc de remplacement pour ne pas
  faire sauter le défilement.

La recherche, le sommaire et le bilan portent sur **l'index, pas sur le DOM** :
ils fonctionnent donc sur toute la pièce même si une seule unité est montée.
C'est une conséquence de §5.1, et la raison pour laquelle l'index doit exister.

---

## 7. Persistance

### 7.1 Des clés séparées

Reprise du §10 du cahier :

```
repet:v1:index                        liste des pièces
repet:v1:piece:<id>                   le REPET.json — écrit une fois, jamais modifié
repet:v1:progres:<id>:<PERSONNAGE>    statuts et historique
repet:v1:annotations:<id>             annotations et marque-pages
repet:v1:reglages                     mode, taille de police, vitesse, sombre
repet:v1:session                      pièce et unité courantes
```

`piece:<id>` immuable est ce qui permet de **recharger une pièce rééditée sans
perdre ses annotations** : elles vivent dans une autre clé, indexées par
identifiant de contenu (§10.2).

Un statut écrit ne réécrit donc jamais les 200 Ko de la pièce. Sans cette
séparation, chaque tape sur « maîtrisée » recopierait le texte intégral.

### 7.2 Quand écrire

- `progres`, `annotations` : écriture différée de `DELAI_ECRITURE_MS` après le
  dernier changement, et forcée sur `visibilitychange` — sur iOS, `beforeunload`
  n'est pas fiable, et c'est `visibilitychange` qui attrape le passage en arrière-plan ;
- `reglages`, `session` : écriture différée ;
- `piece` : une fois, à l'import.

### 7.3 Le quota

`QuotaExceededError` est traité, jamais avalé (P3) : message nommant la cause
probable — trop de pièces, ou historique trop long — et proposant l'export puis
la suppression d'une pièce. L'historique des scores est plafonné à
`SCORES_PAR_REPLIQUE` entrées, les plus anciennes chassées d'abord.

### 7.4 Export et import

Un objet unique, versionné, contenant tout **sauf les pièces** : un `REPET.json`
est reproductible depuis `outil_edition`, une progression ne l'est pas.

```json
{ "export": "repetition/1", "date": "…", "progres": {…}, "annotations": {…}, "reglages": {…} }
```

L'import est **fusionnant, jamais écrasant** : pour une même réplique, le statut
le plus avancé et l'historique le plus long gagnent. Un import écrasant
détruirait le travail fait sur l'appareil depuis l'export, ce qui est exactement
le geste qu'on ferait en croyant se protéger.

L'écran de bilan affiche la date du dernier export et alerte au-delà de
`JOURS_SANS_EXPORT_ALERTE`, puisque Safari purge après 7 jours d'inactivité.

---

## 8. Reconnaissance vocale

### 8.1 Une machine à états explicite, isolée dans `voix.js`

```
   indisponible ──────────────────────────────▶ (aucun bouton affiché)
        │
   inactif ──appui──▶ permission ──▶ décompte(2s) ──▶ écoute
        ▲                  │                            │
        │                  ▼                            ▼
        └──── refus ◀── échec ◀───── silence/erreur ── résultat
```

Cinq règles, toutes issues des limites réelles d'iOS (§4.3 du cahier) :

1. **Un bouton par réplique**, jamais global : une réplique à la fois.
2. **Décompte visible de `DELAI_AVANT_ECOUTE_MS`** avant d'écouter. Siri activé,
   Safari met 2 à 3 secondes à ouvrir réellement le micro : sans ce délai, le
   début de la réplique est systématiquement perdu.
3. **Écoute non continue**, arrêt explicite au doigt, plus un délai de garde
   `ECOUTE_MAX_MS`. Des rapports récurrents décrivent une écoute qui ne s'arrête
   jamais : le délai de garde est la protection, pas le confort.
4. **Seuls les résultats finaux comptent.** Les résultats intermédiaires sont
   affichés s'ils arrivent, jamais utilisés pour un score.
5. **Un échec est un non-événement** : aucun score enregistré, aucune alerte
   modale, retour à `inactif`. La progression s'obtient au doigt de toute façon.

### 8.2 Les replis, dans l'ordre

| Situation | Comportement |
|---|---|
| API absente | le bouton micro n'est pas monté ; mention une fois dans les réglages |
| permission refusée | marche à suivre dans Réglages iOS |
| hors ligne (`navigator.onLine === false`) | « la reconnaissance vocale a besoin du réseau » |
| silence ou interruption | abandon après le délai de garde, sans trace |

`navigator.onLine` à `false` est fiable ; à `true` il ne prouve rien. Il sert
donc à **éviter une tentative vouée à l'échec**, pas à garantir un succès.

**Le repli est unique, et c'est le chemin normal de l'outil** : je récite, puis je
touche « su » ou « à revoir ». Aucune de ces cinq situations ne demande donc de
code supplémentaire — elles ramènent toutes à ce que P2 impose déjà de savoir
faire sans micro. C'est ce qui a permis de retirer `MediaRecorder` du périmètre
(§15, décision 4) sans rien laisser d'inachevé : il n'y avait pas de trou à
combler sous le repli audio.

---

## 9. Comparaison de texte

Module pur, entièrement testable, et c'est l'endroit où un score absurde se
fabrique si l'on n'y prend pas garde.

### 9.1 Normaliser des deux côtés

La transcription iOS rend un texte **sans ponctuation**, avec des apostrophes
typographiques et des nombres parfois en chiffres. `texte.normaliser()` applique,
au récité **comme** à l'attendu : minuscules, dépose des accents, `’ → '`,
ponctuation et tirets retirés, espaces réduits, nombres en chiffres convertis en
mots.

Un seul chemin de normalisation pour les deux côtés : deux fonctions
divergeraient au premier correctif.

### 9.2 Ne pas comparer ce qui n'est pas dit

Le texte attendu exclut les `didascalies_internes` : *elle se lève* ne se
prononce pas. Les compter en mots oubliés ferait chuter le score de chaque
réplique qui porte un jeu de scène — c'est-à-dire les plus travaillées.

### 9.3 Aligner, puis classer

Alignement mot à mot par plus longue sous-séquence commune (programmation
dynamique). Les longueurs en jeu — quelques dizaines de mots, `MOTS_MAX_ALIGNEMENT`
en garde-fou — rendent le coût quadratique sans objet.

Classement issu de l'alignement : `correct`, `oublie`, `ajoute`, et **`substitue`
quand un oubli et un ajout sont adjacents** — sinon « chaise » dit à la place de
« chaire » compterait deux fautes au lieu d'une.

Score = `correct / mots attendus`, arrondi. Les mots en trop pèsent sur le
détail affiché, pas sur le score : réciter juste en ajoutant un « eh bien » n'est
pas une faute de mémoire.

---

## 10. Problèmes délicats et leur résolution

### 10.1 Qu'est-ce que « le top » ?

Le top n'est pas « la réplique précédente ». Trois cas, et ils demandent tous une
réponse différente :

| Cas | Top retenu |
|---|---|
| l'élément précédent est une réplique d'un autre | cette réplique |
| l'élément précédent est une didascalie | **la didascalie** — une porte qui claque est un top |
| ma réplique ouvre l'unité, ou suit une de mes répliques | **aucun top** → marqué « enchaînement » |

Le troisième cas est celui qu'on oublie. Deux de mes répliques séparées par une
didascalie, ou une réplique en tête de scène, n'ont pas de top : afficher un
encadré vide, ou le top d'avant, induirait en erreur en répétition. L'outil
affiche `enchaînement — pas de top`, ce qui est une information utile.

`modele.tops` est calculé une fois à l'indexation, en même temps que le reste.

### 10.2 Identité d'une réplique à travers une réédition

Rappel du §3.2 du cahier : l'`id` est une empreinte de `personnage + texte
normalisé`, avec suffixe d'occurrence pour les doublons (« Oui. » dit quatre
fois).

Conséquence à assumer, et c'est la bonne : **une réplique dont le texte a changé
perd son statut.** Le texte a changé, il faut la réapprendre. Toutes ses voisines
conservent le leur, alors que des identifiants positionnels auraient décalé
silencieusement toute la progression d'un cran.

À l'import d'une pièce déjà connue, l'outil annonce le bilan du raccord :
`214 répliques reconnues, 3 nouvelles, 2 disparues`. Un raccord muet laisserait
croire à une perte de données là où il n'y a qu'une correction éditoriale.

### 10.3 Mes rôles et le rôle actif

Deux notions distinctes, déjà énoncées, et que le code doit garder distinctes
parce que les confondre produit un bug discret :

- `mesRoles` — ce que je joue dans la pièce. Décide de `unite.mienne`, donc du
  repli des scènes. **Entre dans l'index** (§5.1).
- `roleActif` ⊆ `mesRoles` — ce que je répète maintenant. Décide de ce qui est
  masqué. **Reste dans le CSS** (§6.2).

Dans une scène où deux de mes personnages dialoguent, chaque réplique masquée
affiche son `.qui` — jamais un bloc anonyme. C'est une exigence du cahier, et
elle est gratuite ici : `.qui` n'est jamais masqué par les règles de §6.2.

### 10.4 Le tirage des mots à trous doit être stable

L'existant appelle `Math.random()` à chaque rendu. Deux conséquences fâcheuses :
les trous se déplacent à chaque bascule de mode, et une réplique travaillée trois
fois de suite masque trois fois des mots différents — ce qui empêche exactement le
travail qu'on cherche à faire.

`tirage.js` fournit un générateur pseudo-aléatoire déterministe, graine dérivée de
`(idReplique, difficulte, numeroDePassage)`. Les trous sont donc **stables tant
qu'on ne demande pas un nouveau tirage**, et un bouton « nouveau tirage »
incrémente le numéro de passage. Le module est pur : le tirage est testable.

### 10.5 Le service worker et la purge iOS

Stratégie volontairement banale, parce qu'il n'y a rien à gagner à être
astucieux :

- `install` : préchargement de la liste explicite des 12 fichiers ;
- `fetch` : cache d'abord, réseau en repli. Les pièces ne passent jamais par le
  réseau (elles sont en `localStorage`), donc jamais par le cache ;
- déploiement : `CACHE_VERSION` incrémenté à la main dans `sw.js`, anciens caches
  supprimés à l'`activate`.

**Le service worker fait partie de ce que Safari purge après 7 jours.** Après une
purge, le premier chargement exige donc du réseau, puis tout redevient hors ligne.
C'est une limite à documenter dans le README, pas un défaut à corriger : aucune
API ne permet de s'en exempter depuis iOS 17.4.

### 10.6 Réglage de la taille de police et zoom

La taille de police est un `--taille-texte` sur la racine, en `rem`. Elle
n'entre **pas** en conflit avec le pinch-zoom, que §4.4 du cahier impose de
laisser vivre : l'un change le corps du texte dans une mise en page qui se
recompose, l'autre agrandit tout sans recomposer. Les deux servent des besoins
différents, et l'existant supprimait le second.

### 10.7 Le spot check ne doit pas être uniforme

Piocher uniformément parmi les répliques « maîtrisées » redemanderait souvent
celles qu'on vient de vérifier. Le tirage est donc **pondéré par l'ancienneté**
de la dernière vérification : à maîtrise égale, la plus anciennement vue sort la
première. C'est le seul comportement qui teste réellement la mémoire à long
terme, et il ne coûte qu'un tri.

---

## 11. Gestion des erreurs

P3 en pratique. Quatre familles, quatre traitements, aucun `catch` vide.

| Famille | Traitement |
|---|---|
| `REPET.json` non conforme | refus **avant** tout chargement, message nommant le champ fautif. Un `schema` de version supérieure est refusé, jamais interprété au mieux |
| `localStorage` indisponible ou saturé | bandeau persistant « la progression ne sera pas conservée », et l'outil continue de fonctionner (P4) |
| capacité absente (micro, Wake Lock) | la commande n'est pas montée. Un bouton inerte est pire que pas de bouton |
| erreur inattendue | `window.onerror` et `unhandledrejection` consignent dans un journal en mémoire, consultable depuis les réglages et exportable |

Ce dernier point est ce qui aurait révélé le bug `window.storage` en dix
secondes au lieu de le laisser vivre indéfiniment.

---

## 12. Configuration

Toutes les constantes dans `js/config.js`, aucun nombre magique ailleurs — même
règle que `config.py` dans `outil_edition`.

```js
export const CONFIG = {
  MOTS_AMORCE:              3,     // mode « amorce seule »
  MOTS_TOP:                 5,     // derniers mots du top en affichage réduit
  DIFFICULTE_DEFAUT:        45,    // % de mots masqués en mode trous
  UNITES_MONTEES_MAX:       5,     // §6.4
  SCORES_PAR_REPLIQUE:      10,    // §7.3
  DELAI_ECRITURE_MS:        800,
  DELAI_AVANT_ECOUTE_MS:    2000,  // §8.1, règle 2
  ECOUTE_MAX_MS:            30000, // délai de garde
  MOTS_MAX_ALIGNEMENT:      400,   // §9.3
  JOURS_SANS_EXPORT_ALERTE: 5,     // avant les 7 jours de Safari
  VITESSE_DEFILEMENT:       [1, 2, 3, 4],
  LANGUE_RECONNAISSANCE:    'fr-FR',
};
```

`JOURS_SANS_EXPORT_ALERTE` à 5 et non 7 : alerter le jour de l'échéance serait
alerter trop tard.

---

## 13. Tests

**Aucune dépendance**, dans l'esprit des tests d'`outil_edition` qui tournent
sans clé API ni réseau.

```bash
cd outil_repetition
node --test tests/*.test.js       # ou : npm test
```

Les modules purs n'important ni DOM ni API navigateur, Node les charge tels
quels. C'est précisément ce que le découpage de §3.2 achète.

Le glob est explicite et non `node --test tests/` : sous Windows, la forme
« dossier » se fait interpréter comme un module à charger et échoue avec un
`MODULE_NOT_FOUND` déroutant.

**La pureté est vérifiée mécaniquement.** Un test lit la source des sept modules
purs et échoue s'il y trouve `document`, `window`, `localStorage`, `fetch`,
`Math.random` ou `Date.now`. C'est la transposition du contrôle AST qui garde
`utils/blocks.py` pur dans `outil_edition` — sans ce test, la pureté se dégrade au
premier correctif pressé.

### 13.1 Le contrat avec `outil_edition`

`tests/exemple-repet.json` est un **vrai `REPET.json`**, produit par
`repet_export.py` sur une pièce d'essai de quelques répliques, et versionné.
`contrat.test.js` le valide avec `schema.js`.

C'est le seul test qui éprouve les deux outils ensemble, et il attrape la classe
de défauts la plus coûteuse : une divergence silencieuse entre ce que Python écrit
et ce que le navigateur attend. Un champ renommé d'un côté se découvrirait sinon
en chargeant une pièce sur le téléphone.

Il vérifie en particulier le point de jonction le plus fragile : `avant_mot` est
calculé en Python par un découpage sur les espaces, et `texte.mots()` doit compter
**exactement pareil**. Un décalage d'une unité afficherait chaque didascalie au
mauvais endroit, sans qu'aucun test de module ne s'en aperçoive.

La pièce d'essai est écrite pour ce test, donc libre de droits — contrairement
aux pièces réelles, que `.gitignore` écarte.

### 13.2 Priorités de couverture

Cas de test à couvrir en priorité, parce que ce sont les endroits où un bug est
invisible à l'œil :

- `schema.js` — chaque champ manquant, version supérieure, `unites` vide ;
- `texte.js` — apostrophes typographiques, accents, nombres, ponctuation ;
- `comparaison.js` — oubli, ajout, substitution adjacente, didascalie interne
  exclue, réplique récitée mot pour mot (score 100), réplique vide ;
- `modele.js` — les trois cas de top de §10.1, une unité sans acte, une pièce
  sans scène, deux de mes rôles en dialogue ;
- `tirage.js` — même graine, même tirage ; graine différente, tirage différent ;
- `etat.js` — `roleActif ⊄ mesRoles` refusé, `revelees` vidé au changement de mode.

---

## 14. Plan de livraison

Un commit par étape. Reprend le §13 du cahier, en le précisant.

| # | Livrable | Vérifiable par |
|---|---|---|
| 1 | ✅ *fait* — purge de l'historique | `git log -p` ne montre plus le blob |
| 2 | ✅ *fait* — ce document, validé | relecture |
| 3 | ✅ *fait* — `repet_export.py` dans `outil_edition` + tests | 610 tests Python verts |
| 4 | ✅ *fait* — `config.js`, `schema.js`, `texte.js`, `comparaison.js`, `tirage.js` | 119 tests Node verts, pureté et contrat compris |
| 5 | `modele.js`, `etat.js` + tests | les trois cas de top couverts |
| 6 | Coque : `index.html`, chargement d'une pièce, `stockage.js`, choix des rôles | une pièce chargée survit à la fermeture de Safari |
| 7 | `rendu.js` : les 6 modes en CSS, le top, le repli de scènes, montage paresseux | usage réel sur iPhone 15 |
| 8 | Progression, bilan, spot check, export / import | export puis import restitue à l'identique ; fusion vérifiée |
| 9 | Confort : sommaire, recherche, marque-pages, annotations, défilement, Wake Lock | — |
| 10 | `voix.js` et ses replis (Web Speech seul) | testé sur iPhone 15 en HTTPS **et en mode avion** |
| 11 | `manifest`, `sw.js`, activation de GitHub Pages | ouverture hors ligne depuis l'écran d'accueil |
| 12 | `README.md` du sous-projet | — |

L'ordre 4 → 5 → 6 → 7 n'est pas négociable : le pur avant l'impur, la logique
avant le DOM. Il donne des tests verts avant qu'il y ait quoi que ce soit à
regarder, et c'est la seule façon d'avoir confiance dans un score de fidélité.

**L'outil est utilisable dès l'étape 7**, sans micro et sans hors ligne.

---

## 15. Décisions validées

Tranchées le **2026-08-03**. Aucune décision ne reste ouverte : l'implémentation
peut commencer à l'étape 3 du [plan de livraison](#14-plan-de-livraison).

| # | Décision | Retenu | Où cela se lit |
|---|---|---|---|
| 1 | Découpage en fichiers | **12 fichiers**, modules ES natifs, aucune étape de build | §3.1, §3.2 |
| 2 | Exécution des tests | **`node --test`** sur les 7 modules purs, `tests.html` en complément pour le rendu | §13 |
| 3 | Montage du DOM | **paresseux par unité dès l'étape 7**, pas de rendu complet transitoire | §6.4 |
| 4 | Repli enregistrement audio | **retiré du périmètre** | §8.2, étape 10 |

Deux remarques sur la portée de ces choix.

**La décision 1 est celle qui conditionne les autres.** Sans découpage, pas de
`node --test`, donc pas de test de pureté, donc aucun moyen de se fier au score
de fidélité produit par `comparaison.js`. Les décisions 1 et 2 forment un seul
choix vu de deux côtés.

**La décision 4 ne laisse aucun trou.** Le repli audio ne comblait rien : les
cinq situations d'échec du micro (§8.2) ramènent toutes au chemin principal de
l'outil — je récite, je touche « su » ou « à revoir » — que P2 impose de savoir
faire sans micro de toute façon. Ce qui disparaît, c'est `MediaRecorder`, une
gestion de blobs, un lecteur audio et leur part de quota `localStorage` ; ce qui
reste, c'est l'app Dictaphone de l'iPhone, qui le fait mieux. À reconsidérer si
le besoin se manifeste à l'usage, et pas avant.

**La prochaine étape est l'étape 3 du plan** : `repet_export.py` dans
`outil_edition`, avec ses tests — le premier maillon, et celui dont tout le reste
dépend. Rien à écrire côté navigateur avant qu'un `REPET.json` existe pour de
vrai.
