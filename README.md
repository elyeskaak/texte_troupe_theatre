# theatre_editor

Pipeline d'édition de pièces de théâtre : **scans PDF → DOCX propre**, conçu
pour tourner dans Google Colab et traiter des livres entiers.

```
Pièce.pdf ──▶ Pièce_OCR.txt ──▶ Pièce_EDIT.txt ──▶ Pièce_REPORT.txt
              (OCR Vision)      (édition +          (contrôle qualité)
                                 raccord)                  │
                                     │                     │
                                     ├──▶ LIMINAIRES.json  │
                                     │    (rôles des       │
                                     │     premières pages)│
                                     │         │           │
                                     └──▶ Pièce.docx ◀─────┘
                                          (sans IA)
```

Chaque étape est **indépendante** et **reprenable**. Si Colab coupe au milieu
d'un livre de 300 pages, relancer la même cellule reprend exactement là où le
travail s'était arrêté : une coupure coûte au maximum **un appel API**.

---

> **Première utilisation ?** Suivez le [**tutoriel pas à pas**](TUTORIEL.md) :
> chemins de clics, ce qui doit s'afficher à chaque cellule, et un tableau de
> dépannage. Aucune connaissance technique supposée.

## Démarrage rapide

### 1. Déposer les PDF sur le Drive

```
MyDrive/Troupe 122 - 2026-27/
    Le Malentendu.pdf
    Les Justes.pdf
```

Le pipeline y ajoutera les DOCX, et rangera tout le travail intermédiaire dans
`temp/<Nom du livre>/` — le dossier principal reste donc lisible.

**Écarter un livre déjà traité.** Déposez à côté du PDF un fichier vide nommé
`<Nom du livre>.ignorer` : le pipeline le passera sous silence, en annonçant au
lancement qu'il l'a écarté et pourquoi. Écrivez la raison dans le fichier, elle
sera reprise dans l'annonce.

```
MyDrive/Troupe 122 - 2026-27/
    Le Malentendu.pdf
    Les Justes.pdf
    Les Justes.ignorer      ← « déjà traité par l'ancien logiciel »
```

Rien à modifier dans le code, et l'opération est réversible : supprimez le
marqueur, le livre repart au traitement. Un livre écarté est **toujours
annoncé** — écarté en silence, il serait indiscernable d'un livre oublié.

### 2. Renseigner la clé API dans Colab

Panneau latéral **🔑 Secrets** → ajouter `OPENAI_API_KEY` → activer « Accès au
notebook ». La clé n'apparaît jamais dans le notebook ni dans ses sorties.

Le dépôt étant public, **aucun jeton GitHub n'est nécessaire**. La cellule de
récupération du code en accepte néanmoins un, sous le nom `GITHUB_TOKEN`, au cas
où le dépôt redeviendrait privé : elle le détecte alors automatiquement, et
capture les sorties de `git` pour que l'URL qui le contient n'apparaisse jamais
dans un message d'erreur.

### 3. Commencer par un essai sur dix pages

Sur tout nouveau livre, réglez dans le notebook 01 :

```python
config.LIMITE_PAGES = 10
```

Éprouver la chaîne entière sur dix pages coûte quelques centimes et révèle les
mauvaises surprises — couche texte trompeuse, structure mal reconnue — avant
d'engager trois cents pages. Les pages transcrites sont **conservées et
réutilisées** au passage complet : rien n'est perdu, rien n'est repayé.

Remettez ensuite `LIMITE_PAGES = None` et relancez. Vous verrez alors :

```
[ALERTE]  bloc 2 : frontières changées (pages 9–10 → 9–16), réédition
```

C'est normal et voulu. Avec des blocs de 8 pages, l'essai produit un bloc 2 de
2 pages là où le livre entier en attend 8 : l'étape 2 compare les frontières
enregistrées à celles recalculées et réédite le bloc concerné. Sans ce contrôle,
les pages 11 à 16 disparaîtraient silencieusement d'`EDIT.txt`.

### 4. Ouvrir les notebooks, dans l'ordre

| Notebook | Étape | Durée indicative (300 pages) | Coût |
|---|---|---|---|
| [`01_OCR.ipynb`](notebooks/01_OCR.ipynb) | Transcription des pages | 20 à 30 min | le plus élevé |
| [`02_Edition.ipynb`](notebooks/02_Edition.ipynb) | Correction + raccord + liminaires | 15 à 25 min | modéré |
| [`03_Verification.ipynb`](notebooks/03_Verification.ipynb) | Contrôle qualité | 10 à 20 min | modéré |
| [`04_DOCX.ipynb`](notebooks/04_DOCX.ipynb) | Mise en forme | quelques secondes | **gratuit** |

Vérifiez le dossier de travail dans la cellule de configuration avant de lancer.

### En ligne de commande

```bash
python -m theatre_editor.main --etape tout
python -m theatre_editor.main --etape docx --dossier ./essai
python -m theatre_editor.main --verifier-modeles
```

L'enchaînement s'arrête à la première étape incomplète : poursuivre ferait
travailler la suivante sur des données partielles.

---

## Ce que fait chaque étape

### Étape 1 — OCR Vision

Rasterise chaque page avec PyMuPDF et la soumet à un modèle vision.
**Le modèle ne corrige rien** : il transcrit ce qu'il voit, sans mise en forme.

Ce n'est pas de la prudence excessive. `OCR.txt` reste brut afin de servir de
**référence de vérité** à l'étape 3 : si l'OCR corrigeait déjà, il n'existerait
plus aucun texte permettant de détecter ce que l'édition aurait perdu.

#### PDF déjà OCRisés : ne pas payer deux fois

Beaucoup de PDF portent déjà une couche texte, posée par un scanner ou par
Acrobat. Le pipeline la **réutilise telle quelle** quand elle est de bonne
qualité : aucun appel API pour ces pages.

Mais une couche texte n'est pas forcément bonne — accents dépouillés, ligatures,
ordre de lecture faux. Et les deux erreurs possibles n'ont pas le même prix :

| Erreur | Conséquence |
|---|---|
| accepter une mauvaise couche texte | **livre dégradé**, faute définitive |
| rasteriser une bonne couche texte | quelques jetons dépensés |

Les contrôles sont donc **sévères** et le doute renvoie à la vision. Avant de
lancer quoi que ce soit, le notebook 01 affiche un diagnostic **entièrement
gratuit** :

```
Le Malentendu
   pages totales           289
   couche texte utilisable 271
   à passer à l'OCR         18
   part sans appel API      94 %

   couches texte écartées, par motif :
     14  couche texte trop courte
      4  aucun accent ou presque
```

Trois stratégies, dans `config.py` :

```python
STRATEGIE_COUCHE_TEXTE = "auto"      # contrôles appliqués — recommandé
                       # "jamais"    # toujours l'OCR Vision
                       # "toujours"  # confiance aveugle, PDF de provenance sûre
```

Le sidecar de chaque page porte `source: "vision"` ou `source: "couche_texte"` :
la provenance reste vérifiable après coup.

### Étape 2 — Édition OCR

Deux passes. D'abord l'édition par blocs de 8 pages : correction des erreurs de
reconnaissance et application de la convention typographique. Puis la **passe de
raccord**, qui examine chaque jonction entre blocs — 50 dernières lignes à
gauche, 50 premières à droite — et ne peut que ressouder un mot coupé, supprimer
un doublon ou rétablir une didascalie.

Le texte de l'auteur n'est jamais réécrit.

### Étape 2 bis — Rôles des pages liminaires

Lancée depuis le même notebook, juste après l'édition. **Un seul appel par
livre**, mis en cache.

Les premières pages d'une édition imprimée — titre, auteur, épigraphe et sa
source, note d'éditeur, liste des rôles, prologue — sont typographiquement
indiscernables les unes des autres : toutes en gras ou en italique, centrées,
seules sur leur ligne. Aucune règle mécanique ne peut les départager. Un modèle
les annote une fois pour toutes dans `LIMINAIRES.json`.

Cette passe **ne touche pas au texte** : elle ne produit que des rôles, et
uniquement pour les premières lignes. Son échec n'empêche pas de produire le
DOCX — la mise en forme retombe alors sur les règles déterministes, exactement
comme si l'étape n'existait pas.

### Étape 3 — Contrôle qualité

Compare `OCR.txt` et `EDIT.txt`. **Le texte n'est jamais modifié** : cette étape
produit un diagnostic, pas une correction. Une boucle de réparation automatique
serait la porte ouverte à la réécriture.

Deux familles de contrôles. Les **mécaniques** — volume conservé, lignes non
vides, personnages présents de part et d'autre, convention intacte — sont
gratuites, instantanées et déterministes. Les **sémantiques**, bloc par bloc,
cherchent ce qu'aucune règle ne voit : une didascalie perdue, une réplique
abrégée, un raccord mal ressoudé.

### Étape 4 — Génération DOCX

**Aucune IA, aucune clé API, aucun coût.** Uniquement `python-docx` et la
convention typographique. Deux exécutions produisent le même document :
régénérez autant que vous voulez après avoir ajusté une marge.

---

## La convention typographique

C'est le pivot du projet : elle rend l'étape 4 entièrement déterministe.

| Élément | Écriture dans `EDIT.txt` |
|---|---|
| Titre d'acte ou de scène | `**ACTE PREMIER**` |
| Lieu, description initiale | `*Une auberge. Le soir.*` |
| Nom de personnage | `**JAN.**` |
| Réplique | ligne nue sous le personnage |
| Didascalie | `*Pause.*` |
| Didascalie intercalée | `Bonjour *il sourit* ça va ?` |
| Séparateur de scène | `***` |
| Passage illisible | `*[texte illisible]*` |

`EDIT.txt` reste donc **lisible et corrigeable à la main** — ce qui compte, car
c'est le fichier que vous relirez.

Cette convention a une limite assumée : elle ne distingue pas les éléments des
**pages liminaires**, qui s'écrivent tous `**en gras**` ou `*en italique*`. C'est
l'étape 2 bis qui les départage, et elle seule.

---

## Acte, scène ou personnage ?

`**ACTE PREMIER**`, `**SCÈNE 2**` et `**JAN.**` sont syntaxiquement
indiscernables : gras, seuls sur leur ligne, en capitales. Or le DOCX n'insère un
saut de page **que devant les actes** — une erreur de classification produirait
donc une page blanche au milieu d'un acte.

La distinction repose sur une règle ordonnée qui mène avec les signaux non
ambigus : surcharges manuelles, lexique (`ACTE`, `SCÈNE`, `TABLEAU`…),
numérotation, puis la distribution relevée en tête d'ouvrage. Les critères
statistiques ne viennent qu'ensuite — un simple seuil d'occurrences classerait
`**LE MESSAGER.**`, rôle à réplique unique, comme un titre.

Pour un titre purement numéroté comme `**UN.**`, le niveau s'infère du document
entier : s'il n'existe aucun `ACTE` lexical, ces titres *sont* le premier niveau.

**Rien de tout cela n'est infaillible, et c'est pourquoi la classification est
donnée à voir.** Le notebook 04 affiche une table d'inspection avant toute
génération :

```
LABEL                     OCC.  RÉPL.  CLASSÉ        CONFIANCE
------------------------------------------------------------------------
ACTE PREMIER                 1      0  titre_acte    certaine (lexique acte)
SCÈNE 2                      1      0  titre_scene   certaine (lexique scène)
JAN.                         2      2  personnage    certaine (distribution)
LE MESSAGER.                 1      1  personnage    probable (règle 5)
LA VOIX                      1      0  personnage    incertaine ⚠
```

Un `⚠` se corrige en une ligne, dans `config.py` :

```python
TITRES_ACTE_FORCES = frozenset({"LA VOIX"})
```

---

## Reprise après interruption

Toute unité de travail — une page, un bloc, une jonction — possède un fichier de
contenu et un **sidecar JSON**. Le sidecar est *toujours* écrit après le contenu,
et une unité n'est terminée que si son sidecar porte `"statut": "termine"`.

| Moment de la coupure | État sur le disque | Décision à la reprise |
|---|---|---|
| avant le `.txt` | rien | refaire |
| entre `.txt` et `.json` | `.txt` orphelin | refaire |
| après le `.json` | les deux | sauter |

Aucun cas ne produit un travail perdu ni un travail faussement validé. Les
écritures passent par un fichier temporaire puis `os.replace()`, si bien qu'un
lecteur ne voit jamais un fichier à moitié écrit — situation autrement fréquente
sur un Drive monté en FUSE.

---

## Organisation

```
theatre_editor/
    config.py            toutes les constantes, aucune logique
    prompts/             les 5 prompts, en Markdown
    utils/
        io.py            chemins, écriture atomique, reprise
        blocks.py        logique texte PURE — testable sans rien installer
        logging.py       console et journaux JSON
        api.py           Responses API, réessais
    ocr.py               étape 1
    edition.py           étape 2
    liminaires.py        étape 2 bis — un appel par livre
    validation.py        étape 3
    docx_export.py       étape 4 — aucune IA
    main.py              orchestration CLI

notebooks/               interfaces Colab (générées par outils/)
tests/                   538 tests
archive/                 prototype d'origine, conservé
ARCHITECTURE.md          conception détaillée et justifiée
```

Le code métier vit **entièrement** dans le paquet. Les notebooks montent le
Drive, surchargent la configuration et appellent une fonction — rien de plus.

---

## Configuration

Tout se règle dans [`config.py`](theatre_editor/config.py). Aucun nombre magique
ailleurs dans le code.

```python
DOSSIER_DRIVE           = Path("/content/drive/MyDrive/Troupe 122 - 2026-27")

MODEL_OCR               = "gpt-5.5-2026-04-23"   # vision
MODEL_EDITION           = "gpt-5.5-2026-04-23"
MODEL_RACCORD           = "gpt-5.4-mini-2026-03-17"   # léger : tâche étroite
MODEL_VALIDATION        = "gpt-5.5-2026-04-23"
MODEL_LIMINAIRES        = "gpt-5.5-2026-04-23"

PAGES_PAR_BLOC          = 8
LIGNES_LIMINAIRES       = 120     # plafond soumis à l'étape 2 bis
RATIO_MINIMAL_LONGUEUR  = 0.80    # détection de troncature
SUFFIXE_IGNORER         = ".ignorer"

POLICE_TEXTE            = "EB Garamond"
TAILLE_TITRE_ACTE_PT    = 16
TAILLE_TITRE_SCENE_PT   = 14
TAILLE_TEXTE_PT         = 11
MARGE_CM                = 3.0
SAUT_DE_PAGE_AVANT_ACTE = True
```

Les prompts se modifient dans [`theatre_editor/prompts/`](theatre_editor/prompts/),
**sans toucher au Python**. Voir le [README des prompts](theatre_editor/prompts/README.md)
pour les contrats à ne pas rompre.

### Deux réglages à ne pas changer en cours de livre

`PAGES_PAR_BLOC` — les blocs déjà édités ne seraient plus alignés, et l'étape 3
refuserait de valider plutôt que de produire un rapport faux.

Le **modèle d'édition** — deux modèles sur un même texte produiraient des blocs
stylistiquement hétérogènes, ce que la passe de raccord ne rattrape pas.

---

## Tests

```bash
python -m unittest discover -s tests -t .
```

**538 tests, environ 20 secondes.** Aucune clé API, aucun Drive monté, aucun appel
réseau : `openai` et `pymupdf` sont remplacés par des doublures, et les modules
concernés diffèrent leur import pour rendre cela possible.

`python-docx` est en revanche utilisé pour de vrai — les tests génèrent de
véritables fichiers DOCX et les relisent, ce qui est bien plus solide que de
vérifier des appels sur une doublure. Le module est ignoré si la bibliothèque
est absente.

`utils/blocks.py` concentre la logique la plus délicate et sa **pureté est
vérifiée par analyse AST** : aucun import d'`os`, `time`, `openai` ou `docx`.

---

## Coût et durée

Pour un livre de 300 pages, à titre indicatif :

| Étape | Appels | Part du coût |
|---|---|---|
| OCR | 300 (un par page) | dominante |
| Édition | ~38 blocs | modérée |
| Raccord | ~37 jonctions | faible (modèle léger) |
| Liminaires | 1 (par livre, mis en cache) | négligeable |
| Validation | ~38 blocs | modérée |
| DOCX | 0 | nulle |

Les journaux `journal_*.json` consignent la consommation de jetons de chaque
appel : le notebook affiche le total, ce qui permet d'estimer le coût réel avant
de lancer le livre suivant.

Deux façons de réduire la dépense. Augmenter `PAGES_PAR_BLOC` diminue le nombre
d'appels d'édition, au prix d'un risque de troncature accru. Sauter l'étape 3
est possible — elle ne se trouve pas sur le chemin critique vers le DOCX — mais
c'est renoncer à savoir ce que l'édition aurait perdu.

---

## Limites connues

**La police EB Garamond n'est pas incorporée.** `python-docx` inscrit son nom
dans le document ; si elle est absente de la machine qui ouvre le fichier, Word
substituera. Installez-la sur votre poste — elle est gratuite sur Google Fonts.

**Une ligne devient un paragraphe.** C'est voulu : la convention conserve les
ruptures dramaturgiques. Conséquence, un mot coupé entre deux blocs doit être
ressoudé **entièrement d'un seul côté** par la passe de raccord, ce que le
prompt impose explicitement.

**La vision de `MODEL_OCR` n'a pas encore été éprouvée.**
`--verifier-modeles` contrôle qu'un identifiant de modèle existe, non qu'il
accepte les entrées image. Si `gpt-5.5-2026-04-23` refusait la vision, l'étape 1
échouerait dès le premier appel par un code 400 — immédiatement et
explicitement, sans consommer les quatre tentatives. Le repli est alors
`MODEL_OCR = "gpt-4o"`, en une ligne. Raison de plus pour commencer par un PDF
de dix pages.

**Les contrôles mécaniques sont conservateurs.** Ils préfèrent manquer un rôle
disparu plutôt que d'en signaler un à tort : un rapport bruyant ne serait pas
lu. La passe sémantique couvre ce qu'ils laissent passer.

**Une distribution imprimée en un seul bloc ne fournit aucune amorce.** Quand
tous les rôles tiennent sur une même ligne — « LES TROIS DIEUX. SHEN TÉ. WANG,
marchand d'eau. » — les séparer demanderait de deviner où chaque nom finit. Le
classement mécanique s'abstient donc plutôt que de risquer un faux nom, qui
serait autrement appliqué à chaque page du livre. Les personnages restent
reconnus par leurs répliques, et l'étape 2 bis identifie la liste elle-même.

**Une page dont tout le contenu se déclare illisible est comptée comme un
échec**, même si un personnage y parlait d'une lettre effacée. Le choix est
délibéré : un échec est annoncé au récapitulatif, donc visible et corrigible,
tandis que l'erreur inverse écrirait le message d'erreur du modèle dans le texte
de la pièce, sans rien signaler.

---

Conception détaillée, décisions techniques et alternatives écartées :
[`ARCHITECTURE.md`](ARCHITECTURE.md).
