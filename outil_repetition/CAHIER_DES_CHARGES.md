# Cahier des charges — outil_repetition

> **Statut : décisions tranchées le 2026-08-03**, relevé en
> [§14](#14-décisions-validées). Ce document remplace le prompt initial
> `prompt-outil-repetition-theatre.md`. Il en conserve l'intention et la
> quasi-totalité des fonctionnalités, mais l'ajuste sur trois points :
> l'entrée n'est plus un format préparé à la main, la cible de déploiement
> devient **HTTPS + iPhone 15**, et l'existant est réécrit.
>
> L'[`ARCHITECTURE.md`](ARCHITECTURE.md) qui le réalise est rédigé et **reste à
> valider** : il révise le §11.1 ci-dessous (découpage en fichiers) et porte
> quatre décisions ouvertes. Aucun code avant cette validation, même discipline
> qu'[`outil_edition/`](../outil_edition/ARCHITECTURE.md).

---

## Table des matières

1. [Ce qui change par rapport au prompt initial](#1-ce-qui-change-par-rapport-au-prompt-initial)
2. [Place dans le dépôt](#2-place-dans-le-dépôt)
3. [L'entrée : `REPET.json`, produit par outil_edition](#3-lentrée--repetjson-produit-par-outil_edition)
4. [Contraintes iPhone 15](#4-contraintes-iphone-15)
5. [Modes de répétition](#5-modes-de-répétition)
6. [Masquage contextuel des scènes](#6-masquage-contextuel-des-scènes)
7. [Reconnaissance vocale](#7-reconnaissance-vocale)
8. [Suivi de progression](#8-suivi-de-progression)
9. [Navigation et confort](#9-navigation-et-confort)
10. [Persistance et sauvegarde](#10-persistance-et-sauvegarde)
11. [Écarts assumés par rapport au prompt initial](#11-écarts-assumés-par-rapport-au-prompt-initial)
12. [Ce qu'il faut reprendre et ce qu'il faut jeter de l'existant](#12-ce-quil-faut-reprendre-et-ce-quil-faut-jeter-de-lexistant)
13. [Plan de livraison](#13-plan-de-livraison)
14. [Décisions validées](#14-décisions-validées)

---

## 1. Ce qui change par rapport au prompt initial

| Sujet | Prompt initial | Ce cahier des charges | Motif |
|---|---|---|---|
| **Entrée** | fichier `.txt` avec `#ROLE:` / `#SCENE:` / `PERSONNAGE:` préparé à la main | `<Livre>_REPET.json` émis gratuitement par l'étape 4 d'`outil_edition` | le pipeline calcule déjà cette structure ; la refaire à la main serait un travail récurrent et une seconde source de vérité |
| **Ligne `#ROLE`** | déclarée dans le fichier | supprimée — les personnages sont dans le JSON, le rôle joué se choisit dans l'interface | un fichier généré n'a pas à porter une préférence de session |
| **Parsing** | à écrire, strict, avec erreurs par numéro de ligne | **aucun parsing** — lecture d'un JSON versionné | supprime la classe d'erreurs entière |
| **Déploiement** | fichier HTML ouvert localement | **GitHub Pages en HTTPS**, ajouté à l'écran d'accueil de l'iPhone | le micro est interdit depuis `file://` sur Safari (§4.1) |
| **Nombre de fichiers** | un seul HTML autonome | 4 fichiers (§11.1) | un ajout à l'écran d'accueil et un fonctionnement hors ligne exigent un manifeste et un service worker |
| **Reconnaissance vocale** | écoute continue, comparaison automatique | une réplique à la fois, déclenchée au doigt, **jamais sur le chemin critique** (§7) | l'API iOS est capricieuse et exige le réseau : elle ne peut pas être le pivot de l'outil |
| **Persistance** | `localStorage` | `localStorage` **+ export JSON explicite**, avec avertissement d'éviction | Safari purge le stockage après 7 jours d'inactivité, écran d'accueil compris depuis iOS 17.4 (§4.2) |
| **Pièce embarquée** | — | **retirée du dépôt** | *La Toile d'araignée* est sous droits ; le dépôt est public et `.gitignore` exclut déjà `exemples/` pour ce motif |

Tout le reste du prompt initial est conservé : les cinq modes de masquage, la
mise en valeur du top, le masquage contextuel des scènes, le suivi de
progression par personnage, le spot check, les annotations, le sommaire, la
recherche, les marque-pages, le défilement automatique, le mode sombre.

---

## 2. Place dans le dépôt

`outil_repetition/` est un sous-projet indépendant, au même titre
qu'`outil_edition/` et `outil_coupes/`. Une seule dépendance, et elle est
**unidirectionnelle** : il consomme un fichier produit par `outil_edition`,
sans jamais l'appeler.

```
Pièce.pdf ──[outil_edition]──▶ Pièce.docx          (édition papier)
                           └──▶ Pièce_REPET.json   (répétition)  ◀── NOUVEAU
                                      │
                                      ▼
                            [outil_repetition]  ← page web, iPhone / navigateur
```

Conséquence de cette direction unique : `outil_edition` reste utilisable sans
rien savoir de l'outil de répétition, et l'outil de répétition fonctionne avec
n'importe quel JSON conforme au schéma, y compris écrit à la main pour un essai.

---

## 3. L'entrée : `REPET.json`, produit par outil_edition

### 3.1 Une sortie de plus à l'étape 4, gratuite

L'étape 4 d'`outil_edition` construit déjà, pour générer le DOCX, un
`IndexStructure` qui tranche pour chaque ligne entre **acte, scène,
distribution, personnage, lieu, didascalie et réplique**
(voir [`ARCHITECTURE.md` §9.1](../outil_edition/ARCHITECTURE.md)). Cette
information est aujourd'hui consommée puis jetée.

Un **nouveau module `repet_export.py`**, frère de `docx_export.py`, l'écrit dans
`<Livre>_REPET.json`. Il ne duplique aucune logique : il rappelle
`blocks.construire_index_structure()`, qui existe déjà et qui est pur. Le second
parcours du document est local et gratuit — quelques millisecondes — et ce prix
achète la responsabilité unique de chaque module (§4 de l'ARCHITECTURE
d'`outil_edition`) : `docx_export.py` continue de n'exporter que du DOCX.

Propriétés à respecter :

- **aucune IA, aucun appel API, aucun coût** — comme le DOCX, c'est du parsing
  déterministe ;
- **idempotent** : deux exécutions sur le même `EDIT.txt` produisent le même
  fichier, aux champs de date près ;
- **pas de nouvelle logique de classification** : le JSON expose l'index
  existant, il ne le recalcule pas. Si `**LA VOIX**` est mal classé, il l'est
  identiquement dans les deux sorties, et `TITRES_ACTE_FORCES` corrige les deux
  d'un coup ;
- **le champ `confiance` est transmis**, afin que l'outil de répétition puisse
  signaler une structure douteuse au lieu de la présenter comme certaine.

### 3.2 Schéma

```json
{
  "schema": "repetition/1",
  "piece": "Le Malentendu",
  "genere_le": "2026-08-03T14:32:10",
  "outil": "outil_edition 1.0 — étape 4",
  "avertissements": ["classement incertain : LA VOIX"],

  "personnages": [
    { "nom": "JAN", "repliques": 84, "mots": 3120 },
    { "nom": "MARTHA", "repliques": 79, "mots": 2870 }
  ],

  "unites": [
    {
      "id": "u001",
      "acte": "ACTE PREMIER",
      "scene": "SCÈNE 2",
      "implicite": false,
      "personnages": ["JAN", "MARTHA"],
      "elements": [
        { "type": "lieu",        "texte": "Une auberge. Le soir." },
        { "type": "didascalie",  "texte": "Pause." },
        { "type": "replique",    "id": "r_8f3a1c",
          "personnage": "JAN",
          "texte": "Je t'attendais depuis une heure.",
          "didascalies_internes": [{ "avant_mot": 2, "texte": "elle se lève" }],
          "vers": false }
      ]
    }
  ]
}
```

Quatre points de conception portés par ce schéma.

**L'unité jouable, et non l'acte, est l'élément de premier niveau.** Une liste
plate d'unités couvre les trois cas réels sans arborescence conditionnelle :
une pièce classique (`acte` et `scene` renseignés), une pièce contemporaine
sans titres de scène (`scene: null`, une unité par séparateur `***`, avec
`implicite: true` pour ne pas afficher de titre fantôme), et un texte d'un seul
tenant (une unité, les deux champs nuls). C'est aussi exactement le grain dont
§6 a besoin pour replier une scène.

**`personnages` par unité est précalculé.** C'est ce qui permet de décider
qu'une scène est « la mienne » sans la parcourir, donc de replier tout un acte
instantanément sur un iPhone.

**L'`id` d'une réplique est dérivé de son contenu**, non de sa position :
empreinte courte de `personnage + "|" + texte normalisé`. Un `EDIT.txt` relu et
corrigé décale toutes les positions ; des identifiants positionnels feraient
alors migrer silencieusement ma progression d'une réplique vers sa voisine. Avec
une empreinte de contenu, la dégradation devient juste : une réplique dont le
texte a changé perd son statut — ce qui est correct, il faut la réapprendre —
et toutes les autres le conservent. Les collisions (deux répliques identiques du
même personnage, « Oui. ») sont désambiguïsées par un suffixe d'occurrence.

**`vers` reprend la distinction déjà faite par le prompt d'édition** entre
retour à la ligne mécanique et retour voulu (commit `3465015`). Un vers ne doit
pas être reflué comme de la prose, et l'amorce de §5 se compte différemment.

### 3.3 Charger une pièce dans l'outil

Trois voies, par ordre de confort sur iPhone :

1. **Coller** le contenu du JSON dans une zone de texte. Marche partout,
   y compris depuis un JSON reçu par message.
2. **Importer un fichier** (`<input type="file" accept=".json,application/json">`)
   — depuis l'app Fichiers ou iCloud Drive sur iPhone.
3. **Déposer le JSON dans le dossier de la page** et le charger par `fetch`.
   Réservé à l'usage local : ce dossier **ne doit jamais être versionné**
   (§11.2).

Après chargement, le JSON est stocké dans `localStorage` et l'écran d'accueil
liste les pièces disponibles. **Aucune pièce n'est embarquée dans le code.**

Validation à l'entrée : `schema` reconnu, `unites` non vide, chaque réplique
porte `personnage`, `texte` et `id`. En cas d'échec, message explicite nommant
le champ fautif — et rien n'est chargé. Un `schema` de version supérieure est
refusé plutôt qu'interprété au mieux.

---

## 4. Contraintes iPhone 15

C'est la section la plus structurante, et elle était absente du prompt initial.
L'iPhone est le support principal : ce qui n'y marche pas n'existe pas.

### 4.1 HTTPS obligatoire, donc GitHub Pages

Safari place le micro derrière un *secure context* : `SpeechRecognition` et
`getUserMedia` ne fonctionnent qu'en **HTTPS** ou sur `localhost`. Un HTML ouvert
depuis l'app Fichiers (`file://`) **n'obtiendra jamais le micro sur iPhone**. Le
« fichier unique autonome » du prompt initial est donc incompatible avec sa
propre section 5.

Le dépôt étant public, la solution est GitHub Pages :

```
https://elyeskaak.github.io/texte_troupe_theatre/outil_repetition/
```

Puis **Partager → Sur l'écran d'accueil** : l'outil s'ouvre en plein écran, sans
barre Safari, et se lance comme une application.

Le code est public, **les textes ne le sont pas** : ils sont chargés sur
l'appareil et vivent dans son navigateur. C'est ce qui rend le déploiement
compatible avec les droits d'auteur.

### 4.2 Le stockage iOS n'est pas fiable — il faut un export

Depuis iOS 13.4, Safari purge `localStorage`, IndexedDB et les service workers
après **7 jours sans interaction** avec le site. L'exemption dont bénéficiaient
les applications ajoutées à l'écran d'accueil **a été retirée** (changements liés
à iOS 17.4). Trois semaines sans répétition suffiraient donc à effacer toute la
progression.

Conséquences, non négociables :

- un bouton **« Exporter ma progression »** produisant un `.json`
  (téléchargement / feuille de partage iOS), et son import symétrique ;
- l'écran de bilan affiche **la date du dernier export** et alerte au-delà d'un
  seuil ;
- la progression est **une donnée d'agrément, jamais une donnée critique** : sa
  perte ne doit rien casser d'autre que l'historique.

À prévoir aussi : plafonner l'historique des scores vocaux (les *N* derniers par
réplique) pour rester loin du quota d'origine de Safari, et traiter
`QuotaExceededError` par un message clair — pas par un `catch` vide.

> **Le `catch` vide est le défaut exact de l'existant** : il masque une API
> absente et donne l'illusion d'une sauvegarde. Voir §12.

### 4.3 Reconnaissance vocale sur iOS : ce qu'il faut en attendre

`webkitSpeechRecognition` existe sur iOS depuis 14.5, mais :

- **elle exige le réseau** — la reconnaissance est distante. Dans des coulisses
  sans couverture, elle ne marchera pas ;
- l'écoute continue est peu fiable ; des rapports récurrents signalent une
  écoute qui ne s'arrête pas, ou un `onresult` qui ne se déclenche jamais ;
- **Siri interfère** : micro accordé, il faut souvent 2 à 3 secondes avant de
  parler, sinon le début est perdu ;
- chaque session veut un geste utilisateur.

D'où la règle de conception de §7 : **tout l'outil doit fonctionner hors ligne
et sans micro.** La voix est un supplément d'entraînement à la maison, pas le
mécanisme de l'outil.

### 4.4 Ergonomie tactile

| Point | Exigence |
|---|---|
| **Zoom** | retirer `maximum-scale=1, user-scalable=no` du viewport. Bloquer le pinch-zoom sur un outil de lecture de texte est un contresens — et le réglage de taille de police ne le remplace pas |
| **Encoches et barre d'accueil** | `viewport-fit=cover` + `env(safe-area-inset-*)`, sur les barres du haut **et** du bas |
| **Hauteur** | `100dvh`, jamais `100vh` : la barre Safari se replie au défilement |
| **Cibles** | 44 × 44 pt au minimum. Le bouton « révéler » doit être atteignable au pouce, une main, l'autre tenant le texte papier |
| **Survol** | aucune information portée par un `:hover` |
| **Polices** | pas de dépendance bloquante à un CDN. Les polices sont un agrément : replier sur les polices système (`-apple-system`, `ui-serif`) quand le réseau manque |
| **Veille écran** | Screen Wake Lock (Safari 16.4+) pendant une session, pour que l'écran ne s'éteigne pas en pleine réplique. Repli silencieux si indisponible |
| **Hors ligne** | service worker mettant en cache la coque de l'application. Un outil de coulisses doit s'ouvrir sans réseau |
| **Orientation** | portrait d'abord ; le paysage ne doit rien casser, sans être optimisé |

### 4.5 Comparaison de texte en français

La transcription iOS rend un texte **sans ponctuation**, avec des apostrophes
typographiques et des nombres parfois en chiffres. Une comparaison naïve
donnerait des scores absurdes. Normaliser des deux côtés avant de comparer :
casse, accents, apostrophes (`’` → `'`), ponctuation, espaces, tirets ; et
traiter les nombres écrits en chiffres comme leur forme en lettres. `lang` fixé
à `fr-FR`.

---

## 5. Modes de répétition

Basculables à tout moment, sans perdre sa place. Les cinq du prompt initial,
plus celui de l'existant qui mérite d'être gardé.

| Mode | Ce qui est visible de ma réplique |
|---|---|
| **Lecture complète** | tout |
| **Masquage** | rien, sous un rideau à toucher pour révéler |
| **Amorce seule** | les 3 premiers mots (réglable) |
| **Mots à trous** | le texte avec un pourcentage réglable de mots masqués, révélables un à un — *repris de l'existant* |
| **Acronyme géant** | uniquement la première lettre de chaque mot, ponctuation d'origine strictement conservée (ex. `A ?... O... C m...`) |
| **Récitation à l'aveugle** | rien, et rien d'autre à l'écran ; on récite, puis on vérifie |
| **Test du top** | seule la fin de la réplique précédente, rien de la mienne |

Dans tous les modes masqués, **une réplique cachée indique toujours qui parle**
(`JAN — masqué`) : je joue plusieurs rôles, et un bloc anonyme rendrait une
scène entre deux de mes personnages illisible.

### Comportement du mode « Acronyme géant »

Chaque mot de ma réplique est remplacé par sa **première lettre**, en respectant
la casse. Les signes de ponctuation, les apostrophes, les tirets, les espaces et
les retours à la ligne sont **conservés sans aucune modification**.

```
Ai-je ?... Oui... Comme moi...   →   A-j ?... O... C m...
Je ne crois pas qu'elle réponde. →   J n c p q'e r.
```

Quatre points de comportement, tous couverts par des tests :

- **La casse et les accents de l'initiale sont préservés** : « Être » donne
  « Ê », pas « E ».
- **L'apostrophe et le tiret bornent deux mots** : « qu'elle » donne « q'e », et
  « peut-être » donne « p-ê ». C'est la seule lecture cohérente de la règle —
  conserver l'apostrophe tout en ne gardant qu'une initiale pour l'ensemble
  donnerait « q' », qui laisse une apostrophe pendante. L'élision est de surcroît
  un excellent rappel.
- **Les espaces ne sont pas normalisés.** Le rythme visuel de la réplique est
  précisément ce qui la rappelle : le réduire serait retirer l'indice.
- **Les chiffres sont conservés entiers**, faute d'initiale : « 20 ans » donne
  « 20 a ». Le cas est rare, l'édition imprimée écrivant ses nombres en lettres.

**Pourquoi ce mode est utile là où les autres ne le sont pas.** Il ne cache pas
une *part* du texte, il en garde le squelette entier. C'est donc un mode de
**révision** et non d'apprentissage : on l'emploie quand la réplique est presque
sue et qu'il ne manque que le déclic. La ponctuation intacte porte le phrasé —
les silences, les questions, les suspensions — c'est-à-dire ce qu'une réplique
masquée fait perdre en premier.

**Mise en valeur du top.** La dernière réplique de l'autre personnage juste avant
la mienne est encadrée et détachée, avec l'option de n'en montrer que les 3 à 5
derniers mots. En mode « test du top », c'est le seul élément affiché.

---

## 6. Masquage contextuel des scènes

Deux réglages indépendants et combinables, exactement comme au prompt initial :

- **Mes scènes uniquement** : les unités où aucun de mes personnages n'apparaît
  sont repliées sur un titre (`SCÈNE 4 — absent`), dépliable au doigt. Le test
  porte sur **l'ensemble des personnages que je joue dans la pièce**, jamais sur
  le seul rôle actif de la session.
- **Répétition active** : dans mes scènes, le texte des autres reste visible et
  seules mes répliques sont masquées selon le mode de §5.

Distinction à ne pas confondre, et déjà énoncée dans le prompt initial :
le **rôle actif de la session** décide *ce qui est masqué* ; l'**ensemble de mes
rôles** décide *ce qui est une de mes scènes*.

---

## 7. Reconnaissance vocale

Repensée autour de la fragilité constatée en §4.3.

**Le principe : le micro ne bloque jamais rien.** La progression s'obtient au
doigt (« su » / « à revoir ») ; le micro ne fait que proposer un score. Un
`onresult` qui ne vient jamais doit rester un non-événement.

Déroulé pour une réplique :

1. Bouton micro **sur la réplique**, jamais global : une réplique à la fois.
2. Appui → demande de permission → **décompte visible de 2 secondes** avant
   l'écoute effective (contourne le démarrage lent de §4.3).
3. Écoute non continue, arrêt explicite au doigt, plus un délai de garde.
4. Comparaison mot à mot après normalisation (§4.5) : mots justes en vert,
   oubliés en gris barré, substitués ou ajoutés en orange, et un pourcentage de
   fidélité.
5. Le score s'ajoute à l'historique de la réplique **pour le personnage actif**.

Replis, dans l'ordre :

| Situation | Comportement |
|---|---|
| API absente (navigateur non compatible) | le bouton micro n'apparaît pas ; message une seule fois, discret |
| Permission refusée | explication de la marche à suivre dans Réglages iOS |
| Réseau absent | message explicite « la reconnaissance vocale a besoin du réseau » |
| Reconnaissance muette ou interrompue | abandon silencieux après le délai de garde ; **aucun score enregistré**, aucune erreur bruyante |

Dans tous ces cas, le repli est **le même et il suffit** : je récite, puis je
touche « su » ou « à revoir ». C'est déjà le chemin principal de §8.

**Pas de repli par enregistrement audio** (retiré du périmètre le 2026-08-03).
Le prompt initial en prévoyait un « pour réécoute ». Il aurait coûté
`MediaRecorder`, une gestion de blobs, un lecteur et un quota de stockage — pour
un usage que l'app Dictaphone de l'iPhone rend déjà, mieux, et sans rien à écrire.
À reconsidérer seulement si le besoin se manifeste à l'usage.

---

## 8. Suivi de progression

Inchangé par rapport au prompt initial, avec une précision sur les identifiants.

- Statut par réplique et par scène : **à apprendre / en cours / maîtrisée**.
- **Suivi séparé par personnage.** Si je joue Henry et Oliver, chacun a ses
  statuts et son historique : rien n'est partagé.
- Vue d'ensemble en code couleur, scène par scène, filtrable par personnage ou
  en vue combinée.
- Historique des scores vocaux par réplique dans le temps (plafonné, §4.2).
- **Spot check** : tirage aléatoire d'une réplique parmi les scènes marquées
  « maîtrisée », pour le ou les personnages actifs.

Les statuts sont indexés par l'`id` de contenu de §3.2, ce qui les rend robustes
à une réédition de la pièce.

---

## 9. Navigation et confort

Repris tel quel du prompt initial : sommaire cliquable par acte et scène,
recherche dans le texte, marque-pages, défilement automatique à vitesse réglable,
taille de police, mode sombre, annotations libres par réplique sans jamais
toucher au texte de l'auteur.

Deux ajouts dictés par l'usage sur iPhone :

- **Reprendre où j'en étais** : la position et le mode sont restaurés à
  l'ouverture. Une session de répétition s'interrompt sans arrêt.
- **Aller à la réplique suivante / précédente** : gros boutons de saut de top à
  top, déjà présents dans l'existant et à conserver.

Le mode sombre est le défaut : on répète le soir, et l'écran d'un iPhone est la
seule source de lumière en coulisses.

---

## 10. Persistance et sauvegarde

`localStorage` uniquement, sans backend, comme au prompt initial — mais avec des
clés séparées, afin qu'écrire un statut ne réécrive pas la pièce entière à chaque
tape :

```
repet:v1:index                        liste des pièces (id, titre, date)
repet:v1:piece:<id>                   le REPET.json, immuable
repet:v1:progres:<id>:<PERSONNAGE>    statuts et historique
repet:v1:annotations:<id>             annotations et marque-pages
repet:v1:reglages                     mode, taille de police, vitesse
repet:v1:session                      dernière position
```

`piece:<id>` est écrit une fois puis jamais modifié : les annotations vivent à
part, ce qui permet de recharger une pièce rééditée **sans perdre ses notes**.

Export et import portent sur tout sauf les pièces — le JSON de la pièce est
reproductible depuis `outil_edition`, la progression non.

---

## 11. Écarts assumés par rapport au prompt initial

### 11.1 Quatre fichiers, et non un seul

```
outil_repetition/
├── index.html                  interface + logique (toujours sans dépendance)
├── manifest.webmanifest        nom, icône, plein écran à l'écran d'accueil
├── sw.js                       service worker : ouverture hors ligne
└── icone.svg                   icône d'écran d'accueil
```

Le « fichier unique » du prompt visait l'absence d'installation, et cet objectif
est atteint : on ouvre une URL. Mais un ajout à l'écran d'accueil et un
fonctionnement hors ligne ne se font pas dans un fichier unique. Toute la logique
reste dans `index.html`, sans dépendance externe obligatoire — l'esprit de la
contrainte est tenu.

À noter : le service worker fait partie du stockage purgé par les 7 jours de
§4.2. Il se réinstalle à la visite suivante ; le premier chargement après une
purge exige donc du réseau.

### 11.2 Le dossier des pièces n'est pas versionné

Un `outil_repetition/pieces/` peut servir localement (§3.3, voie 3). Il rejoint
`.gitignore` au même titre qu'`exemples/`. Publier un `REPET.json` reviendrait à
publier le texte intégral d'une œuvre sous droits sur une URL indexable.

### 11.3 La pièce embarquée est retirée

L'existant contient les 188 Ko de *La Toile d'araignée* d'Agatha Christie, en
base64 dans le HTML, versionnés et poussés sur un dépôt public. C'est à retirer,
et ce retrait est un préalable, pas une finition.

**Décision : réécriture d'historique.** Un simple commit de suppression
laisserait le texte accessible à quiconque connaît un ancien SHA. Le blob est
donc purgé de tous les commits avec `git filter-repo`, suivi d'un
`push --force`. Le dépôt n'ayant qu'un auteur, le coût côté collaboration est
nul.

Deux réserves à connaître avant de lancer la commande :

- GitHub conserve un temps les commits devenus inatteignables — ils restent
  consultables par leur SHA. Une purge réellement complète demande de **demander
  un `gc` au support GitHub** après le force-push ;
- si des clones ou des forks existent, ils gardent le blob. À vérifier avant.

Les commandes seront préparées ici et lancées par toi : un `push --force` sur
`main` n'est pas une opération à déléguer.

---

## 12. Ce qu'il faut reprendre et ce qu'il faut jeter de l'existant

`repetition-theatre.html` (891 lignes) couvre environ un quart de ce cahier des
charges. Il est réécrit, mais il n'est pas sans valeur.

**À reprendre :**

- le **parti graphique** — thème scène et rideau, ocre sur bordeaux sombre,
  colonne de 520 px centrée, `100dvh`, `viewport-fit=cover`. C'est déjà
  mobile-first et c'est réussi ;
- l'**animation de révélation** au doigt (`clip-path` en cercle depuis le point
  touché) ;
- le **mode mots à trous** avec son curseur de difficulté, absent du prompt
  initial et bon à garder (§5) ;
- la **sélection multi-personnages** par pastilles, et le rappel « Henry & Oliver »
  en tête d'écran ;
- les **boutons de saut de top à top** et la barre de progression au défilement.

**À jeter, et pourquoi :**

| Élément | Motif |
|---|---|
| `window.storage.get/set/delete` | **cette API n'existe pas dans un navigateur.** C'est un vestige de bac à sable Artifacts. Les trois helpers l'entourent d'un `try/catch` qui retourne `null` : dans Safari, chaque appel échoue en silence. Le bouton « Sauvegarder » ne sauvegarde rien et la liste des pièces enregistrées ne s'affiche jamais. À remplacer par `localStorage` (§10) — avec des erreurs **visibles** |
| `parseScript()` | parsing heuristique — précisément ce que le prompt initial voulait bannir. Remplacé par la lecture du JSON de §3 |
| `if(current){ ... }` / `// else: stray preamble text, ignored` | toute ligne non reconnue est **jetée en silence**, ou concaténée à la réplique précédente. Une réplique perdue est indétectable |
| `pageNumRe` | supprime silencieusement toute ligne de 1 à 4 chiffres. Une réplique réduite à `1789` disparaît |
| `CHARACTER_STOPLIST`, `key.split(' ').length > 3` | rustines contre les erreurs du parser. Sans parser, plus de rustines |
| `SCRIPT_B64_PARTS` | §11.3 |
| `maximum-scale=1, user-scalable=no` | §4.4 |
| polices Google Fonts en dépendance simple | §4.4 : prévoir le repli système |
| `whoProg` calculé au défilement | mesure une position dans la page, pas un apprentissage. Le compteur doit refléter les statuts de §8 |

---

## 13. Plan de livraison

Un commit par étape, comme pour `outil_edition`.

| # | Livrable | Vérifiable par |
|---|---|---|
| 1 | Retrait de la pièce embarquée + `.gitignore`, puis purge de l'historique (§11.3) | `git log -p` ne fait plus apparaître le blob |
| 2 | `ARCHITECTURE.md` d'`outil_repetition` | relecture et validation |
| 3 | `repet_export.py` dans `outil_edition` (§3) + tests | tests unitaires du schéma sur les pièces d'exemple |
| 4 | Coque : chargement d'une pièce, `localStorage`, écran de choix du rôle | une pièce chargée survit à une fermeture de Safari |
| 5 | Écran de répétition : les 7 modes, le top, le repli de scènes | usage réel sur iPhone 15 |
| 6 | Suivi de progression, bilan, spot check, export / import | export puis import restitue à l'identique |
| 7 | Confort : sommaire, recherche, marque-pages, annotations, défilement | — |
| 8 | Micro et replis (§7) | testé sur iPhone 15 en HTTPS, **et** avion activé |
| 9 | `manifest` + service worker + GitHub Pages | ouverture hors ligne depuis l'écran d'accueil |
| 10 | `README.md` du sous-projet, entrée dans le README racine | — |

Les étapes 4 à 7 sont utilisables sans micro et sans réseau : l'outil est
utilisable dès l'étape 5.

---

## 14. Décisions validées

Tranchées le **2026-08-03**. Aucune décision ne reste ouverte à ce stade.

| # | Sujet | Décision | Conséquence dans ce document |
|---|---|---|---|
| 1 | Historique git | **Réécriture** : `git filter-repo` + `push --force`, plus une demande de `gc` au support GitHub | §11.3, étape 1 du plan |
| 2 | Module d'export | **`repet_export.py` distinct**, rappelant `construire_index_structure()` | §3.1, étape 3 du plan |
| 3 | Publication | **GitHub Pages sur `texte_troupe_theatre`**, sous `/outil_repetition/` | §4.1, §11.1 |
| 4 | Portée du JSON | **Une pièce = un fichier**, sans découpage par acte | §3.2 |

Les trois arbitrages qui ont façonné le document lui-même — entrée par
`REPET.json` plutôt que format manuel, déploiement HTTPS plutôt que fichier
local, réécriture plutôt qu'extension de l'existant — ont été validés en amont
et sont relevés en [§1](#1-ce-qui-change-par-rapport-au-prompt-initial).

**La prochaine décision est l'`ARCHITECTURE.md`**, à rédiger avant tout code
(étape 2 du plan). Elle aura à trancher au moins : la structure du rendu
(re-rendu complet de la scène courante, ou mise à jour ciblée des blocs
concernés — l'existant re-rend tout, ce qui deviendra visible sur 300 pages), et
la façon d'exposer un `avertissements` non vide sans alarmer inutilement.

---

### Références

- Web Speech API et *secure context* : [MDN](https://developer.mozilla.org/docs/Web/API/Web_Speech_API),
  [Apple Developer Forums](https://developer.apple.com/forums/thread/748048)
- Purge du stockage après 7 jours et fin de l'exemption pour l'écran d'accueil :
  [WebKit / ITP](https://support.didomi.io/apple-adds-a-7-day-cap-on-all-script-writable-storage),
  [analyse des changements iOS 17.4](https://blog.tomayac.com/2024/02/28/so-what-exactly-did-apple-break-in-the-eu/)
