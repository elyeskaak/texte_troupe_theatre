# ARCHITECTURE — Pipeline d'édition de pièces de théâtre

> **Statut : validé le 2026-07-27.**
> Les neuf décisions ouvertes ont été tranchées ; le relevé figure en
> [§17](#17-décisions-validées). L'implémentation peut commencer au commit 3
> du [plan de livraison](#16-plan-de-livraison).
>
> Révision notable depuis la première rédaction : l'exigence de **discerner
> acte, scène et personnage**, combinée au saut de page réservé aux actes, a
> imposé une refonte complète de [§9.1](#91-acte-scène-ou-personnage--la-classification-à-trois-niveaux)
> et le passage à six styles DOCX. Voir [§17.1](#171-lexigence-qui-a-le-plus-changé-la-conception).

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
17. [Décisions validées](#17-décisions-validées)

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
      │  ÉTAPE 2c — Rôles des pages liminaires    (même notebook)
      │  ┌──────────────────────────────────────────────────────────┐
      │  │ LIGNES_LIMINAIRES premières lignes au plus                │
      │  │ UN SEUL appel par livre, mis en cache                     │
      │  │ Responses API → « numéro|rôle », aucun texte rendu        │
      │  │ Écriture : LIMINAIRES.json                                │
      │  └──────────────────────────────────────────────────────────┘
      │
      ├──▶ LIMINAIRES.json             ← rôles seuls, relus par l'étape 4
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

Second point : **l'étape 2c ne produit aucun texte.** Elle ne rend que des
couples « numéro de ligne → rôle ». C'est ce qui la rend inoffensive : elle ne
peut pas altérer l'œuvre, seulement se tromper sur la mise en forme de quelques
lignes du début. Elle est de surcroît facultative — sans `LIMINAIRES.json`,
l'étape 4 retombe intégralement sur ses règles déterministes. Une étape d'IA
ajoutée sans créer de dépendance.

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
│   │   ├── prompt_validation.md
│   │   └── prompt_liminaires.md     ← étape 2c
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
│   ├── liminaires.py                ← étape 2c — un appel par livre
│   ├── validation.py                ← étape 3
│   ├── docx_export.py               ← étape 4
│   ├── repet_export.py              ← étape 4, seconde sortie (§5.7)
│   └── main.py                      ← orchestration CLI
│
├── notebooks/                       ← générés par outils/, jamais à la main
│   ├── 01_OCR.ipynb
│   ├── 02_Edition.ipynb             ← contient les étapes 2a, 2b et 2c
│   ├── 03_Verification.ipynb
│   └── 04_DOCX.ipynb
│
├── outils/
│   └── generer_notebooks.py         ← ⚠ AJOUT — cf. §14
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
├── Le Malentendu.docx                    ← SORTIE étape 4
├── ignorer.txt                           ← livres à écarter, un par ligne (§9.9)
│
└── temp/                                 ← tout le travail intermédiaire
    ├── journal_ocr.json                  ← un journal par étape, tous livres
    ├── journal_edition.json
    ├── journal_liminaires.json
    ├── journal_validation.json
    ├── journal_docx.json
    │
    └── Le Malentendu/                    ← un sous-dossier par livre
        ├── OCR_pages/                    ← cache étape 1
        │   ├── page_0001.txt
        │   ├── page_0001.json
        │   └── page_0002.txt
        ├── OCR.txt                       ← SORTIE étape 1
        │
        ├── EDIT_blocs/                   ← cache étape 2a
        │   ├── bloc_0001.txt
        │   └── bloc_0001.json
        ├── EDIT_raccords/                ← cache étape 2b
        │   ├── bloc_0001.txt
        │   └── raccord_0001.json
        ├── EDIT.txt                      ← SORTIE étape 2
        │
        ├── LIMINAIRES.json               ← SORTIE étape 2c (rôles seuls)
        │
        ├── REPORT_blocs/                 ← cache étape 3
        │   ├── bloc_0001.txt
        │   └── bloc_0001.json
        └── REPORT.txt                    ← SORTIE étape 3
```

**Le dossier principal ne montre que le PDF et le DOCX.** C'est une demande
explicite : avec une dizaine de pièces, la disposition à plat d'origine — où
chaque livre déposait cinq fichiers et quatre dossiers à la racine — rendait le
dossier Drive illisible.

Le changement est arrivé après que des livres avaient déjà été traités. Les
transcriptions existantes seraient devenues invisibles, donc refaites et
repayées. `io.migrer_livre()` déplace l'ancienne disposition vers la nouvelle,
et le notebook 01 comporte une section de migration à lancer une fois. Le
critère de reprise portant sur le contenu des sidecars et non sur leur
emplacement, la migration suffit à préserver l'intégralité du travail.

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
| `liminaires.py` | Étape 2c : `EDIT.txt` → `LIMINAIRES.json` | tout `utils` | oui | oui |
| `validation.py` | Étape 3 : → `REPORT.txt` | tout `utils` | oui | oui |
| `docx_export.py` | Étape 4 : `EDIT.txt` → `.docx` | `config`, `io`, `blocks` | **non** | oui |
| `repet_export.py` | Étape 4 : lignes classées → `REPET.json` | `config`, `io`, `blocks` | **non** | oui |
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
def recenser_personnages(texte: str) -> set[str]
    """Relève la distribution en tête d'ouvrage (règle 4 de §9.1)."""

def construire_index_structure(texte: str) -> IndexStructure
    """Applique les 8 règles de §9.1 + la passe C d'inférence de hiérarchie.
    Retourne, pour chaque label en gras, son type (ACTE / SCENE / PERSONNAGE)
    et le niveau de confiance du classement."""

def classifier_ligne(ligne: str, index: IndexStructure) -> TypeLigne
    """Classe une ligne à l'aide de l'index pré-calculé. Le passage par un
    index est nécessaire : le type d'un `**X.**` ne peut pas se décider
    localement, il dépend du document entier."""

def rapport_classification(index: IndexStructure) -> str
    """Table d'inspection lisible, affichée avant génération du DOCX."""

def decouper_en_runs(ligne: str) -> list[Run]                      # gras / italique inline
def assembler(textes: list[str]) -> str
```

Noter la séparation entre `construire_index_structure()` (une passe sur le
document entier) et `classifier_ligne()` (décision locale, instantanée). C'est
la conséquence directe de §9.1 : le type d'un label en gras est une propriété
**globale** du document, pas une propriété de la ligne.

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

### 5.5 bis `LIMINAIRES.json`

Sortie de l'étape 2c. **Ne contient aucun texte** — seulement des numéros de
ligne et des rôles :

```json
{
  "roles": {
    "0": "titre_oeuvre",
    "1": "titre_secondaire",
    "3": "epigraphe",
    "4": "attribution",
    "6": "distribution",
    "7": "entree_distribution"
  },
  "lignes_soumises": 9,
  "roles_refuses": [],
  "date_traitement": "2026-07-28T10:17:19",
  "modele": "gpt-5.5-2026-04-23",
  "response_id": "resp_abc123",
  "duree_secondes": 3.4,
  "tentative_reussie": 1,
  "tokens_entree": 612,
  "tokens_sortie": 48,
  "longueur_sortie": 97
}
```

Trois propriétés portées par ce format :

- **Ce fichier est à la fois la sortie et le sidecar.** Sa présence vaut
  `statut == "termine"` : un second lancement n'appelle rien. L'invariant de
  §7 tient donc sans fichier supplémentaire, l'unité de reprise étant le livre
  entier et non un fragment.
- **`roles_refuses` conserve les rôles inventés par le modèle.** Ils sont
  écartés à la lecture, mais consignés : un rôle rejeté en silence resterait
  introuvable, alors qu'il signale un prompt à corriger.
- **Les clés sont des chaînes**, JSON n'admettant pas de clé numérique.
  `charger_roles()` les reconvertit, et ignore toute valeur devenue inconnue
  plutôt que d'échouer — un rôle retiré de `config.py` après l'annotation ferait
  autrement échouer une étape 4 censée être infaillible.

L'étape 4 applique ces rôles **en comparant le contenu des lignes, non leur
numéro.** La classification peut scinder une ligne en deux paragraphes — une
réplique en ligne `**JAN.** Bonjour.` en produit deux — ce qui décale tous les
numéros suivants. Se fier à l'indice attribuerait le rôle à la mauvaise ligne.

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
STRUCTURE DÉTECTÉE (§9.1)
------------------------------------------------------------------------
Actes : 3     Scènes : 24     Personnages : 9
[ATTENTION]  1 classement incertain : « LA VOIX »
             → ajoutez-le à PERSONNAGES_FORCES si c'est un rôle

------------------------------------------------------------------------
BLOC 12 — pages 89 à 96
------------------------------------------------------------------------
[TEXTE RACCOURCI]     Réplique de MARTHA abrégée.
                      Vers « Je n'ai jamais eu le temps »
[DIDASCALIE PERDUE]   « Elle referme la porte » absente
                      Après la réplique de JAN, ~ligne 40
```

La section « structure détectée » figure dans `REPORT.txt` bien qu'elle concerne
l'étape 4. C'est délibéré : elle vous permet de repérer un problème de
classification **avant** de générer le DOCX, au moment où vous relisez déjà le
rapport. Un acte pris pour un personnage se verrait autrement à la première
page blanche parasite.

### 5.7 `<Livre>_REPET.json`

Seconde sortie de l'étape 4, destinée à `../outil_repetition/`. **Aucune IA,
aucun coût** : le fichier expose l'`IndexStructure` déjà construit pour le DOCX,
qui était jusqu'ici consommé puis jeté.

```json
{
  "schema": "repetition/2",
  "piece": "Le Malentendu",
  "genere_le": "2026-08-03T14:32:10",
  "outil": "outil_edition 1.0.0 — étape 4",
  "avertissements": [],
  "liminaires": [{ "type": "distribution", "texte": "PERSONNAGES" }],
  "personnages": [{ "nom": "JAN", "repliques": 84, "mots": 3120 }],
  "unites": [
    {
      "id": "u001",
      "acte": "ACTE PREMIER",
      "scene": "SCÈNE 2",
      "implicite": false,
      "personnages": ["JAN", "MARTHA"],
      "elements": [
        { "type": "lieu", "texte": "Une auberge. Le soir." },
        { "type": "replique", "id": "r_8f3a1c02d4e1", "personnages": ["JAN"],
          "texte": "Je t'attendais depuis une heure.", "vers": false,
          "didascalies_internes": [{ "avant_mot": 2, "texte": "elle se lève" }] },
        { "type": "replique", "id": "r_2b7e91a4c3d0", "personnages": ["JAN", "MARTHA"],
          "texte": "Chippendale ?", "vers": false }
      ]
    }
  ]
}
```

Six propriétés portées par ce format.

**L'unité de premier niveau est l'« unité jouable », pas l'acte.** Une liste
plate couvre les trois cas réels sans arborescence conditionnelle : la pièce
classique (`acte` et `scene` renseignés), la pièce contemporaine sans titre de
scène — où les `***` marquent les changements, d'où `implicite: true` — et le
texte d'un seul tenant. C'est aussi le grain dont l'outil de répétition a besoin
pour replier une scène.

**L'identifiant d'une réplique est une empreinte de son contenu**, jamais sa
position. Un `EDIT.txt` relu et corrigé décale toutes les positions ; des
identifiants positionnels feraient migrer silencieusement la progression d'une
réplique vers sa voisine. Le rang d'occurrence n'entre dans l'empreinte que s'il
est **non nul** : sinon, ajouter un second « Oui. » changerait l'identifiant du
premier, qui existait pourtant déjà.

**Le texte parlé est séparé des jeux de scène.** *elle se lève* ne se prononce
pas : la laisser dans `texte` ferait chuter le score de fidélité de toutes les
répliques portant une didascalie — c'est-à-dire les plus travaillées. La position
est donnée en mots (`avant_mot`), qui résiste au reflux, et non en caractères.

**`vers` se déduit du nombre de lignes.** L'étape 2 a déjà rejoint les retours à
la ligne mécaniques et ne conserve séparées que les lignes voulues ([§8](#8-la-convention-typographique--le-contrat-entre-les-étapes)) :
une réplique restée sur deux lignes l'est donc par décision, jamais par accident
de largeur de page. L'outil de répétition s'en sert pour ne pas recomposer un
vers comme de la prose.

**Rien n'est écarté en silence.** Une ligne de texte sans personnage annoncé est
conservée sous le type `texte_sans_personnage` *et* signalée dans
`avertissements`, qui remonte au rapport de l'étape. Le prototype de l'outil de
répétition, lui, concaténait ou jetait sans trace ce qu'il ne reconnaissait pas :
une réplique perdue y était indétectable.

`construire_repet()` ne porte **aucun champ de date** : deux appels sur le même
texte produisent des dictionnaires strictement égaux, ce qui rend le déterminisme
testable. `genere_le` est ajouté au moment de l'écriture.

**`personnages` d'une réplique est toujours une liste.** « SIR ROWLAND /
CLARISSA. » — ou, dans un document plus ancien, « SIR ROWLAND et CLARISSA. »
/ « X ET Y. » — joignent plusieurs personnages dans un même label, et le
texte est bien dit par tous — les séparer en répliques identiques fausserait
le compte. Le slash est la convention retenue pour l'écriture de nouvelles
répliques collectives ; « et »/« ET » reste reconnu pour ne pas casser les
documents déjà écrits ainsi. Un seul nom dans l'immense majorité des cas produit une
liste à un élément, ce qui laisse l'identifiant inchangé (§ ci-dessus, la
jonction d'une liste à un élément est ce nom-là). « TOUS. » est différent :
il ne nomme personne, et qui est en scène n'est pas su à ce stade. Il se
traduit par le joker `"*"` plutôt que par une énumération devinée, et ce
joker vaut pour n'importe quel rôle choisi côté `outil_repetition` — sans
jamais apparaître dans la distribution `personnages` de tête de document,
qui ne liste que des rôles qu'on peut effectivement choisir de jouer.

### 5.8 Journaux `journal_<etape>.json`

Voir [§12](#12-journalisation).

---

## 6. Flux des données, étape par étape

### Étape 1 — OCR

| | |
|---|---|
| **Entrée** | `<Livre>.pdf` |
| **Sortie** | `<Livre>_OCR.txt` |
| **Unité de reprise** | **la page** |
| **Modèle** | `MODEL_OCR` (`gpt-5.5-2026-04-23`) |
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
| **Sorties** | `<Livre>.docx` **et** `<Livre>_REPET.json` (§5.7) |
| **IA** | **aucune** |
| **Reprise** | sans objet (quelques secondes, entièrement local) |

1. Lire `EDIT.txt`.
2. **Construire l'index de structure** : relever la distribution, appliquer les
   8 règles et la passe d'inférence de hiérarchie (§9.1). Une seule passe sur le
   document entier.
3. **Afficher la table d'inspection** (§9.1) : vous voyez ce que le parseur a
   compris, et notamment les classements incertains, *avant* toute génération.
4. Classifier chaque ligne à l'aide de l'index.
5. Découper chaque ligne en runs (gras / italique inline, §9.2).
6. Construire le document avec les six styles nommés de [§9.3](#93-styles-docx),
   saut de page inséré avant chaque acte uniquement.
7. Écrire le `.docx` et `journal_docx.json`, en y consignant tout classement
   incertain.
8. **Écrire `<Livre>_REPET.json`** à partir des mêmes lignes classées (§5.7).

L'ordre 2 → 3 → 4 n'est pas négociable : le type d'un `**X.**` dépend du
document entier, il ne peut donc pas être décidé en lisant les lignes une à une.

L'ordre 7 → 8 ne l'est pas non plus, mais pour une autre raison. **Le DOCX est
enregistré avant la sortie de répétition**, parce que le document imprimé est la
raison d'être de l'étape et la seconde sortie un bénéfice annexe. Un défaut dans
le JSON ne doit donc coûter ni le DOCX, ni le statut du livre : `repet_export`
est appelé sous protection, et son échec devient un **avertissement**, pas une
erreur d'étape. Il est signalé pour autant — un JSON manquant en silence se
découvrirait sur le téléphone, un dimanche de filage.

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

Contrepartie assumée : cette grammaire ne distingue pas, à elle seule, un titre
d'acte, un titre de scène et un nom de personnage — les trois s'écrivant
`**…**` seuls sur leur ligne. C'est le prix de la lisibilité de `EDIT.txt`, et
c'est l'objet de [§9.1](#91-acte-scène-ou-personnage--la-classification-à-trois-niveaux).

---

## 9. Problèmes délicats et leur résolution

### 9.1 Acte, scène ou personnage : la classification à trois niveaux

C'est le problème central de l'étape 4, et votre exigence de saut de page en
fait un problème **critique** plutôt que cosmétique.

**Le problème.** Trois éléments de nature totalement différente s'écrivent de
façon **syntaxiquement indiscernable** — gras, seuls sur leur ligne, en
capitales :

```
**ACTE PREMIER**     ← acte      (niveau 1)
**SCÈNE 3**          ← scène     (niveau 2)
**UN.**              ← ??        (acte ou scène selon la pièce)
**JAN.**             ← personnage
```

**Pourquoi c'est critique.** Vous demandez un saut de page **avant chaque acte,
mais pas avant les scènes**. Une erreur de classification ne produit donc plus
un défaut invisible : elle produit une page blanche parasite au milieu d'un
acte, ou un acte qui ne commence pas sur une page neuve. Distinguer acte de
scène n'est plus une élégance, c'est une condition de fonctionnement.

#### Règle de décision, dans un ordre strict

L'erreur serait de compter les occurrences en premier. On mène au contraire avec
les signaux **non ambigus** (lexique, numérotation), et on ne recourt aux
statistiques qu'en dernier ressort.

| # | Condition | Classement | Confiance |
|---|---|---|---|
| 0 | Figure dans un override de `config.py` | forcé | **certaine** |
| 0 bis | Correspond à `ETIQUETTES_DISTRIBUTION` | **DISTRIBUTION** | certaine |
| 1 | Correspond à `LEXIQUE_ACTE` | **ACTE** | certaine |
| 2 | Correspond à `LEXIQUE_SCENE` | **SCÈNE** | certaine |
| 3 | Est un pur jeton de numérotation (`UN`, `II`, `3`, `PREMIÈRE`) | titre → passe C | déduite |
| 4 | Figure dans la liste de personnages relevée en tête d'ouvrage | **PERSONNAGE** | certaine |
| 5 | Est suivi au moins une fois d'une ligne de réplique | **PERSONNAGE** | probable |
| 6 | Apparaît ≥ `SEUIL_OCCURRENCES_PERSONNAGE` fois | **PERSONNAGE** | probable |
| 7 | Aucun des cas précédents | **PERSONNAGE** (défaut) | **incertaine** ⚠ |

**La règle 0 bis a été ajoutée après exécution des tests.** Sans elle,
`**PERSONNAGES**` — l'en-tête d'une distribution — est une ligne en gras suivie
d'une ligne ayant la forme d'une réplique (`JAN, le frère`) : la règle 5 en
faisait un rôle, ce qui faussait le décompte des personnages. Le classer comme
titre d'acte aurait été pire encore : la passe C aurait vu un acte lexical et
basculé *tous* les titres numérotés en scènes. D'où un type propre, neutre
vis-à-vis de la hiérarchie, et son propre style (§9.3).

**La règle 7 retient « personnage » et non « titre ».** Une version antérieure
classait ces labels comme actes — et leur infligeait donc un saut de page, soit
l'issue la plus voyante possible pour le cas où l'on sait le moins de choses.
Le cas typique est un rôle dont l'unique intervention est une didascalie
(`**LA VOIX**` suivi de `*Silence.*`), fréquent au théâtre contemporain. Avec
« personnage » par défaut, la dégradation est bénigne dans les deux sens : un
vrai titre reste centré et gras, et aucune page blanche parasite n'apparaît.

- `LEXIQUE_ACTE` : `ACTE`, `PARTIE`, `PROLOGUE`, `ÉPILOGUE`, `MOUVEMENT`,
  `JOURNÉE`, `INTERMÈDE`.
- `LEXIQUE_SCENE` : `SCÈNE`, `SCENE`, `TABLEAU`, `SÉQUENCE`, `FRAGMENT`.
- Comparaison sur une forme normalisée : capitales, sans accents, sans point
  final, espaces réduits. `ACTE PREMIER`, `Acte premier.` et `ACTE  I` sont donc
  reconnus identiquement.

**Pourquoi la règle 5 avant la règle 6.** Un personnage secondaire peut n'avoir
qu'une seule réplique dans toute la pièce (`**LE MESSAGER.**`). Un simple seuil
d'occurrences le classerait comme titre, et lui infligerait un saut de page. Le
critère « suivi d'une réplique » l'attrape correctement, car un titre n'est
jamais suivi d'une réplique : il est suivi d'un lieu en italique, ou d'un nom de
personnage.

**La règle 4 est le meilleur signal disponible.** Beaucoup d'éditions ouvrent sur
une distribution (`PERSONNAGES`, `PERSONNAGES :`, `DISTRIBUTION`). Quand elle
existe, `recenser_personnages()` l'analyse et alimente `personnages_connus` : la
classification devient alors quasi certaine pour tous les rôles, y compris ceux
qui ne parlent qu'une fois.

#### Passe C — résoudre le niveau d'un titre purement numéroté

Reste le cas de `**UN.**` : titre certain, mais acte ou scène ? Il se tranche par
l'**inférence de hiérarchie**, au niveau du document entier :

1. **Si des titres lexicaux `ACTE` existent** et que des titres numérotés
   existent aussi → les titres numérotés sont des **scènes** imbriquées.
2. **Si aucun titre lexical `ACTE` n'existe** → les titres numérotés
   constituent le niveau supérieur, donc des **actes**. C'est exactement le cas
   de votre prototype, dont le prompt nomme `**UN.**` un « titre de partie »,
   c'est-à-dire une division de premier niveau. ✅
3. **Détection de remise à zéro** : si la numérotation redémarre (1, 2, 3, 1, 2),
   il y a deux niveaux ; la série qui redémarre est le niveau interne (scènes).
4. **Départage par style de numérotation** : chiffres romains et nombres écrits
   en lettres → acte ; chiffres arabes → scène. Signal faible, utilisé en dernier.

Le point 2 mérite d'être souligné : dans une pièce contemporaine découpée en
`UN / DEUX / TROIS` avec des `***` comme séparateurs internes, il n'y a
**aucun titre de scène** — les `***` marquent les changements de scène. Traiter
`**UN.**` comme un acte est donc le bon résultat, et le saut de page tombe au
bon endroit.

#### Le filet de sécurité : rendre la classification visible et corrigeable

Aucune heuristique ne couvre toutes les pièces. Plutôt que de prétendre le
contraire, la classification est **inspectable et surchargeable**.

**1. Table d'inspection.** `rapport_classification()` produit un tableau affiché
dans le notebook `04_DOCX.ipynb` **avant** la génération, et repris dans
`REPORT.txt` :

```
LABEL             OCC.  SUIVI RÉPL.  CLASSÉ        CONFIANCE
ACTE PREMIER         1            0  ACTE          certaine (lexique)
SCÈNE 3              1            0  SCÈNE         certaine (lexique)
JAN                 84           84  PERSONNAGE    certaine (distribution)
LE MESSAGER          1            1  PERSONNAGE    probable (règle 5)
UN                   1            0  ACTE          déduite (passe C, cas 2)
LA VOIX              1            0  ACTE          INCERTAINE ⚠
```

Vous voyez donc, en une seconde et avant tout DOCX, ce que le parseur a compris —
et notamment les lignes ⚠ qui demandent votre arbitrage.

**2. Overrides dans `config.py`**, prioritaires sur toute heuristique :

```python
PERSONNAGES_FORCES  : set[str] = set()   # ex. {"LA VOIX", "LE MESSAGER"}
TITRES_ACTE_FORCES  : set[str] = set()
TITRES_SCENE_FORCES : set[str] = set()
```

Corriger la pièce la plus atypique devient l'ajout d'un mot dans un ensemble.

**3. Journalisation.** Chaque classement `INCERTAINE` est enregistré comme
avertissement dans `journal_docx.json`.

Toute cette logique vit dans `blocks.py`. Elle est **pure** — pas d'I/O, pas
d'API — donc entièrement couverte par `tests/test_blocks.py`, avec un cas de test
par règle et par cas de la passe C.

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

**Sept** styles de paragraphe créés programmatiquement — jamais de mise en forme
appliquée run par run, afin qu'une modification globale reste un changement d'une
seule ligne de `config.py`. Le style de titre est scindé en deux, conséquence
directe de §9.1 et du saut de page réservé aux actes.

| Style | Alignement | Graisse | Corps | Espacement | Saut de page |
|---|---|---|---|---|---|
| `Theatre_Titre_Acte` | centré | **gras** | **16 pt** | avant 0, après 24 pt | **oui** |
| `Theatre_Titre_Scene` | centré | **gras** | **14 pt** | avant 24, après 12 pt | non |
| `Theatre_Distribution` | centré | **gras** | 14 pt | avant 24, après 12 pt | non |
| `Theatre_Lieu` | centré | *italique* | 11 pt | avant 12, après 12 pt | non |
| `Theatre_Personnage` | centré | **gras** | **11 pt** | avant 12, après 0 pt | non |
| `Theatre_Didascalie` | centré | *italique* | 11 pt | avant 6, après 6 pt | non |
| `Theatre_Texte` | **justifié** | romain | 11 pt | après 6 pt | non |

Seuls les **titres** se détachent par le corps. Le nom de personnage reste à la
taille du texte : il se distingue par le gras et le centrage, jamais par la
taille. Son style référence directement `TAILLE_TEXTE_PT` plutôt qu'une
constante propre — c'est une relation voulue, non une coïncidence de valeurs, et
changer le corps entraînera le personnage avec lui.

`Theatre_Distribution` porte les mêmes valeurs que `Theatre_Titre_Scene`, mais
reste un style distinct : cela évite de fausser le décompte des scènes dans le
rapport, et permet de composer l'en-tête d'une liste de rôles en petites
capitales sans toucher aux titres de scène.

Communs à tous : EB Garamond, **aucune couleur** (on ne définit simplement
jamais `font.color`, la valeur héritée est le noir automatique).

Deux détails de mise en page qui comptent :

- L'espacement *avant* de `Theatre_Titre_Acte` est nul, puisque le style porte
  déjà un saut de page : un espacement avant, en haut d'une page neuve,
  produirait un décalage inutile.
- Le saut de page est implémenté via
  `paragraph_format.page_break_before = True` sur le **style**, et non par
  l'insertion d'un caractère de saut de page. Conséquence : passer
  `SAUT_DE_PAGE_AVANT_ACTE` à `False` ne laisse aucun résidu dans le document,
  et le premier acte du document ne crée pas de page blanche initiale (Word
  ignore un `page_break_before` sur le premier paragraphe).

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
   texte corrigé », « as an AI »… Détecte le bavardage et les refus de type
   assistant. « je ne peux pas » en a été écarté : c'est une réplique trop
   courante (« je ne peux pas te le dire »), et §9.7 capte déjà le vrai refus
   de transcription — au prix, sinon, de pages perdues.
3. **Parité des astérisques** (séparateurs `***` exclus) → détecte une
   astérisque orpheline — un balisage `*…*` ou `**…**` non refermé qui
   casserait l'étape 4. Le séparateur de scène `***`, impair mais parfaitement
   légitime, est retiré avant le comptage : sans cela, tout bloc contenant un
   nombre impair de séparateurs serait marqué suspect à tort, puis exclu
   d'`EDIT.txt` (corrigé le 2026-07-28, après un vrai appel d'édition).

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

### 9.6 Les pages liminaires : le seul endroit où l'IA est indispensable

Le problème est venu d'exemples réels. Les premières pages d'une édition
imprimée contiennent, dans un ordre variable, un titre d'œuvre, un nom
d'auteur, un sous-titre, une épigraphe, la source de cette épigraphe, une note
d'éditeur, un prologue et la liste des rôles.

Après l'étape 2, tous ces éléments s'écrivent **de la même façon** : en gras ou
en italique, centrés, seuls sur leur ligne. La convention de §8 les rend
indiscernables, par construction — elle a été conçue pour le corps de la pièce,
où trois catégories suffisent.

Aucune règle mécanique ne peut trancher. « Heiner Müller » sous une phrase en
italique est la source d'une épigraphe ; le même nom en tête de page est
l'auteur ; ailleurs, ce serait un personnage. La différence est **sémantique**,
et il n'existe pas d'indice typographique pour l'établir.

**Cinq pistes ont été évaluées avant d'écrire une ligne de code.**

| # | Proposition | Verdict |
|---|---|---|
| 1 | Détecter les déclarations d'échec du modèle | Retenue — corrigeait une corruption silencieuse observée (§9.7) |
| 2 | Marqueur pour écarter un livre déjà traité | Retenue — §9.9 |
| 3 | Faire produire à l'étape 1 une **seconde sortie décrivant la mise en page** | Retenue sous condition, puis restreinte |
| 4 | Demander au modèle d'OCR de séparer les noms d'une liste de rôles agglutinée | **Écartée** — cas de bord, et §9.8 le règle mieux |
| 5 | Une passe d'IA dédiée aux liminaires | Retenue — c'est l'étape 2c |

La proposition 3 méritait d'être retenue : un modèle vision *voit* le gras, le
centrage et la taille, et le dire ne coûte presque rien puisque l'appel est déjà
payé. Elle a néanmoins été restreinte pour une raison décisive : la mise en page
observée serait devenue **une seconde source de vérité**, en concurrence avec la
convention typographique. Un modèle rapportant « centré, grand » sur un nom de
personnage aurait pu remonter jusqu'à l'étape 4 et défaire une mise en page
voulue. L'observation reste utile pour les liminaires, où aucune règle n'existe
déjà ; elle est nuisible partout où une règle existe.

D'où la restriction retenue : **l'étape 2c ne voit que les premières lignes**,
plafonnées à `LIGNES_LIMINAIRES`, et ne rend **que des rôles**. Elle ne peut
donc pas contredire la convention sur le corps de la pièce, ni altérer une
seule lettre du texte.

Trois propriétés complètent la protection :

- **un appel par livre, mis en cache** — le coût est négligeable et ne croît
  pas avec la longueur de l'ouvrage ;
- **PyMuPDF fournit gratuitement l'information de mise en page** —
  `get_text("dict")` rend la taille exacte, le gras, l'italique et la position
  de chaque fragment, sans appel d'API. La proposition 3 était donc en partie
  déjà satisfaite, gratuitement ;
- **dégradation propre** — sans `LIMINAIRES.json`, l'étape 4 se comporte
  exactement comme avant. Un échec de cette étape ne bloque rien.

### 9.7 Page blanche, ou modèle qui renonce ?

Deux réponses inattendues du modèle d'OCR, de conséquences opposées.

**Une page blanche est normale** dans un livre imprimé. Le prompt impose une
mention exacte, mais un modèle paraphrase : « Cette page est vide. » Écrite
telle quelle dans `OCR.txt`, la phrase devenait du texte de la pièce.

**Une déclaration d'échec est tout autre chose.** Le message observé,
`Erreur - Impossible d'OCR cette page`, a été enregistré avec le statut
« terminé ». Trois conséquences, aucune signalée : le message entrait dans le
texte, la page n'était **jamais reprise** puisque son sidecar la déclarait
faite, et l'étape 3 comparait un `OCR.txt` déjà corrompu — donc ne pouvait rien
détecter.

Les deux cas sont donc reconnus séparément, et routés à l'opposé : une page vide
est conservée vide et comptée comme traitée ; une déclaration d'échec devient un
`PAGE_ECHOUEE`, retentée puis annoncée.

Le discriminant retenu pour l'échec n'est pas lexical mais **syntaxique :
l'objet du verbe**. C'est ce qui sépare « je ne peux pas lire cette page » d'une
réplique comme « je ne peux pas lire dans tes pensées ». Une première version
exigeait la préposition `à`, ce qui manquait « je ne peux pas lire cette page »
— la formulation la plus probable.

Une ambiguïté subsiste, tranchée délibérément : une page dont **tout** le
contenu déclare l'illisibilité est comptée comme un échec, même si un
personnage y parlait d'une lettre effacée. L'asymétrie des conséquences le
justifie — un échec est annoncé, donc corrigible à la main, tandis que l'erreur
inverse corrompt le texte en silence.

Enfin, la détection de blancheur est **locale et gratuite** : PyMuPDF rasterise
à `DPI_TEST_BLANCHEUR` (40) et compte les pixels sombres. Une page blanche ne
coûte alors aucun appel. Le seuil est volontairement sévère : manquer une page
blanche coûte un appel, sauter une page imprimée perdrait du texte.

### 9.8 Où s'arrête la liste des rôles

La distribution est lue **par position** : après l'étiquette (`PERSONNAGES`,
`PERSONNAGES ET DÉCORS`…), toute ligne lui appartient. Cette lecture est ce qui
permet de traiter une liste tenant sur un seul bloc, sans avoir à reconnaître
chaque nom. Sa contrepartie : il faut savoir où elle s'arrête.

Les critères d'arrêt initiaux — deux lignes vides, un séparateur, un titre
d'acte ou de scène — laissaient passer le cas le plus courant :

```
**PERSONNAGES**
Gilles Rimey.
Alphonsine Rouart.

**JAN.**
Bonjour.
```

`**JAN.**` ne correspondant à aucun critère, la lecture continuait : **le corps
entier de la pièce était classé « entrée de distribution »**.

Le critère décisif est **l'enchaînement sur une réplique**. Une entrée de
distribution n'en est jamais suivie — elle précède un autre nom, ou une ligne
vide. Un nom de personnage annonce toujours du texte. Ce même critère écarte les
faux noms extraits d'une liste en un seul bloc, où `**LIEU DE L'ACTION**`
devenait une amorce appliquée ensuite à chaque page du livre.

Limite assumée : une liste agglutinée sur une ligne — « LES TROIS DIEUX. SHEN
TÉ. WANG, marchand d'eau. » — ne fournit aucune amorce exploitable. Les séparer
demanderait de deviner où chaque nom finit. Le classement mécanique s'abstient
donc, ce qui est le bon arbitrage : une amorce fausse dégrade toutes les pages,
une amorce absente n'en dégrade aucune, les personnages restant reconnus par
leurs répliques.

### 9.9 Écarter un livre déjà traité

Deux ouvrages du dossier avaient été traités par un autre outil. Les relancer
aurait consommé des tokens pour rien.

**Décision : un fichier-liste unique sur le Drive**, `ignorer.txt`
(`NOM_FICHIER_IGNORER`), posé à côté des PDF. On y écrit un nom de livre par
ligne ; les lignes vides et celles ouvrant par `#` sont ignorées, ce qui permet
d'y laisser des commentaires. La comparaison est indulgente — casse et
extension `.pdf` neutralisées — car ce fichier est édité à la main.

Deux options ont été écartées. **Une liste dans `config.py`** supposerait un
commit — donc un aller-retour par le dépôt — pour chaque livre ajouté ou
retiré, alors que la décision se prend en regardant le Drive. **Un marqueur par
livre** (`<Livre>.ignorer`, la première version) se créait bien là où
l'information se trouve, mais l'éparpillait : pour savoir ce qui est écarté, il
fallait parcourir tout le dossier. Le fichier unique se lit d'un coup d'œil et
se gère toujours depuis le Drive, sans toucher au code.

La liste ne porte que des noms, sans raison individuelle : la garder minimale
la rend triviale à éditer. Un livre écarté est en revanche **toujours annoncé**
au lancement — écarté en silence, il serait indiscernable d'un livre oublié, et
la recherche partirait sur une fausse piste.

Le remplacement de l'ancien marqueur est **complet** : `<Livre>.ignorer` n'est
plus lu. S'il en subsiste sur le Drive, il est **signalé** au lancement plutôt
qu'ignoré en silence — sans quoi une exclusion faite avec l'ancien mécanisme
disparaîtrait, et le livre repartirait au traitement, donc serait repayé.

---

## 10. Choix techniques et justifications

| # | Décision | Alternatives écartées | Raison |
|---|---|---|---|
| **D1** | **PyMuPDF** (`pymupdf`) pour rasteriser | `pdf2image` | `pdf2image` exige le binaire système *poppler*, à installer via `apt` dans Colab : lent et fragile. PyMuPDF est un simple `pip install`, très rapide, et donne un contrôle fin du DPI. |
| **D2** | ~~Rasteriser toutes les pages sans jamais lire la couche texte~~ → **révisée**, voir §10.1 | rasterisation systématique | La prémisse d'origine — « sur un scan il n'y a pas de couche texte » — est fausse pour les PDF déjà passés à l'OCR par un scanner ou par Acrobat. La couche texte est désormais réutilisée **si elle passe des contrôles de qualité sévères**. |
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
| **D15** | Une **passe d'IA dédiée aux liminaires**, bornée aux premières lignes et ne rendant que des rôles | faire décrire la mise en page par l'étape 1 sur tout le livre ; ou étendre les règles déterministes | Les liminaires sont sémantiquement ambigus et typographiquement identiques (§9.6) : aucune règle ne peut les départager. Décrire la mise en page sur tout le livre créerait en revanche **une seconde source de vérité** concurrente de la convention de §8, capable de défaire une mise en page voulue. Borner la passe aux liminaires garde le bénéfice et supprime le risque. |
| **D16** | L'étape 2c est **facultative** : sans `LIMINAIRES.json`, l'étape 4 retombe sur ses règles | en faire une dépendance de l'étape 4 | Une étape d'IA sur le chemin critique du DOCX annulerait la propriété la plus utile de l'étape 4 — gratuite, déterministe, rejouable à volonté. Elle est donc lancée depuis le notebook 02, jamais depuis le 04. |
| **D17** | Les rôles s'appliquent **par comparaison du contenu**, non par numéro de ligne | indexation directe | La classification peut scinder une ligne en deux paragraphes (`**JAN.** Bonjour.`), ce qui décale tous les numéros suivants et attribuerait le rôle à la mauvaise ligne. |
| **D18** | Écarter un livre par **fichier marqueur sur le Drive** | liste de noms dans `config.py` | La décision se prend en regardant le Drive ; l'y inscrire évite un commit par livre ajouté ou retiré (§9.9). |
| **D19** | Une **déclaration d'échec du modèle** vaut `PAGE_ECHOUEE`, distincte d'une page vide | tout écrire dans `OCR.txt` | Sans cette distinction, « Erreur - Impossible d'OCR cette page » entrait dans le texte avec le statut « terminé » : jamais reprise, et indétectable par l'étape 3 qui comparait un `OCR.txt` déjà corrompu (§9.7). |
| **D20** | Travail intermédiaire rangé dans `temp/<Livre>/` | disposition à plat à la racine | Avec une dizaine de pièces, la racine devenait illisible. `migrer_livre()` déplace l'existant : le critère de reprise portant sur le contenu des sidecars et non sur leur emplacement, rien n'est repayé. |

### 10.1 Révision de D2 — réutiliser une couche texte existante

**Ce qui a changé.** D2 écartait toute lecture de la couche texte d'un PDF, au
motif que « sur un scan il n'y a pas de couche texte ». Cette prémisse est fausse
pour une partie réelle du corpus : beaucoup de PDF ont déjà été passés à l'OCR
par un scanner ou par Acrobat. Les repasser au modèle vision, c'est **payer deux
fois la même transcription**.

**Ce qui n'a pas changé.** La seconde moitié du raisonnement de D2 reste entière,
et c'est elle qui gouverne l'implémentation : une couche texte **n'est pas
forcément exploitable**. Un OCR ancien ou bas de gamme produit des accents
dépouillés, des ligatures non résolues, un ordre de lecture faux. Réutiliser une
mauvaise couche texte dégraderait tout le livre, puisque l'étape 2 a pour
consigne de ne pas réécrire l'auteur : une faute d'extraction deviendrait
définitive.

**L'asymétrie des risques dicte la conception.**

| Erreur | Conséquence |
|---|---|
| accepter à tort une mauvaise couche texte | livre dégradé, faute définitive |
| rasteriser à tort une bonne couche texte | quelques jetons dépensés |

Les contrôles de `blocks.evaluer_couche_texte()` sont donc **sévères**, et le
doute renvoie à l'OCR Vision : volume minimal par page, part de lettres, part de
caractères accentués — l'absence totale d'accents sur une page de français étant
le signal le plus fiable d'un OCR qui a dépouillé le texte — et part de
caractères de remplacement.

Trois compléments rendent la chose maîtrisable plutôt que magique :

- **`STRATEGIE_COUCHE_TEXTE`** vaut `"auto"` (contrôles appliqués), `"jamais"`
  (rasterisation systématique, comportement d'avant cette révision) ou
  `"toujours"` (confiance aveugle, à réserver aux PDF dont on connaît la
  provenance) ;
- **`ocr.diagnostiquer_couches_texte()`** recense, **sans aucun appel API**,
  combien de pages seront réellement facturées et **pourquoi** les autres sont
  écartées. C'est la réponse directe à « comment ne pas gaspiller de jetons » :
  on le sait avant de lancer ;
- le **sidecar de chaque page** porte `source: "vision"` ou
  `source: "couche_texte"`. La provenance reste donc vérifiable après coup, ce
  qui compte si le résultat final surprend.

**Un livre hybride est un cas normal**, non une anomalie : les pages à couche
texte exploitable la réutilisent, les autres passent à la vision. L'homogénéité
de qualité que D2 cherchait à préserver est garantie non par l'unicité du chemin,
mais par la sévérité du contrôle à l'entrée du chemin gratuit.

### 10.2 `LIMITE_PAGES`, et le piège qu'elle a révélé

`config.LIMITE_PAGES` plafonne le nombre de pages traitées par PDF, pour
éprouver les quatre étapes sur dix pages avant d'engager un livre entier.

Ce réglage a mis au jour **deux pertes de données silencieuses** qui existaient
déjà, et que rien n'aurait signalées.

**Le numéro d'un bloc ne l'identifie pas.** Il dépend du nombre de pages
présentes dans `OCR.txt`. Avec `PAGES_PAR_BLOC = 8` :

| | essai (10 pages) | livre entier (289 pages) |
|---|---|---|
| bloc 1 | pages 1–8 | pages 1–8 |
| bloc 2 | **pages 9–10** | **pages 9–16** |

Le bloc 2 de l'essai portait `statut: "termine"`. Au passage complet,
`editer_bloc()` le sautait — et **les pages 11 à 16 disparaissaient d'`EDIT.txt`
sans aucune alerte**. `bloc_deja_edite()` compare désormais les frontières
enregistrées à celles recalculées, et réédite tout bloc dont elles ont changé.

**Un bloc réédité laissait ses raccords périmés.**
`preparer_blocs_raccords()` ne recopie jamais par-dessus un fichier existant — à
raison, puisque ces fichiers portent les corrections de jonction déjà acquises.
Mais la copie d'un bloc réédité est obsolète, et c'est l'ancienne version qui se
retrouvait dans `EDIT.txt`. `invalider_raccords_voisins()` supprime donc la copie
du bloc et les sidecars des deux jonctions qui le touchent.

Vérifié de bout en bout : essai de 10 pages puis passage complet à 24 pages sur
un livre dont chaque page porte un marqueur unique — **24 pages sur 24 présentes
dans `EDIT.txt`, 14 appels OCR au second passage au lieu de 24**.

La leçon générale : un identifiant dérivé d'un découpage n'est stable que si le
découpage l'est. Partout où une unité est mise en cache, son sidecar doit porter
de quoi vérifier qu'elle recouvre bien ce qu'on croit.

---

## 11. Configuration

`config.py` — intégralité des constantes, aucune logique. **Toutes les valeurs
ci-dessous sont désormais validées** (voir §17).

```python
# ----- Emplacements ---------------------------------------------------
DOSSIER_DRIVE = Path("/content/drive/MyDrive/Troupe 122 - 2026-27")
SCAN_RECURSIF = False           # PDF à plat dans le dossier

# ----- Modèles (identifiants vérifiés sur le compte) ------------------
MODEL_OCR         = "gpt-5.5-2026-04-23"        # vision
MODEL_EDITION     = "gpt-5.5-2026-04-23"        # repris du prototype
MODEL_RACCORD     = "gpt-5.4-mini-2026-03-17"   # léger : voir note ci-dessous
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
STOCKER_REPONSES    = False     # → store=False (pièce sous droits)

# ----- Rasterisation PDF ---------------------------------------------
DPI_RASTERISATION    = 200
DPI_MINIMAL          = 110      # plancher en cas de dégradation
TAILLE_MAX_IMAGE_MO  = 18.0

# ----- Contrôles qualité ---------------------------------------------
RATIO_MINIMAL_LONGUEUR       = 0.80   # au lieu de 0.55 dans le prototype
RETRAITER_BLOCS_SUSPECTS     = True
SEUIL_OCCURRENCES_PERSONNAGE = 2

# ----- Classification structurelle (§9.1) ----------------------------
LEXIQUE_ACTE  = {"ACTE", "PARTIE", "PROLOGUE", "EPILOGUE",
                 "MOUVEMENT", "JOURNEE", "INTERMEDE"}
LEXIQUE_SCENE = {"SCENE", "TABLEAU", "SEQUENCE", "FRAGMENT"}

PERSONNAGES_FORCES  : set[str] = set()   # surcharges prioritaires
TITRES_ACTE_FORCES  : set[str] = set()
TITRES_SCENE_FORCES : set[str] = set()

# ----- Marqueurs (contrat inter-étapes, §5) --------------------------
MARQUEUR_PAGE     = "[PAGE {numero}]"
SEPARATEUR_PAGE   = "\n\n<<<PAGE_BREAK>>>\n\n"

# ----- DOCX -----------------------------------------------------------
POLICE_TEXTE            = "EB Garamond"
# Seuls les titres se détachent par le corps ; le personnage suit le texte.
TAILLE_TITRE_ACTE_PT    = 16
TAILLE_TITRE_SCENE_PT   = 14
TAILLE_TEXTE_PT         = 11
MARGE_CM                = 3.0
SAUT_DE_PAGE_AVANT_ACTE  = True    # actes seulement
SAUT_DE_PAGE_AVANT_SCENE = False

# ----- Suffixes de fichiers ------------------------------------------
SUFFIXE_OCR           = "_OCR.txt"
SUFFIXE_OCR_PAGES     = "_OCR_pages"
SUFFIXE_EDIT          = "_EDIT.txt"
SUFFIXE_EDIT_BLOCS    = "_EDIT_blocs"
SUFFIXE_EDIT_RACCORDS = "_EDIT_raccords"
SUFFIXE_REPORT        = "_REPORT.txt"
SUFFIXE_REPORT_BLOCS  = "_REPORT_blocs"
```

### 11.1 Note sur `MODEL_RACCORD` — une hypothèse corrigée

L'inventaire des modèles réellement disponibles sur votre compte a démenti mon
hypothèse implicite : **`gpt-5.5-mini` n'existe pas.** La famille 5.5 ne propose
que `gpt-5.5`, `gpt-5.5-2026-04-23`, `gpt-5.5-pro` et `gpt-5.5-pro-2026-04-23`.

Les variantes légères disponibles sont : `gpt-5.4-mini-2026-03-17`,
`gpt-5.4-nano-2026-03-17`, `gpt-5-mini`, `gpt-5-nano`, `gpt-4.1-mini`,
`gpt-4.1-nano`, `gpt-4o-mini`.

Je retiens **`gpt-5.4-mini-2026-03-17`** : c'est le mini le plus récent, donc le
plus proche de votre modèle d'édition en génération, et la tâche de raccord est
étroite — ressouder un mot coupé sur une fenêtre de 100 lignes, avec un format de
sortie délimité simple. L'identifiant est **daté**, donc figé : aucun risque
qu'une mise à jour d'alias change le comportement au milieu d'un livre.

Deux remarques d'inventaire, pour votre information :

- `gpt-5.6-luna`, `gpt-5.6-sol` et `gpt-5.6-terra` sont plus récents que 5.5,
  mais leur nomenclature ne permet pas d'inférer leur niveau ni leur coût, et
  aucun n'a de variante datée. Je ne les retiens pas sans que vous ayez confirmé
  ce qu'ils sont — changer de modèle d'édition en cours de livre créerait une
  hétérogénéité stylistique entre blocs.
- `gpt-5.5-2026-04-23` est bien présent : c'est le modèle retenu pour l'OCR,
  l'édition et la validation. `gpt-4o` reste disponible comme repli pour la
  vision (§11.2).

Le helper `lister_modeles_disponibles()` est néanmoins inclus dans
`utils/api.py` et appelable depuis les notebooks, afin que ce contrôle soit
reproductible sans quitter Colab.

### 11.2 Note sur `MODEL_OCR` — une déférence excessive, corrigée

`MODEL_OCR` valait initialement `gpt-4o`, parce que le cahier des charges
demandait « utiliser GPT-4o comme modèle OCR ». Cette contrainte a été reprise
sans être rediscutée, et elle laissait le pipeline dans un état incohérent :

| Étape | Modèle initial |
|---|---|
| OCR | `gpt-4o` ← **famille ancienne** |
| édition | `gpt-5.5-2026-04-23` |
| raccord | `gpt-5.4-mini-2026-03-17` |
| validation | `gpt-5.5-2026-04-23` |

L'OCR était le seul point resté sur un modèle ancien — et c'est le plus mal
choisi pour trois raisons cumulées. C'est l'étape **la plus nombreuse en appels**
(une par page), **la plus coûteuse**, et **celle dont tout le reste dépend** :
une erreur de transcription se propage, puisque l'étape 2 a pour consigne de ne
pas réécrire l'auteur. Une lettre mal lue devient une faute définitive.

`MODEL_OCR` vaut désormais **`gpt-5.5-2026-04-23`**, identifiant daté pour la
même raison qu'à l'édition : un alias non daté pourrait changer de comportement
au milieu d'un livre.

**Réserve levée le 2026-07-28.** Un test sur de vraies pages (deux pages d'un
scan sans couche texte, `LIMITE_PAGES = 2`) a confirmé que `gpt-5.5-2026-04-23`
accepte les entrées `input_image` : les deux pages ont été transcrites sans
erreur, et `store=False` a été honoré côté API — la réponse est introuvable par
son identifiant (404). `--verifier-modeles` ne contrôle toujours, lui, que
l'existence de l'identifiant, non l'acceptation des images : si un futur
changement de modèle refusait la vision, l'appel échouerait par un code **400**,
que `est_reessayable()` classe comme non réessayable — l'échec serait immédiat et
explicite, sans consommer les quatre tentatives ni ~38 secondes d'attente. Le
repli connu pour la vision reste `gpt-4o`.

C'est une raison de plus de commencer par un PDF de dix pages.

---

## 12. Journalisation

Un fichier par étape, à la racine de `DOSSIER_DRIVE`, structure identique :

```json
{
  "etape": "ocr",
  "derniere_execution": "2026-07-27T14:32:10",
  "configuration": {
    "modele": "gpt-5.5-2026-04-23",
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
      "modele": "gpt-5.5-2026-04-23",
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

Trois ajouts par rapport à votre spécification. **Les trois ont été acceptés**
(§17, décision n° 5) ; je conserve ci-dessous leur justification et le plan B
envisagé, pour que la trace de la décision subsiste.

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
| 1 | ✅ *fait* | Prototype préservé + `.gitignore` + `.gitattributes` |
| 2 | ✅ *fait* | `ARCHITECTURE.md`, puis révision après validation |
| 3 | ✅ *fait* | `config.py`, `__init__.py`, `requirements.txt` |
| 4 | ✅ *fait* | `utils/io.py`, `utils/logging.py` |
| 5 | ✅ *fait* | `utils/blocks.py` + `tests/test_blocks.py` |
| 6 | ✅ *fait* | `utils/api.py` (dont `lister_modeles_disponibles()`) |
| 7 | ✅ *fait* | les 4 fichiers `prompts/*.md` |
| 8 | ✅ *fait* | `ocr.py` |
| 9 | ✅ *fait* | `edition.py` |
| 10 | ✅ *fait* | `validation.py` |
| 11 | ✅ *fait* | `docx_export.py` + `tests/test_docx_export.py` |
| 12 | ✅ *fait* | `main.py` |
| 13 | ✅ *fait* | les 4 `.ipynb` |
| 14 | ✅ *fait* | `README.md`, déplacement du prototype dans `archive/` |

L'ordre n'est pas arbitraire : chaque commit ne dépend que des précédents, donc
le dépôt est cohérent à tout moment.

**Le commit 5 est le jalon à surveiller.** `blocks.py` porte la classification
acte / scène / personnage de §9.1, c'est-à-dire la logique la plus délicate du
projet, et il est **pur** — donc `tests/test_blocks.py` s'exécute en une seconde
sans clé API ni Drive monté. Je pourrai vous démontrer que la détection
fonctionne, cas par cas, **avant le premier appel facturé**. Si l'heuristique
doit être ajustée, c'est là que ça se verra, au moment le moins coûteux.

---

## 17. Décisions validées

Toutes les questions ouvertes ont été tranchées le 2026-07-27. Ce tableau est le
relevé de ces décisions ; il n'y a plus de point bloquant.

| # | Question | Décision retenue |
|---|---|---|
| 1 | Modèles des étapes IA | `gpt-5.5-2026-04-23` pour l'OCR, l'édition **et** la validation ; modèle léger pour le raccord seul |
| 2 | Identifiant du modèle léger | **`gpt-5.4-mini-2026-03-17`** — `gpt-5.5-mini` n'existe pas (§11.1) |
| 3 | `RATIO_MINIMAL_LONGUEUR` | **`0.80`**, au lieu de `0.55` dans le prototype |
| 4 | `STOCKER_REPONSES` | **`False`** — aucune perte de fonctionnalité, plus prudent pour une pièce sous droits |
| 5 | Les trois ajouts de §14 | **Les trois acceptés** : `utils/api.py`, dossiers de cache, `tests/` |
| 6 | Rangement des PDF | **À plat** dans `Troupe 122 - 2026-27` ⇒ `SCAN_RECURSIF = False` |
| 7 | Saut de page | **Avant chaque acte uniquement**, pas avant les scènes |
| 8 | Corps des titres | **Acte 16 pt, scène 14 pt** ; personnage et texte 11 pt |
| 9 | Discerner acte / scène / personnage | Exigence explicite ⇒ **classification à trois niveaux** (§9.1), refonte complète |
| 10 | Rangement du Drive | Le dossier principal ne montre que PDF et DOCX ; tout le reste dans `temp/<Livre>/`, avec migration de l'existant (D20) |
| 11 | Mise en forme des pages liminaires | **Étape 2c** : une passe d'IA dédiée, un appel par livre, bornée aux premières lignes et ne rendant que des rôles (D15, §9.6) |
| 12 | Couche de mise en page produite par l'OCR | **Écartée hors liminaires** — seconde source de vérité concurrente de la convention typographique (D15) |
| 13 | Séparer les noms d'une liste de rôles agglutinée | **Écartée** — cas de bord, mieux traité par §9.8 et l'étape 2c |
| 14 | Livres déjà traités ailleurs | **Fichier marqueur sur le Drive** plutôt qu'une liste dans `config.py` (D18, §9.9) |

### 17.1 L'exigence qui a le plus changé la conception

La demande « discerner les titres des actes, des titres de scènes et des noms
des personnages » n'était pas un détail de confort : **elle interagit
directement avec la décision n° 7.**

Ma conception initiale ne distinguait que *titre* et *personnage*, en s'appuyant
sur un argument de faible risque — les deux se rendant « centrés gras », une
erreur de classification restait invisible. Cet argument **tombe** dès lors
qu'un saut de page est réservé aux actes : une erreur produit désormais une page
blanche au milieu d'un acte, ou un acte qui n'ouvre pas sur une page neuve.

Trois conséquences, toutes intégrées :

1. **§9.1 entièrement refondu** : règle de décision ordonnée à 8 niveaux menant
   avec les signaux non ambigus (lexique, numérotation, distribution) plutôt
   qu'avec le comptage d'occurrences, plus une passe d'inférence de hiérarchie
   pour les titres purement numérotés comme `**UN.**`.
2. **Six styles DOCX au lieu de cinq** (§9.3), `Theatre_Titre_Acte` et
   `Theatre_Titre_Scene` étant désormais distincts.
3. **Un filet de sécurité explicite** : table d'inspection affichée avant
   génération, trois ensembles d'overrides dans `config.py`, et journalisation
   de tout classement incertain. Une heuristique qui se donne à voir et se
   laisse corriger vaut mieux qu'une heuristique qu'on affirme parfaite.

### 17.2 Un point resté ouvert, non bloquant

`gpt-5.6-luna`, `gpt-5.6-sol` et `gpt-5.6-terra` sont disponibles sur votre
compte et plus récents que `gpt-5.5`. Leur nomenclature ne permet pas d'inférer
leur niveau de capacité ni leur coût. Je ne les retiens pas par défaut, mais si
l'un d'eux correspond à un modèle d'édition supérieur, il suffira de changer
`MODEL_EDITION`. À ne faire **qu'entre deux livres**, jamais au milieu d'un :
mélanger deux modèles d'édition sur un même texte introduirait une hétérogénéité
stylistique entre les blocs, précisément ce que la passe de raccord ne sait pas
rattraper.

---

### 17.3 Ce qu'un usage réel a corrigé

Les décisions 10 à 14 ne viennent pas de la conception mais de **pages de livres
réels** soumises après la première livraison : Kelly, Koltès, Shakespeare,
Brecht, Kermann, et un recueil en vers libres. Trois d'entre elles corrigent des
défauts que les 346 tests initiaux ne pouvaient pas voir, faute d'avoir jamais
rencontré la disposition en cause.

Le plus instructif est le défaut de §9.8 : la liste des rôles avalait le corps
entier de la pièce. Il était présent depuis l'origine, dans du code entièrement
testé — mais aucun test ne faisait suivre une liste de rôles par une réplique
sans titre d'acte intermédiaire. La disposition la plus courante des éditions
françaises était précisément celle qu'aucun cas de test ne décrivait.

D'où une conclusion de méthode, appliquée depuis : **écrire les cas de test
depuis des pages imprimées**, non depuis la convention. La convention est ce que
le code sait déjà traiter ; les livres sont ce qu'il doit traiter.

---

*Architecture validée le 2026-07-27. Implémentation achevée le 2026-07-28 :*
*les 14 commits du plan de livraison sont livrés, plus l'étape 2c et les*
*corrections issues de l'usage réel. 551 tests au vert.*
