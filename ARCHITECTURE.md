# ARCHITECTURE — Pipeline d'édition de pièces de théâtre

> **Statut : proposition soumise à validation.**
> Aucun code métier n'est écrit avant approbation de ce document.
> La section [§17](#17-points-à-valider-avant-écriture-du-code) liste les
> décisions sur lesquelles j'attends une confirmation explicite.

---

## Table des matières

1. [Objectif et principes directeurs](#1-objectif-et-principes-directeurs)
2. [Vue d'ensemble du pipeline](#2-vue-densemble-du-pipeline)
3. [Arborescence du projet](#3-arborescence-du-projet)
4. [Rôle de chaque module](#4-rôle-de-chaque-module)
5. [Formats des fichiers intermédiaires](#5-formats-des-fichiers-intermédiaires)
6. [Flux des données, étape par étape](#6-flux-des-données-étape-par-étape)
7. [Le patron de reprise : l'invariant d'idempotence](#7-le-patron-de-reprise--linvariant-didempotence)
8. [La convention typographique : le contrat entre les étapes](#8-la-convention-typographique--le-contrat-entre-les-étapes)
9. [Problèmes délicats et leur résolution](#9-problèmes-délicats-et-leur-résolution)
10. [Choix techniques et justifications](#10-choix-techniques-et-justifications)
11. [Configuration](#11-configuration)
12. [Journalisation](#12-journalisation)
13. [Gestion des erreurs](#13-gestion-des-erreurs)
14. [Écarts assumés par rapport à l'arborescence demandée](#14-écarts-assumés-par-rapport-à-larborescence-demandée)
15. [Conventions de code](#15-conventions-de-code)
16. [Plan de livraison](#16-plan-de-livraison)
17. [Points à valider avant écriture du code](#17-points-à-valider-avant-écriture-du-code)

---

## 1. Objectif et principes directeurs

Transformer des scans PDF de pièces de théâtre en une édition propre au format
DOCX, dans Google Colab, de façon robuste à l'échelle d'un livre entier
(150 à 400 pages).

Cinq principes gouvernent chaque décision de ce document.

### P1 — Fidélité absolue au texte de l'auteur

Le pipeline est un **outil d'édition**, jamais un outil de réécriture. Toute
ambiguïté se tranche en faveur de la conservation. Ce principe est déjà inscrit
dans les prompts du prototype existant et il est renforcé ici par des contrôles
mécaniques (§9.4) qui ne dépendent pas de la bonne volonté du modèle.

### P2 — Indépendance stricte des étapes

Chaque étape lit des fichiers et écrit des fichiers. Aucune étape ne détient
d'état en mémoire dont une autre dépendrait. Conséquence directe : on peut
relancer l'étape 3 six mois plus tard, ou refaire seulement l'étape 4 après
avoir changé une marge, sans jamais repayer un appel API.

### P3 — Idempotence et reprise sur interruption

Colab coupe les sessions. C'est une certitude, pas un risque. Le pipeline est
donc conçu autour d'un invariant formel décrit en [§7](#7-le-patron-de-reprise--linvariant-didempotence) :
**une unité de travail terminée n'est jamais recalculée, et une unité
interrompue n'est jamais considérée comme terminée.**

### P4 — Séparation logique métier / interface

100 % du code métier vit dans `theatre_editor/`. Les notebooks ne contiennent
que : montage du Drive, installation des dépendances, surcharges de
configuration, un appel de fonction, affichage du résumé. Un notebook ne doit
jamais dépasser une poignée de lignes par cellule.

### P5 — Aucun nombre magique, aucun prompt en dur

Toutes les constantes dans `config.py`. Tous les prompts dans `prompts/*.md`.
Le corollaire important : **on peut faire évoluer la qualité éditoriale du
résultat sans toucher une ligne de Python.**

---

## 2. Vue d'ensemble du pipeline

```
                    ┌─────────────────────────────────────────┐
                    │  Google Drive : DOSSIER_DRIVE           │
                    └─────────────────────────────────────────┘

   Pièce.pdf
      │
      │  ÉTAPE 1 — OCR Vision                    notebooks/01_OCR.ipynb
      │  ┌──────────────────────────────────────────────────────────┐
      │  │ PyMuPDF rasterise page → PNG → base64                    │
      │  │ Responses API (vision) → texte brut, page par page        │
      │  │ Écriture immédiate : _OCR_pages/page_0001.txt + .json     │
      │  │ Assemblage final                                          │
      │  └──────────────────────────────────────────────────────────┘
      ▼
   Pièce_OCR.txt                    ← texte brut, marqueurs [PAGE X]
      │
      │  ÉTAPE 2a — Édition par blocs             notebooks/02_Edition.ipynb
      │  ┌──────────────────────────────────────────────────────────┐
      │  │ Découpage en blocs de PAGES_PAR_BLOC pages                │
      │  │ Responses API → correction OCR seule + mise en forme      │
      │  │ Écriture immédiate : _EDIT_blocs/bloc_0001.txt + .json    │
      │  └──────────────────────────────────────────────────────────┘
      │
      │  ÉTAPE 2b — Passe de raccord
      │  ┌──────────────────────────────────────────────────────────┐
      │  │ Pour chaque jonction N/N+1 :                              │
      │  │   50 dernières lignes de N  +  50 premières de N+1         │
      │  │ Responses API → ressoudure uniquement                     │
      │  │ Écriture immédiate : _EDIT_raccords/                       │
      │  └──────────────────────────────────────────────────────────┘
      ▼
   Pièce_EDIT.txt                   ← texte propre, convention typographique
      │
      │  ÉTAPE 3 — Contrôle qualité               notebooks/03_Verification.ipynb
      │  ┌──────────────────────────────────────────────────────────┐
      │  │ Contrôles mécaniques (sans IA)  ──┐                       │
      │  │ Comparaison OCR/EDIT par bloc (IA) ┴→ constats fusionnés  │
      │  │ Le modèle ne modifie JAMAIS le texte                      │
      │  └──────────────────────────────────────────────────────────┘
      ▼
   Pièce_REPORT.txt                 ← diagnostic, lecture humaine
      │
      │  ÉTAPE 4 — Génération DOCX                notebooks/04_DOCX.ipynb
      │  ┌──────────────────────────────────────────────────────────┐
      │  │ AUCUNE IA — parsing déterministe + python-docx            │
      │  └──────────────────────────────────────────────────────────┘
      ▼
   Pièce.docx
```

Le point à retenir : **l'étape 3 est un diagnostic, pas une correction.** Elle
ne se trouve pas sur le chemin critique entre `EDIT.txt` et le DOCX. Si le
rapport révèle un problème, on corrige soit un prompt puis on relance l'étape 2
sur les blocs concernés, soit `EDIT.txt` à la main. Cela évite toute boucle de
réécriture automatique, qui serait la porte ouverte à la violation de P1.

---

## 3. Arborescence du projet

### 3.1 Le dépôt (versionné dans git)

```
Théâtre/
├── ARCHITECTURE.md                  ← ce document
├── README.md                        ← démarrage rapide, 5 minutes
├── requirements.txt                 ← dépendances épinglées
├── .gitignore                       ← exclut PDF, sorties, secrets
├── .gitattributes                   ← force LF (projet exécuté sous Linux)
│
├── theatre_editor/                  ← TOUT le code métier
│   ├── __init__.py                  ← version, exports publics
│   ├── config.py                    ← toutes les constantes
│   │
│   ├── prompts/
│   │   ├── prompt_ocr.md
│   │   ├── prompt_edition.md        ← repris du prototype
│   │   ├── prompt_raccord.md        ← repris du prototype
│   │   └── prompt_validation.md
│   │
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── io.py                    ← système de fichiers, chemins, reprise
│   │   ├── blocks.py                ← logique texte pure (0 I/O, 0 API)
│   │   ├── logging.py               ← console + journaux JSON
│   │   └── api.py                   ← ⚠ AJOUT — client Responses + retry
│   │
│   ├── ocr.py                       ← étape 1
│   ├── edition.py                   ← étapes 2a + 2b
│   ├── validation.py                ← étape 3
│   ├── docx_export.py               ← étape 4
│   └── main.py                      ← orchestration CLI
│
├── notebooks/
│   ├── 01_OCR.ipynb
│   ├── 02_Edition.ipynb
│   ├── 03_Verification.ipynb
│   └── 04_DOCX.ipynb
│
├── tests/                           ← ⚠ AJOUT — sans API ni Drive
│   ├── test_blocks.py
│   └── test_docx_export.py
│
└── archive/
    └── Édition_OCR.ipynb            ← prototype d'origine, conservé
```

Les deux `⚠ AJOUT` sont justifiés en [§14](#14-écarts-assumés-par-rapport-à-larborescence-demandée).

### 3.2 Le dossier de travail (sur Google Drive, non versionné)

Pour un livre nommé `Le Malentendu`, `DOSSIER_DRIVE` contient :

```
Troupe 122 - 2026-27/
├── Le Malentendu.pdf                     ← ENTRÉE (fournie par vous)
│
├── Le Malentendu_OCR_pages/              ← cache étape 1
│   ├── page_0001.txt
│   ├── page_0001.json
│   ├── page_0002.txt
│   └── page_0002.json
├── Le Malentendu_OCR.txt                 ← SORTIE étape 1
│
├── Le Malentendu_EDIT_blocs/             ← cache étape 2a
│   ├── bloc_0001.txt
│   └── bloc_0001.json
├── Le Malentendu_EDIT_raccords/          ← cache étape 2b
│   ├── bloc_0001.txt
│   └── raccord_0001.json
├── Le Malentendu_EDIT.txt                ← SORTIE étape 2
│
├── Le Malentendu_REPORT_blocs/           ← cache étape 3
│   ├── bloc_0001.txt
│   └── bloc_0001.json
├── Le Malentendu_REPORT.txt              ← SORTIE étape 3
│
├── Le Malentendu.docx                    ← SORTIE étape 4
│
├── journal_ocr.json
├── journal_edition.json
├── journal_validation.json
└── journal_docx.json
```

**Le nom du livre est la clé de voûte.** Il est dérivé une seule fois du nom du
PDF (`Le Malentendu.pdf` → `Le Malentendu`) et tous les autres chemins en
découlent mécaniquement, via une unique fonction `resoudre_chemins(nom_livre)`.
Aucun chemin n'est construit ailleurs dans le code. Conséquence : plusieurs
pièces cohabitent sans collision dans le même dossier, et le pipeline traite un
dossier entier en boucle.

---

## 4. Rôle de chaque module

| Module | Responsabilité unique | Dépend de | Appelle l'API ? | Touche le disque ? |
|---|---|---|---|---|
| `config.py` | Constantes. Zéro logique. | — | non | non |
| `utils/io.py` | Chemins, lecture/écriture atomique, sidecars, scan du Drive | `config` | non | **oui** |
| `utils/blocks.py` | Découpage, fenêtrage, classification de lignes, contrôles | `config` | non | non |
| `utils/logging.py` | Affichage console + écriture des journaux | `config`, `io` | non | oui |
| `utils/api.py` | Client OpenAI, retry, extraction de texte, chronométrage | `config`, `logging` | **oui** | non |
| `ocr.py` | Étape 1 : PDF → `OCR.txt` | tout `utils` | oui | oui |
| `edition.py` | Étapes 2a/2b : `OCR.txt` → `EDIT.txt` | tout `utils` | oui | oui |
| `validation.py` | Étape 3 : → `REPORT.txt` | tout `utils` | oui | oui |
| `docx_export.py` | Étape 4 : `EDIT.txt` → `.docx` | `config`, `io`, `blocks` | **non** | oui |
| `main.py` | Orchestration, CLI, sélection d'étape | tous | — | — |

Deux invariants de conception se lisent dans ce tableau :

- **`blocks.py` est pur.** Aucune I/O, aucun appel réseau, aucune horloge. C'est
  ce qui rend l'ensemble testable sans clé API ni Drive monté (`tests/test_blocks.py`).
- **`docx_export.py` n'appelle jamais l'API.** Exigence explicite de votre
  cahier des charges, garantie par construction : le module n'importe même pas
  `utils/api.py`.

### 4.1 Détail des fonctions publiques prévues

#### `utils/io.py`

```python
def resoudre_chemins(nom_livre: str) -> CheminsLivre
    """Construit tous les chemins dérivés d'un nom de livre."""

def ecrire_texte_atomique(chemin: Path, contenu: str) -> None
    """Écrit via un fichier temporaire puis os.replace (jamais de fichier
    partiel visible, même si Colab coupe pendant l'écriture)."""

def lire_texte(chemin: Path) -> str
    """Lecture UTF-8 avec repli utf-8-sig (BOM)."""

def charger_prompt(nom: str) -> str
    """Charge prompts/<nom>.md, mis en cache. Erreur claire si absent."""

def ecrire_sidecar(chemin_json: Path, donnees: dict) -> None
def lire_sidecar(chemin_json: Path) -> dict | None

def unite_terminee(chemin_json: Path) -> bool
    """Cœur de la reprise : True seulement si le sidecar existe ET
    contient statut == "termine"."""

def lister_pdf(dossier: Path) -> list[Path]
def lister_fichiers_ocr(dossier: Path) -> list[Path]

def charger_cle_api() -> str
    """Colab userdata, puis variable d'environnement OPENAI_API_KEY.
    Message d'erreur explicite si aucune des deux."""
```

#### `utils/blocks.py`

```python
def decouper_en_pages(texte: str) -> list[str]
def former_blocs(pages: list[str], pages_par_bloc: int) -> list[Bloc]
def fenetre_fin(texte: str, n_lignes: int) -> tuple[str, str]      # (préfixe, extrait)
def fenetre_debut(texte: str, n_lignes: int) -> tuple[str, str]    # (extrait, suffixe)
def nettoyer_enveloppe(texte: str) -> str
def verifier_sortie(source: str, sortie: str) -> list[str]         # avertissements
def classifier_ligne(ligne: str, noms_personnages: set[str]) -> TypeLigne
def recenser_personnages(texte: str) -> set[str]
def decouper_en_runs(ligne: str) -> list[Run]                      # gras / italique inline
def assembler(textes: list[str]) -> str
```

---

## 5. Formats des fichiers intermédiaires

Cette section est un **contrat**. Chaque étape s'engage à produire exactement ce
format, et peut supposer que l'étape précédente l'a respecté.

### 5.1 `<Livre>_OCR_pages/page_NNNN.txt`

Texte brut d'une page, tel que rendu par le modèle vision. Aucun marqueur, aucun
traitement. `NNNN` = numéro de page dans le PDF, sur 4 chiffres, à partir de
`0001`. La numérotation suit le PDF, jamais la pagination imprimée du livre.

### 5.2 `<Livre>_OCR.txt`

Assemblage des pages. Format exact :

```
[PAGE 1]
Texte brut de la première page,
paragraphes conservés tels quels.

<<<PAGE_BREAK>>>

[PAGE 2]
Texte brut de la deuxième page.
```

- Le marqueur `[PAGE X]` ouvre chaque page, seul sur sa ligne.
- Le séparateur exact est `\n\n<<<PAGE_BREAK>>>\n\n`.
- **Aucune correction** n'a été appliquée à ce stade. Ce fichier est la
  référence de vérité pour l'étape 3 : c'est parce qu'il n'est jamais corrigé
  qu'il permet de détecter ce que l'étape 2 aurait perdu.

### 5.3 `<Livre>_EDIT_blocs/bloc_NNNN.txt`

Texte édité d'un bloc de `PAGES_PAR_BLOC` pages. Marqueurs `[PAGE X]` et
`<<<PAGE_BREAK>>>` supprimés. Convention typographique de [§8](#8-la-convention-typographique--le-contrat-entre-les-étapes) appliquée.

### 5.4 Sidecars `.json` — schéma commun

Tous les sidecars partagent une base commune, ce qui permet à
`unite_terminee()` d'être unique pour les trois étapes IA :

```json
{
  "statut": "termine",
  "unite": "bloc",
  "numero": 1,
  "page_debut": 1,
  "page_fin": 8,
  "modele": "gpt-5.5-2026-04-23",
  "date_traitement": "2026-07-27T14:32:10.123456",
  "response_id": "resp_abc123",
  "duree_secondes": 18.42,
  "tentative_reussie": 1,
  "longueur_entree": 14203,
  "longueur_sortie": 13871,
  "avertissements": []
}
```

`statut` prend exactement trois valeurs :

| Valeur | Signification | L'unité sera-t-elle refaite ? |
|---|---|---|
| `"termine"` | Réussie, contrôles passés | non |
| `"suspect"` | Produite mais avertissements présents | oui si `RETRAITER_BLOCS_SUSPECTS` |
| `"echec"` | Toutes les tentatives ont échoué | **oui, toujours** |

### 5.5 `<Livre>_EDIT.txt`

Assemblage **exclusivement** des blocs présents dans `_EDIT_raccords/`, jamais
de `_EDIT_blocs/`. Blocs joints par `\n\n`. Le fichier se termine par un unique
`\n`.

### 5.6 `<Livre>_REPORT.txt`

Texte destiné à un lecteur humain, pas à une machine. Structure :

```
========================================================================
RAPPORT DE CONTRÔLE QUALITÉ — Le Malentendu
Généré le 2026-07-27 à 14:32
OCR  : 412 038 caractères, 289 pages
EDIT : 398 114 caractères, 37 blocs
========================================================================

------------------------------------------------------------------------
CONTRÔLES AUTOMATIQUES (mécaniques, sans IA)
------------------------------------------------------------------------
[OK]      Parité des astérisques
[ALERTE]  Bloc 12 : ratio de longueur 0.71 (seuil 0.80)
[ALERTE]  Personnage présent dans l'OCR, absent de l'EDIT : LE GARDE
          → OCR pages 96-104

------------------------------------------------------------------------
BLOC 12 — pages 89 à 96
------------------------------------------------------------------------
[TEXTE RACCOURCI]     Réplique de MARTHA abrégée.
                      Vers « Je n'ai jamais eu le temps »
[DIDASCALIE PERDUE]   « Elle referme la porte » absente
                      Après la réplique de JAN, ~ligne 40
```

### 5.7 Journaux `journal_<etape>.json`

Voir [§12](#12-journalisation).

---

## 6. Flux des données, étape par étape

### Étape 1 — OCR

| | |
|---|---|
| **Entrée** | `<Livre>.pdf` |
| **Sortie** | `<Livre>_OCR.txt` |
| **Unité de reprise** | **la page** |
| **Modèle** | `MODEL_OCR` (GPT-4o) |
| **Prompt** | `prompts/prompt_ocr.md` |

Déroulé :

1. Scanner `DOSSIER_DRIVE`, lister tous les `.pdf`.
2. Pour chaque PDF, ouvrir avec PyMuPDF, compter les pages.
3. Pour chaque page `i` :
   - si `page_{i}.json` dit `termine` → **sauter, aucun appel API** ;
   - rasteriser à `DPI_RASTERISATION` → PNG → base64 ;
   - appel Responses API vision ;
   - écrire `page_{i}.txt` **puis** `page_{i}.json` (ordre critique, §7) ;
   - `time.sleep(PAUSE_ENTRE_APPELS)`.
4. Assembler toutes les pages en `<Livre>_OCR.txt`.
5. Écrire `journal_ocr.json`.

L'assemblage est **systématiquement refait** à chaque exécution. C'est une
opération locale, gratuite, et elle garantit que `OCR.txt` reflète toujours
l'état réel du cache — y compris après une reprise partielle.

Le prompt OCR interdit toute correction : le modèle transcrit, il ne lit pas.
C'est l'étape 2 qui corrigera. Cette séparation est essentielle (§10, D6).

### Étape 2a — Édition par blocs

| | |
|---|---|
| **Entrée** | `<Livre>_OCR.txt` |
| **Sortie** | `_EDIT_blocs/bloc_NNNN.txt` |
| **Unité de reprise** | **le bloc** |
| **Modèle** | `MODEL_EDITION` |
| **Prompt** | `prompts/prompt_edition.md` (repris du prototype) |

Déroulé : découpage en pages → regroupement par `PAGES_PAR_BLOC` → pour chaque
bloc non terminé, appel API → `verifier_sortie()` → écriture txt puis json.

Le découpage est **purement déterministe** : même `OCR.txt` ⇒ mêmes frontières
de blocs. C'est ce qui rend la reprise correcte : le `bloc_0012.txt` d'hier
correspond exactement au bloc 12 recalculé aujourd'hui.

### Étape 2b — Passe de raccord

| | |
|---|---|
| **Entrée** | `_EDIT_blocs/` |
| **Sortie** | `_EDIT_raccords/` puis `<Livre>_EDIT.txt` |
| **Unité de reprise** | **la jonction** |
| **Modèle** | `MODEL_RACCORD` |
| **Prompt** | `prompts/prompt_raccord.md` (repris du prototype) |

1. Copier chaque `_EDIT_blocs/bloc_N.txt` vers `_EDIT_raccords/bloc_N.txt`,
   uniquement si la destination n'existe pas.
2. Pour chaque jonction `N`/`N+1`, dans l'ordre croissant :
   - extraire les `LIGNES_CONTEXTE_RACCORD` (50) dernières lignes de `N` et les
     50 premières de `N+1` ;
   - appel API, réponse au format délimité
     `<<<BLOC_GAUCHE>>>…<<<BLOC_DROIT>>>…` ;
   - **recoller** : `préfixe_gauche + gauche_corrigée` et
     `droite_corrigée + suffixe_droit` ;
   - réécrire les deux fichiers, puis `raccord_N.json`.
3. Assembler `_EDIT_raccords/` → `<Livre>_EDIT.txt`.

**Point subtil, à conserver du prototype** : l'ordre croissant est significatif.
Le bloc droit corrigé à la jonction `N` sert de bloc gauche à la jonction `N+1`.
Les corrections se propagent donc correctement, et la reprise reste cohérente
parce que les fichiers de `_EDIT_raccords/` sont mis à jour en place, jonction
par jonction.

Seul risque de ce schéma : si l'on interrompt entre l'écriture des deux `.txt`
et celle du `.json`, la jonction sera refaite sur un texte déjà partiellement
raccordé. Le prompt de raccord étant idempotent par nature (« si aucune
correction n'est nécessaire, rends les extraits tels quels »), refaire un
raccord déjà fait est sans effet. C'est une propriété que je vérifierai en
rédigeant le prompt.

### Étape 3 — Contrôle qualité

| | |
|---|---|
| **Entrée** | `<Livre>_OCR.txt` **et** `<Livre>_EDIT.txt` |
| **Sortie** | `<Livre>_REPORT.txt` |
| **Unité de reprise** | **le bloc** |
| **Modèle** | `MODEL_VALIDATION` |
| **Prompt** | `prompts/prompt_validation.md` |

Deux familles de contrôles, fusionnées dans un seul rapport.

**(a) Contrôles mécaniques, sans IA** — rapides, gratuits, déterministes,
100 % fiables :

- ratio de longueur global et par bloc, seuil `RATIO_MINIMAL_LONGUEUR` ;
- différence des jeux de noms de personnages entre OCR et EDIT ;
- parité des astérisques, motifs interdits résiduels ;
- présence des mots-clés de structure (`ACTE`, `SCÈNE`…) de l'OCR dans l'EDIT ;
- delta de nombre de lignes non vides par bloc.

**(b) Comparaison sémantique par bloc, avec IA** — pour ce qu'aucune règle ne
peut voir : didascalie perdue, réplique abrégée, raccord mal ressoudé.

Pour chaque bloc `N` : on redécoupe `OCR.txt` avec les mêmes frontières
(disponibles dans `bloc_N.json`, champs `page_debut`/`page_fin`) et on envoie le
couple (OCR du bloc, EDIT du bloc). Le modèle ne renvoie que des constats.

Découper est ici une nécessité, pas un choix : un livre entier ne tient pas dans
une fenêtre de contexte, et un rapport sur un livre entier dépasserait
`MAX_OUTPUT_TOKENS`.

### Étape 4 — DOCX

| | |
|---|---|
| **Entrée** | `<Livre>_EDIT.txt` |
| **Sortie** | `<Livre>.docx` |
| **IA** | **aucune** |
| **Reprise** | sans objet (quelques secondes, entièrement local) |

1. Lire `EDIT.txt`.
2. Recenser les personnages (première passe, §9.1).
3. Classifier chaque ligne (deuxième passe).
4. Découper chaque ligne en runs (gras / italique inline, §9.2).
5. Construire le document avec les styles nommés de [§9.3](#93-styles-docx).
6. Écrire le `.docx` et `journal_docx.json`.

---

## 7. Le patron de reprise : l'invariant d'idempotence

C'est le mécanisme central de la robustesse. Il mérite d'être énoncé
formellement, parce que tout le reste en découle.

### 7.1 L'invariant

> Toute unité de travail possède un chemin de sortie déterministe et un sidecar
> JSON. Le sidecar est **toujours écrit après** le fichier de contenu. Une unité
> est réputée terminée **si et seulement si** son sidecar existe et porte
> `statut == "termine"`.

### 7.2 Pourquoi l'ordre d'écriture suffit

Considérons les trois moments où Colab peut couper :

| Interruption | État sur le disque | Décision à la reprise | Correct ? |
|---|---|---|---|
| avant l'écriture du `.txt` | rien | refaire | ✅ |
| entre `.txt` et `.json` | `.txt` seul, orphelin | refaire, écrase le `.txt` | ✅ |
| après le `.json` | les deux | sauter | ✅ |

Aucun cas ne produit un travail perdu ni un travail faussement validé. Le
sidecar joue le rôle de **marqueur de validation (commit)** : le contenu existe
avant d'être déclaré valide, jamais l'inverse.

### 7.3 Écriture atomique

Google Drive monté en FUSE peut produire des fichiers tronqués si l'écriture est
interrompue en plein flush. `ecrire_texte_atomique()` écrit dans
`<nom>.tmp` puis appelle `os.replace()`, opération atomique au niveau du
système de fichiers. Un lecteur ne voit donc jamais un fichier à moitié écrit.

### 7.4 Les trois étages de reprise

| Étage | Granularité | Coût d'une reprise |
|---|---|---|
| étape | 4 étapes | relancer un notebook |
| livre | N PDF dans le dossier | boucle, livres déjà faits sautés |
| unité | page / bloc / jonction | **1 appel API perdu au maximum** |

Dans le pire cas, une coupure de Colab coûte **un seul appel API**.

---

## 8. La convention typographique : le contrat entre les étapes

Votre prototype a déjà établi une convention pseudo-Markdown. Je la reprends
telle quelle et j'en fais le **pivot de l'architecture**, car elle produit un
bénéfice majeur : l'étape 4 devient entièrement déterministe.

| Élément | Écriture dans `EDIT.txt` | Exemple |
|---|---|---|
| Titre (acte, partie, scène) | `**…**`, seul sur la ligne | `**UN.**` |
| Lieu / description initiale | `*…*`, seul sur la ligne | `*Une rue. Mark et Jan.*` |
| Personnage | `**…**` en capitales, seul sur la ligne | `**JAN.**` |
| Réplique | ligne(s) nue(s) sous le personnage | `Mort ?` |
| Didascalie | `*…*`, seule sur la ligne | `*Pause.*` |
| Didascalie inline | `*…*` au milieu d'une réplique | `Bonjour *il sourit* ça va ?` |
| Séparateur de scène | `***` seul sur la ligne | `***` |
| Illisible | `*[texte illisible]*` | |

Exemple complet :

```
**UN.**

*Une rue. Mark et Jan.*

**JAN.**
Mort ?

**MARK.**
Oui.

*Pause.*

**JAN.**
Comment ?

***
```

**Pourquoi c'est le bon choix**, plutôt qu'un format structuré (JSON/XML) :

1. `EDIT.txt` reste **lisible et corrigeable à la main** dans n'importe quel
   éditeur. Pour un travail éditorial, c'est décisif : vous relirez ce fichier.
2. Le modèle produit du Markdown naturellement et fiablement. Lui demander du
   JSON strict sur 400 pages multiplierait les erreurs de format et les
   troncatures.
3. La grammaire est **régulière**, donc analysable par des règles simples et
   testables.
4. Elle est déjà éprouvée par vos prompts existants.

Contrepartie assumée : cette grammaire est ambiguë sur un point (titre vs
personnage), traité en [§9.1](#91-titre-ou-personnage-la-seule-ambiguïté-réelle).

---

## 9. Problèmes délicats et leur résolution

### 9.1 Titre ou personnage : la seule ambiguïté réelle

`**UN.**` (titre) et `**JAN.**` (personnage) sont **syntaxiquement
indiscernables** : gras, seuls sur leur ligne, en capitales.

**Circonstance atténuante déterminante** : votre cahier des charges demande
« titres : centrés, gras » **et** « personnages : centrés, gras ». Les deux
rendus sont donc **visuellement identiques**. Une erreur de classification est
par conséquent invisible dans le DOCX. Le risque est faible.

Je maintiens néanmoins la distinction, pour deux raisons : appliquer un style
nommé distinct permet un saut de page avant un acte
(`SAUT_DE_PAGE_AVANT_TITRE`), et Word peut construire un sommaire à partir des
styles de titre.

Heuristique en deux passes :

**Passe 1 — recensement.** Parcourir tout `EDIT.txt` et collecter les
candidats `**X.**`. Un candidat est retenu comme **personnage** si :

- il apparaît au moins `SEUIL_OCCURRENCES_PERSONNAGE` fois (défaut : 2) ; **et**
- il est suivi, au moins une fois, d'une ligne de réplique non vide.

**Passe 2 — arbitrage par lexique.** Un candidat est classé **titre**,
prioritairement sur la passe 1, s'il correspond à
`LEXIQUE_TITRES` : `ACTE`, `SCÈNE`, `TABLEAU`, `PARTIE`, `PROLOGUE`,
`ÉPILOGUE`, `INTERMÈDE`, ou un nombre écrit (`UN`, `DEUX`, `PREMIER`…), ou un
chiffre romain seul.

**Départage final.** Un candidat ni personnage ni titre (occurrence unique, non
suivi de réplique) est classé **titre** — c'est le cas d'un titre de scène
inhabituel, et la conséquence visuelle est nulle.

Cette logique vit dans `blocks.py`, elle est pure, donc directement testable.

### 9.2 Didascalie inline : le parsing à deux niveaux

Une réplique réelle ressemble souvent à ceci :

```
Je t'attendais *elle se lève* depuis une heure.
```

Un parsing ligne par ligne produirait un paragraphe entièrement romain,
perdant l'italique. La solution est un parsing **à deux niveaux** :

1. **Niveau ligne** → détermine le *style de paragraphe* (Titre, Lieu,
   Personnage, Didascalie, Texte).
2. **Niveau run** → à l'intérieur du paragraphe, `decouper_en_runs()` découpe
   sur `**gras**` et `*italique*` et produit une liste de runs typés, que
   `python-docx` ajoute successivement.

Cette séparation évite un piège classique : traiter `**` avant `*`. Une seule
expression régulière alternée, appliquée de gauche à droite, avec `**` en
première alternative, règle le problème proprement.

### 9.3 Styles DOCX

Cinq styles de paragraphe créés programmatiquement — jamais de mise en forme
appliquée run par run, afin qu'une modification globale reste un changement d'une
seule ligne de `config.py`.

| Style | Alignement | Casse/graisse | Espacement |
|---|---|---|---|
| `Theatre_Titre` | centré | **gras** | avant 24 pt, après 18 pt |
| `Theatre_Lieu` | centré | *italique* | avant 12 pt, après 12 pt |
| `Theatre_Personnage` | centré | **gras** | avant 12 pt, après 0 pt |
| `Theatre_Didascalie` | centré | *italique* | avant 6 pt, après 6 pt |
| `Theatre_Texte` | **justifié** | romain | après 6 pt |

Communs à tous : EB Garamond, 11 pt, **aucune couleur** (on ne définit
simplement jamais `font.color`, la valeur héritée est le noir automatique).

Trois précisions techniques :

- **Numéros de page** : `python-docx` n'en insère aucun par défaut. Il n'y a
  donc rien à faire, seulement rien à ajouter. L'exigence est satisfaite par
  construction.
- **EB Garamond** : `python-docx` n'incorpore pas la police, il inscrit son
  *nom* dans le XML. La police est résolue par la machine qui ouvre le fichier.
  Aucune installation n'est requise pour *générer* le DOCX ; en revanche, si la
  police est absente de votre poste, Word substituera. Je définirai aussi
  `w:rFonts/@w:cs` et `@w:eastAsia` en plus de `@w:ascii`, car `python-docx` ne
  renseigne pas ces attributs et Word peut alors substituer à tort.
- **Marges** : `MARGE_CM = 3.0` sur les quatre côtés (« généreuses »).

### 9.4 Se protéger de l'infidélité du modèle

P1 exige la fidélité, mais un prompt n'est pas une garantie. Trois filets
mécaniques, indépendants du modèle :

1. **Ratio de longueur** par bloc (`RATIO_MINIMAL_LONGUEUR`) → détecte
   troncature et résumé involontaire.
2. **Motifs interdits** → `<<<PAGE_BREAK>>>` résiduel, ` ``` `, « Voici le
   texte corrigé », « je ne peux pas »… Détecte le bavardage et les refus.
3. **Parité des astérisques** → détecte une convention typographique cassée,
   qui casserait l'étape 4.

Un bloc en échec sur l'un de ces contrôles est marqué `"suspect"` et sera
retraité au prochain passage si `RETRAITER_BLOCS_SUSPECTS` est vrai. Ces
contrôles sont repris du prototype, où ils étaient déjà présents et pertinents.

### 9.5 Ne jamais perdre une page à cause d'un PDF récalcitrant

Une page peut échouer pour des raisons non liées au modèle : page corrompue,
image gigantesque, dépassement de la taille de requête. Trois protections :

- si le PNG rasterisé dépasse `TAILLE_MAX_IMAGE_MO`, réduire le DPI et
  réessayer (dégradation progressive, plutôt qu'un échec sec) ;
- une page qui échoue définitivement est marquée `"echec"`, **le livre
  continue**, et la page apparaît dans le récapitulatif final ;
- l'assemblage insère un marqueur visible `[PAGE N — ÉCHEC OCR]` afin que le
  trou soit repérable dans `OCR.txt` plutôt que silencieux.

---

## 10. Choix techniques et justifications

| # | Décision | Alternatives écartées | Raison |
|---|---|---|---|
| **D1** | **PyMuPDF** (`pymupdf`) pour rasteriser | `pdf2image` | `pdf2image` exige le binaire système *poppler*, à installer via `apt` dans Colab : lent et fragile. PyMuPDF est un simple `pip install`, très rapide, et donne un contrôle fin du DPI. |
| **D2** | Rasteriser **toutes** les pages, sans tenter d'extraire une couche texte | extraction `pypdf`/`pdfplumber` si couche texte présente | Sur un scan il n'y a pas de couche texte. Sur un PDF hybride, mélanger deux sources produirait une qualité inégale et non reproductible. Vous demandez explicitement l'OCR Vision. Un chemin unique est un chemin testable. |
| **D3** | **Responses API** exclusivement, `client.responses.create()` | Chat Completions | Exigence de votre cahier des charges. Bénéfice réel : `output_text` unifié, `instructions` séparé de `input`, et le même code sert le texte et la vision. |
| **D4** | Une unité de reprise = **une page** à l'étape 1 | un seul appel par PDF, ou par lot de pages | Une page = un appel = une perte maximale d'un appel. C'est aussi la granularité qui rend l'OCR reprenable au sens strict que vous demandez. |
| **D5** | Un **cache page par page** puis assemblage, plutôt qu'un `OCR.txt` en ajout | append direct dans `OCR.txt` | En mode append, une coupure laisse un fichier dont on ne peut pas savoir si la dernière page est complète. Impossible de reprendre sûrement. Le cache + sidecar lève l'ambiguïté. C'est un ajout au format demandé, justifié en §14. |
| **D6** | **Séparer transcription (1) et correction (2)** | un seul appel qui OCRise et corrige | Deux bénéfices. (a) `OCR.txt` non corrigé devient la référence de vérité de l'étape 3 : sans lui, on ne peut rien détecter. (b) On peut réviser le prompt d'édition et relancer l'étape 2 **sans repayer l'OCR**, qui est la partie coûteuse. |
| **D7** | Prompts en **Markdown externes**, chargés puis mis en cache | f-strings en Python | Exigence P5. Bénéfice : itérer sur la qualité éditoriale sans toucher au code, et `git diff` lisible sur un prompt. |
| **D8** | **Étape 4 sans aucune IA** | classification des lignes par modèle | Exigence. Et sur le fond : la convention de §8 est régulière, une IA ici n'ajouterait que du coût, de la latence et du non-déterminisme. Deux exécutions doivent donner deux fichiers identiques. |
| **D9** | Contrôles mécaniques **en plus** de la validation IA | validation IA seule | Les contrôles de §9.4 sont gratuits, instantanés et fiables à 100 %. Ils rendent `REPORT.txt` utile même si le modèle passe à côté d'un problème. |
| **D10** | `utils/api.py` mutualisé | retry dupliqué dans `ocr.py`, `edition.py`, `validation.py` | Vous interdisez la duplication. Trois copies d'une logique de retry, c'est trois occasions de divergence. |
| **D11** | Code et docstrings **en français** | anglais | Continuité avec votre prototype (`lire_fichier_ocr`, `decouper_en_pages`) et avec le domaine (didascalie, réplique, raccord) dont le vocabulaire technique est français. Un mélange serait le pire choix. |
| **D12** | Journaux JSON réécrits atomiquement à chaque ajout | JSONL en append | Vous demandez des `.json`. À l'échelle d'un livre (quelques centaines d'entrées), réécrire un JSON complet coûte quelques millisecondes. Le fichier reste un JSON valide en permanence, y compris après interruption. |
| **D13** | `temperature` **optionnelle** (`None` ⇒ non transmise) | toujours envoyer `temperature=0` | `temperature=0` est idéal pour la fidélité, mais certains modèles récents rejettent le paramètre. Le rendre omissible évite un plantage à chaque changement de modèle. |
| **D14** | Le nom du livre dérive du nom du PDF, chemins centralisés | chemins construits sur place | Une seule fonction `resoudre_chemins()` : renommer une convention de fichier devient un changement d'un seul endroit. |

---

## 11. Configuration

`config.py` — intégralité des constantes, aucune logique. Les valeurs ci-dessous
sont mes propositions de défaut.

```python
# ----- Emplacements ---------------------------------------------------
DOSSIER_DRIVE = Path("/content/drive/MyDrive/Troupe 122 - 2026-27")

# ----- Modèles --------------------------------------------------------
MODEL_OCR         = "gpt-4o"                  # vision
MODEL_EDITION     = "gpt-5.5-2026-04-23"      # repris de votre prototype
MODEL_RACCORD     = "gpt-5.5-2026-04-23"
MODEL_VALIDATION  = "gpt-5.5-2026-04-23"

# ----- Découpage ------------------------------------------------------
PAGES_PAR_BLOC            = 8
LIGNES_CONTEXTE_RACCORD   = 50

# ----- Appels API -----------------------------------------------------
MAX_OUTPUT_TOKENS   = 16000
MAX_TENTATIVES      = 4
PAUSE_ENTRE_APPELS  = 1.0
ATTENTE_MAX_BACKOFF = 60
TEMPERATURE         = None      # None ⇒ paramètre non transmis (D13)
STOCKER_REPONSES    = True      # → store=… côté API (voir §17)

# ----- Rasterisation PDF ---------------------------------------------
DPI_RASTERISATION    = 200
DPI_MINIMAL          = 110      # plancher en cas de dégradation
TAILLE_MAX_IMAGE_MO  = 18.0

# ----- Contrôles qualité ---------------------------------------------
RATIO_MINIMAL_LONGUEUR       = 0.80   # étape 2 (0.55 dans le prototype)
RETRAITER_BLOCS_SUSPECTS     = True
SEUIL_OCCURRENCES_PERSONNAGE = 2

# ----- Marqueurs (contrat inter-étapes, §5) --------------------------
MARQUEUR_PAGE     = "[PAGE {numero}]"
SEPARATEUR_PAGE   = "\n\n<<<PAGE_BREAK>>>\n\n"

# ----- DOCX -----------------------------------------------------------
POLICE_TEXTE            = "EB Garamond"
TAILLE_TEXTE_PT         = 11
MARGE_CM                = 3.0
SAUT_DE_PAGE_AVANT_TITRE = False

# ----- Suffixes de fichiers ------------------------------------------
SUFFIXE_OCR           = "_OCR.txt"
SUFFIXE_OCR_PAGES     = "_OCR_pages"
SUFFIXE_EDIT          = "_EDIT.txt"
SUFFIXE_EDIT_BLOCS    = "_EDIT_blocs"
SUFFIXE_EDIT_RACCORDS = "_EDIT_raccords"
SUFFIXE_REPORT        = "_REPORT.txt"
SUFFIXE_REPORT_BLOCS  = "_REPORT_blocs"
```

Deux valeurs méritent votre attention :

- **`RATIO_MINIMAL_LONGUEUR`** : votre prototype utilisait `0.55`. C'est très
  permissif — une réplique pourrait être amputée de 40 % sans déclencher
  d'alerte. Or l'étape 2 supprime les marqueurs `[PAGE X]`, et le ratio est
  calculé après neutralisation de ces marqueurs : la sortie devrait donc être
  proche de 0,95–1,00 de l'entrée. Je propose `0.80`, nettement plus protecteur.
- **`MODEL_OCR = "gpt-4o"`** conformément à votre demande, tandis que
  `MODEL_EDITION` conserve le modèle de votre prototype. Ce sont des variables
  de configuration : si un identifiant n'est pas disponible sur votre compte,
  vous le changez en un seul endroit.

---

## 12. Journalisation

Un fichier par étape, à la racine de `DOSSIER_DRIVE`, structure identique :

```json
{
  "etape": "ocr",
  "derniere_execution": "2026-07-27T14:32:10",
  "configuration": {
    "modele": "gpt-4o",
    "dpi": 200,
    "max_output_tokens": 16000
  },
  "livres": {
    "Le Malentendu": {
      "statut": "termine",
      "unites_totales": 289,
      "unites_terminees": 287,
      "unites_suspectes": 2,
      "unites_echouees": 0,
      "duree_totale_secondes": 5218.4
    }
  },
  "appels": [
    {
      "date": "2026-07-27T14:31:52",
      "livre": "Le Malentendu",
      "unite": "page",
      "numero": 1,
      "modele": "gpt-4o",
      "response_id": "resp_abc123",
      "duree_secondes": 4.81,
      "longueur_entree": 248193,
      "longueur_sortie": 1842,
      "tentative_reussie": 1,
      "tokens_entree": 1204,
      "tokens_sortie": 498,
      "avertissements": []
    }
  ]
}
```

Tous les champs que vous demandez sont présents : date, modèle, `response_id`,
temps d'exécution, longueur d'entrée, longueur de sortie, avertissements. J'y
ajoute la consommation de jetons quand l'API la renvoie (`response.usage`), car
c'est ce qui permet d'estimer le coût réel d'un livre.

`longueur_entree` est en caractères, sauf à l'étape 1 où l'entrée est une image :
c'est alors la taille du PNG en octets. Ce point sera commenté dans le code, car
il est une source de confusion évidente.

Écriture via `ecrire_texte_atomique()`, donc jamais de journal corrompu.

---

## 13. Gestion des erreurs

### Philosophie : échouer par unité, poursuivre l'exécution

Une page illisible ne doit pas faire perdre 280 pages de travail. Chaque unité
est encapsulée : en cas d'échec définitif, on enregistre `statut: "echec"`, on
journalise, on affiche, **on continue**. Le récapitulatif final liste les unités
en échec pour un nouveau passage ciblé.

### Stratégie de réessai

`utils/api.py` centralise : jusqu'à `MAX_TENTATIVES` tentatives, attente
exponentielle `5 × 2^(n-1)` plafonnée à `ATTENTE_MAX_BACKOFF`, plus un jitter
aléatoire pour éviter la synchronisation des relances.

### Ce qui, au contraire, doit arrêter immédiatement

Trois conditions font échouer l'exécution sans tenter de continuer, parce que
poursuivre produirait un résultat silencieusement faux :

- clé API absente ou invalide ;
- `DOSSIER_DRIVE` inexistant (Drive non monté) ;
- fichier d'entrée d'une étape absent (`OCR.txt` manquant à l'étape 2).

Chacune produit un message explicite disant **quoi faire**, pas seulement ce qui
a échoué.

---

## 14. Écarts assumés par rapport à l'arborescence demandée

Trois ajouts par rapport à votre spécification. Je les signale parce que ce sont
des écarts, et que vous devez pouvoir les refuser.

### 14.1 `utils/api.py` — ajout

**Ce que c'est** : le client OpenAI, la boucle de réessai, l'extraction du texte
de réponse, le chronométrage.

**Pourquoi** : `ocr.py`, `edition.py` et `validation.py` ont tous les trois
besoin de cette logique. Sans module commun, elle serait recopiée trois fois —
ce que votre consigne « aucune duplication de code » interdit. Dans votre
prototype, cette logique existe déjà mais mêlée à `editer_bloc_api()`, ce qui
la rend non réutilisable.

**Si vous refusez** : je place ces fonctions dans `utils/io.py`. Mais y mettre du
réseau brouillerait sa responsabilité, qui est le système de fichiers.

### 14.2 Les dossiers de cache `_OCR_pages/` et `_REPORT_blocs/` — ajout

**Pourquoi** : votre spécification décrit `_EDIT_blocs/` pour l'étape 2, mais
demande aussi « sauvegarder chaque page immédiatement » et « reprendre
automatiquement un OCR interrompu » à l'étape 1. Ces deux exigences **impliquent
un cache par page** : sans lui, la reprise ne peut pas savoir si la dernière
page écrite est complète (voir D5). J'applique donc le même patron aux étapes 1
et 3 qu'à l'étape 2. Bénéfice secondaire : un seul patron de reprise à
comprendre, à tester et à maintenir pour les trois étapes IA.

### 14.3 `tests/` — ajout

**Pourquoi** : `blocks.py` concentre la logique la plus subtile (classification
titre/personnage, fenêtrage, runs inline) et elle est **pure**, donc testable en
une seconde sans clé API ni Drive. Le rapport valeur/coût est excellent, et vous
placez la robustesse au-dessus de la concision. Ces tests s'exécutent en local
comme dans Colab.

**Si vous refusez** : je les retire, sans autre conséquence sur l'architecture.

---

## 15. Conventions de code

- **Français** pour les noms, docstrings et commentaires (D11). Types Python
  standards en anglais (`list[str]`, `Path`).
- **Fonctions courtes**, une responsabilité. Cible : moins de 40 lignes.
  `effectuer_passe_raccord()` du prototype fait ~130 lignes et sera scindée.
- **Typage** sur toutes les signatures publiques. `from __future__ import
  annotations` pour la syntaxe moderne.
- **Docstrings** sur tout module, classe et fonction publique : ce que fait la
  fonction, ses paramètres, sa valeur de retour, ses exceptions.
- **Commentaires** réservés au *pourquoi*, jamais au *quoi*. Les sections
  délimitées par `# ===…` de votre prototype sont conservées : elles sont lisibles
  et vous êtes visiblement habitué à ce repère visuel.
- **`dataclass`** pour les structures (`Bloc`, `CheminsLivre`, `Run`,
  `ResultatAppel`) plutôt que des `dict` : l'autocomplétion et les erreurs de
  frappe détectées valent leur poids.
- **Aucune exception nue**. `except Exception` est acceptable dans la boucle de
  réessai, mais l'erreur y est toujours journalisée et relancée.
- **Aucun `print` dans le code métier** : tout passe par `utils/logging.py`,
  afin qu'un changement de verbosité soit centralisé.

---

## 16. Plan de livraison

Un commit par étape cohérente, dans cet ordre — chaque commit laisse le dépôt
dans un état compréhensible.

| # | Commit | Contenu |
|---|---|---|
| 1 | ✅ *fait* | Prototype préservé + `.gitignore` |
| 2 | ⬅ *ce document* | `ARCHITECTURE.md` |
| 3 | Socle | `config.py`, `__init__.py`, `requirements.txt`, `.gitattributes` |
| 4 | Utilitaires | `utils/io.py`, `utils/logging.py` |
| 5 | Logique texte | `utils/blocks.py` + `tests/test_blocks.py` |
| 6 | Couche API | `utils/api.py` |
| 7 | Prompts | les 4 fichiers `prompts/*.md` |
| 8 | Étape 1 | `ocr.py` |
| 9 | Étape 2 | `edition.py` |
| 10 | Étape 3 | `validation.py` |
| 11 | Étape 4 | `docx_export.py` + `tests/test_docx_export.py` |
| 12 | Orchestration | `main.py` |
| 13 | Notebooks | les 4 `.ipynb` |
| 14 | Documentation | `README.md`, déplacement du prototype dans `archive/` |

L'ordre n'est pas arbitraire : chaque commit ne dépend que des précédents, donc
le dépôt est cohérent à tout moment. Les tests des commits 5 et 11 sont
exécutables immédiatement, sans clé API — je pourrai donc vous montrer que la
logique délicate fonctionne avant même le premier appel facturé.

---

## 17. Points à valider avant écriture du code

Six questions dont la réponse change le code. Un simple « tout est bon » vaut
acceptation de mes valeurs par défaut.

1. **`MODEL_EDITION = "gpt-5.5-2026-04-23"`** — repris de votre prototype. Cet
   identifiant est-il bien disponible sur votre compte, et faut-il l'utiliser
   aussi pour le raccord et la validation ? (Le raccord et la validation sont
   des tâches beaucoup plus étroites : un modèle moins coûteux y suffirait
   probablement, pour un gain de coût appréciable sur un livre.)

2. **`RATIO_MINIMAL_LONGUEUR` : `0.80` au lieu de `0.55`** (§11). Plus
   protecteur, mais produira davantage de blocs marqués « suspects » et donc de
   retraitements. Préférez-vous rester à `0.55` ?

3. **`STOCKER_REPONSES`** — par défaut, la Responses API conserve les réponses
   côté OpenAI (`store=True`). Pour une pièce sous droits, vous pouvez préférer
   `store=False`. Je propose `True` (aligné sur le comportement actuel de votre
   prototype) mais le paramètre est là. Que choisissez-vous ?

4. **Les trois ajouts de §14** (`utils/api.py`, dossiers de cache, `tests/`) —
   acceptés ?

5. **`DOSSIER_DRIVE`** — je reprends `/content/drive/MyDrive/Troupe 122 - 2026-27`
   de votre prototype. Est-ce bien le dossier contenant les PDF ?

6. **Saut de page avant chaque acte** dans le DOCX — `False` par défaut, parce
   que vous ne l'avez pas demandé. C'est pourtant l'usage courant dans une
   édition de théâtre. Le passer à `True` ?

---

*Document rédigé avant tout code, conformément à la consigne. La suite du*
*travail commence au commit 3 du plan de livraison, après votre validation.*
