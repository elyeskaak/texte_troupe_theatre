# Tutoriel pas à pas

Guide complet pour lancer le pipeline, en partant de zéro. Aucune connaissance
technique supposée.

Comptez **20 minutes** pour la préparation, à faire une seule fois. Ensuite,
lancer un livre prend trois clics.

---

## 1. La carte : qui fait quoi

C'est le seul point à bien comprendre avant de commencer. Trois endroits
distincts, chacun avec son rôle.

```
   ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
   │     GITHUB      │     │  GOOGLE COLAB   │     │  GOOGLE DRIVE   │
   │                 │     │                 │     │                 │
   │   LE CODE       │────▶│  LA MACHINE     │◀───▶│   VOS FICHIERS  │
   │                 │     │                 │     │                 │
   │ texte_troupe_   │     │ ordinateur      │     │ Troupe 122 -    │
   │ theatre         │     │ temporaire      │     │ 2026-27/        │
   │                 │     │ chez Google     │     │                 │
   │ permanent       │     │ ÉPHÉMÈRE        │     │ permanent       │
   └─────────────────┘     └─────────────────┘     └─────────────────┘
```

**GitHub** contient le programme. Il ne contient **aucun** de vos PDF ni de vos
textes. C'est là que les corrections et améliorations arrivent.

**Colab** est un ordinateur prêté par Google, dans le navigateur. Il est
**effacé à chaque fois** que vous fermez la session. Rien de ce qui y est écrit
ne survit — c'est pourquoi tout est sauvegardé sur le Drive au fur et à mesure.

**Drive** contient vos PDF et reçoit toutes les sorties. C'est le seul endroit
qui garde vos données.

> **La conséquence à retenir :** si Colab se déconnecte en pleine exécution,
> vous ne perdez rien. Le travail déjà fait est sur le Drive. Vous relancez, et
> ça reprend où ça s'était arrêté.

---

## 2. Checklist de préparation

À faire une fois. Cochez au fur et à mesure.

- [ ] Une clé API OpenAI (§3)
- [ ] Enregistrée dans les Secrets de Colab (§5)
- [ ] Vos PDF déposés dans le bon dossier du Drive (§4)

Le dépôt étant **public**, aucun jeton GitHub n'est nécessaire.

---

## 3. Créer la clé OpenAI

C'est la seule chose à créer. Elle sert à payer les appels aux modèles.

1. Allez sur **platform.openai.com**, connectez-vous.
2. Menu de gauche → **API keys**.
3. **Create new secret key**. Donnez-lui un nom, par exemple `theatre`.
4. **Copiez la clé** (elle commence par `sk-`). Elle ne sera plus affichée
   ensuite : collez-la temporairement dans un bloc-notes.

> **Vérifiez votre crédit** au passage : menu **Billing**. Sans crédit, les
> appels échouent avec une erreur de facturation, et le pipeline s'arrête.

Le dépôt de code étant **public**, aucun jeton GitHub n'est nécessaire. Si vous
le repassiez un jour en privé, la cellule de récupération du code accepte un
secret `GITHUB_TOKEN` et l'utilise automatiquement, sans rien à modifier.

---

## 4. Ranger vos PDF sur le Drive

Dans votre Google Drive, créez ou ouvrez le dossier :

```
Mon Drive / Troupe 122 - 2026-27
```

Déposez-y vos PDF, directement — **pas dans des sous-dossiers**.

```
Troupe 122 - 2026-27/
    Le Malentendu.pdf
    Les Justes.pdf
```

**Le nom du fichier devient le nom du livre.** `Le Malentendu.pdf` produira
`Le Malentendu_OCR.txt`, puis `Le Malentendu.docx`. Nommez donc proprement dès
maintenant : accents et espaces sont acceptés, mais évitez les caractères
`/ \ : * ? " < > |`.

---

## 5. Ouvrir le premier notebook dans Colab

Le dépôt est public : aucune autorisation à donner.

1. Allez sur **colab.research.google.com**.
2. Menu **Fichier** → **Ouvrir un notebook**.
3. Onglet **GitHub**.
4. Dans le champ de recherche, tapez simplement **`elyeskaak`** — le nom
   d'utilisateur seul, **sans URL**. Validez avec la loupe.
5. Choisissez `texte_troupe_theatre` dans la liste **Repository**.
6. Cliquez sur **`notebooks/01_OCR.ipynb`**.

> **Le champ affiche « Could not find organization or user » ?** C'est que vous
> avez collé une URL complète, souvent avec `.git` à la fin. Ce champ attend le
> **nom d'utilisateur seul**. Effacez tout et tapez `elyeskaak`.

> **Méthode de secours, qui marche toujours** : sur github.com, ouvrez
> `notebooks/01_OCR.ipynb`, cliquez sur **Download raw file**, puis dans Colab
> **Fichier → Importer le notebook** et déposez le fichier téléchargé.

### Enregistrer la clé OpenAI

Le notebook est ouvert. Avant de lancer quoi que ce soit :

1. Dans la **colonne de gauche**, cliquez sur l'icône **clé 🔑** (*Secrets*).
2. **Ajouter un nouveau secret** :

   | Nom | Valeur |
   |---|---|
   | `OPENAI_API_KEY` | votre clé `sk-…` |

3. Activez l'interrupteur **Accès au notebook**. C'est l'étape qu'on oublie —
   sans elle, le notebook ne voit pas le secret.

Le secret est lié à votre compte Google, pas au notebook. Vous ne le saisirez
qu'une fois, et il n'apparaîtra jamais dans le notebook ni dans ses résultats
affichés.

---

## 6. Le premier essai : 10 pages

On ne lance jamais un livre de 300 pages du premier coup. On éprouve d'abord la
chaîne sur 10 pages, pour quelques centimes.

Dans Colab, une cellule se lance en cliquant le **▶** à sa gauche, ou avec
**Maj + Entrée**. Faites-les **dans l'ordre, une par une**.

### Section 1 — Dépendances et Drive

Lancez la cellule. Une fenêtre demande l'autorisation d'accéder au Drive :
acceptez, choisissez votre compte Google.

Vous devez voir :
```
Mounted at /content/drive
```

⏱ Environ 1 minute (l'installation des bibliothèques).

### Section 2 — Récupération du code

**Lancez uniquement la cellule « Option A ».** Ignorez « Option B », qui ne sert
que si vous préférez ne pas utiliser GitHub.

Vous devez voir :
```
Code récupéré : /content/texte_troupe_theatre
Jeton GitHub  : non nécessaire (dépôt public)
```

### Section 3 — Configuration

Vérifiez que le chemin correspond à votre dossier, puis lancez.

Vous devez voir :
```
Dossier de travail : /content/drive/MyDrive/Troupe 122 - 2026-27
Existe             : True
```

> **`Existe : False` ?** Le chemin est faux. Le plus souvent : le dossier
> s'appelle autrement, ou il est dans un « Drive partagé » et non dans « Mon
> Drive ». Corrigez le chemin dans la cellule et relancez.

### Sections 4 et 5 — Clé API et modèles

Deux vérifications rapides. Vous devez voir `Clé API trouvée.` puis quatre
lignes `[OK]`.

> **`[ECHEC] ocr … introuvable` ?** Le modèle configuré n'existe pas sur votre
> compte. Voyez le dépannage en §10.

### Section 6 — Aperçu

Liste vos PDF avec leur taille. Aucun appel payant. Vérifiez que vos deux
fichiers sont bien là.

### Section 7 — Diagnostic : ce que ça va coûter

**Cette cellule est gratuite.** Elle regarde si vos PDF contiennent déjà du texte
exploitable — beaucoup de PDF ont déjà été passés à l'OCR par un scanner.

Exemple de résultat :
```
Le Malentendu
   pages retenues          10
   couche texte utilisable 10
   à passer à l'OCR         0
   part sans appel API     100%

Les Justes
   pages retenues          10
   couche texte utilisable  0
   à passer à l'OCR        10
   part sans appel API       0%
```

Ici, le premier livre ne coûtera **rien** et le second coûtera 10 appels. C'est
normal : l'un est déjà OCRisé, l'autre est fait d'images.

### Section 8 — Régler l'essai

```python
config.LIMITE_PAGES = 10
```

Lancez. Vous devez voir `Limite de pages : 10`.

### Section 9 — Lancement

C'est ici que les appels payants ont lieu. Vous verrez défiler l'avancement :
```
   [ALERTE]  ESSAI LIMITÉ : 10 page(s) sur 289.
   10/10 (100 %) — pages
   [OK]      Le Malentendu_OCR.txt — 12 843 caractères
```

L'alerte « ESSAI LIMITÉ » est **normale** : c'est un rappel volontaire que vous
êtes en mode essai.

⏱ Environ 1 minute pour 10 pages.

### Section 10 — Contrôle

Affiche le début du texte obtenu. **Lisez-le vraiment.** C'est le moment de voir
si la transcription est correcte avant d'aller plus loin.

---

## 7. Les trois notebooks suivants

Retournez dans **Fichier → Ouvrir un notebook → GitHub** et ouvrez le suivant.

Pour chacun : refaites les sections 1, 2 et 3 (Drive, code, configuration), puis
suivez les sections numérotées.

**Vous n'avez rien à reporter d'un notebook à l'autre.** Chaque étape lit les
fichiers laissés par la précédente sur le Drive.

| Notebook | Ce qu'il fait | À regarder |
|---|---|---|
| **02_Edition** | Corrige les erreurs de lecture, met en forme | la section 9 affiche le texte édité et la structure détectée |
| **03_Verification** | Compare l'original et l'édition | le rapport : ce qui aurait été perdu |
| **04_DOCX** | Fabrique le document Word | **la table d'inspection, section 5** |

### Le point à ne pas survoler : la table d'inspection

Dans le notebook 04, section 5, vous verrez :

```
LABEL                     OCC.  RÉPL.  CLASSÉ        CONFIANCE
ACTE PREMIER                 1      0  titre_acte    certaine (lexique acte)
SCÈNE 2                      1      0  titre_scene   certaine (lexique scène)
JAN.                        84     84  personnage    certaine (distribution)
LA VOIX                      1      0  personnage    incertaine ⚠
```

Le programme y montre **comment il a compris votre pièce** : ce qu'il prend pour
un acte, une scène, un personnage. Les lignes marquées `⚠` sont celles dont il
n'est pas sûr.

Pourquoi c'est important : seuls les **actes** déclenchent un saut de page dans le
document Word. Une scène prise pour un acte produirait une page blanche au milieu
d'un acte.

Si une ligne est mal classée, corrigez-la dans la section 6 :

```python
config.TITRES_ACTE_FORCES = frozenset({"OUVERTURE"})
config.PERSONNAGES_FORCES = frozenset({"LA VOIX"})
```

Écrivez les noms **en majuscules et sans accents**, exactement comme dans la
colonne `LABEL`. Puis relancez la génération — c'est gratuit et instantané.

---

## 8. Passer au livre entier

L'essai vous a convaincu ? Retournez au notebook **01**, section 8 :

```python
config.LIMITE_PAGES = None
```

Relancez la section 9. **Les 10 pages de l'essai ne seront pas repayées** : seules
les pages manquantes sont transcrites.

Puis refaites les notebooks 02, 03 et 04.

Au notebook 02, vous verrez peut-être :
```
[ALERTE]  bloc 2 : frontières changées (pages 9–10 → 9–16), réédition
```

**C'est normal et c'est une protection.** Le texte est découpé en blocs de 8
pages. Pendant l'essai, le bloc 2 ne contenait que 2 pages ; il en contient 8
maintenant. Le programme s'en aperçoit et le refait — sans ce contrôle, des pages
disparaîtraient discrètement.

⏱ Pour 300 pages, comptez 20 à 30 minutes par étape.

---

## 9. Quand Colab se déconnecte

Ça arrivera. Colab coupe les sessions inactives au bout d'environ 90 minutes, et
limite les sessions à quelques heures.

**Vous ne perdez rien.** Voici la marche à suivre :

1. Rechargez la page.
2. Relancez les sections 1, 2 et 3 (Drive, code, configuration).
3. Relancez la section de lancement.

Vous verrez alors :
```
   [DEJA]    247 page(s) déjà transcrite(s)
```

Seul ce qui manquait est traité. Aucun appel n'est repayé.

> **Astuce :** laissez l'onglet Colab visible pendant le traitement. Une session
> réduite ou un ordinateur en veille se fait déconnecter plus vite.

---

## 10. Dépannage

| Message | Ce que ça veut dire | Quoi faire |
|---|---|---|
| `Could not find organization or user` | Une URL a été collée dans l'onglet GitHub de Colab | Tapez le nom d'utilisateur seul : `elyeskaak` |
| `Récupération du code impossible` | Dépôt injoignable, ou redevenu privé sans jeton | Vérifiez que github.com/elyeskaak/texte_troupe_theatre s'ouvre sans être connecté |
| `Clé API introuvable` | Le secret `OPENAI_API_KEY` manque, ou son interrupteur « Accès au notebook » est éteint | Revoyez §5 |
| `Existe : False` | Le dossier Drive n'est pas au chemin indiqué | Corrigez le chemin. Attention aux « Drive partagés », dont le chemin diffère |
| `Dossier de travail introuvable` | Le Drive n'est pas monté | Relancez la section 1 |
| `[ECHEC] ocr … introuvable` | Le modèle n'existe pas sur votre compte | Dans la section 3, ajoutez `config.MODEL_OCR = "gpt-4o"` et relancez |
| `[ALERTE] page N : mise en forme ajoutée` | Le modèle a ajouté du `**gras**` ou de l'`*italique*`, alors que la transcription doit être en texte nu | La page est reprise automatiquement, jusqu'à 2 fois. Si l'alerte persiste, elle est conservée et signalée : lisez la page dans `Livre_OCR_pages/` pour juger |
| `[ALERTE] page N : sortie vide` | Le modèle n'a rien rendu sans déclarer une page blanche | Reprise automatique. Si la page est réellement blanche, ce n'est pas grave |
| `Erreur non réessayable … 400` | Le modèle refuse les images | Même correctif : repassez `MODEL_OCR` sur `"gpt-4o"` |
| `insufficient_quota` | Plus de crédit OpenAI | Rechargez sur platform.openai.com → Billing |
| `aucun fichier « _OCR.txt »` | Vous lancez l'étape 2 avant l'étape 1 | Faites le notebook 01 d'abord |
| `découpage incohérent` | `PAGES_PAR_BLOC` a changé entre deux étapes | Remettez la valeur d'origine, ou supprimez les dossiers `_EDIT_blocs/` et `_EDIT_raccords/` |
| Le DOCX a des pages blanches inattendues | Une scène a été prise pour un acte | Table d'inspection, §7 de ce tutoriel |
| Les accents s'affichent mal dans le DOCX | La police EB Garamond n'est pas installée sur votre ordinateur | Installez-la gratuitement depuis Google Fonts |

### Si rien ne marche : repartir de zéro sur un livre

Supprimez sur le Drive tout ce qui porte le nom du livre **sauf le PDF** :

```
Le Malentendu_OCR.txt          ← supprimer
Le Malentendu_OCR_pages/       ← supprimer
Le Malentendu_EDIT_blocs/      ← supprimer
Le Malentendu_EDIT_raccords/   ← supprimer
Le Malentendu_EDIT.txt         ← supprimer
Le Malentendu.pdf              ← GARDER
```

Attention : cela fera repayer tout l'OCR.

---

## 11. Où sont mes fichiers

Tout dans le même dossier Drive, à côté du PDF.

| Fichier | Ce que c'est | Utile pour vous ? |
|---|---|---|
| `Livre.pdf` | votre source | — |
| `Livre_OCR.txt` | transcription brute, non corrigée | rarement |
| `Livre_EDIT.txt` | **texte propre** | **oui** — c'est ici qu'on corrige à la main |
| `Livre_REPORT.txt` | ce qui aurait été perdu | oui, à relire une fois |
| `Livre.docx` | **le document final** | **oui** |
| `Livre_OCR_pages/` | une page par fichier | non, mémoire interne |
| `Livre_EDIT_blocs/` | blocs intermédiaires | non |
| `Livre_EDIT_raccords/` | blocs après ressoudure | non |
| `journal_*.json` | trace de chaque appel et son coût | si vous voulez vérifier la dépense |

**Ne supprimez pas les dossiers `_pages/`, `_blocs/`, `_raccords/`** : c'est grâce
à eux que rien n'est jamais repayé.

### Corriger le texte à la main

`Livre_EDIT.txt` est un simple fichier texte. Si le rapport signale un problème,
ou si vous voyez une coquille, ouvrez-le, corrigez, enregistrez, puis relancez
**seulement le notebook 04**. C'est gratuit et immédiat.

Les conventions à respecter en corrigeant :

```
**ACTE PREMIER**          un titre : deux astérisques de chaque côté
*Une auberge. Le soir.*   un lieu ou une didascalie : une seule astérisque
**JAN.**                  un nom de personnage : deux astérisques
Nous y sommes enfin.      une réplique : rien
***                       un changement de scène
```

---

## 12. Récupérer une mise à jour du code

Quand le programme est amélioré sur GitHub, la cellule « Option A » du notebook
récupère automatiquement la dernière version à chaque exécution. Vous n'avez rien
à faire.

**Une exception :** si les *notebooks eux-mêmes* ont changé, il faut les rouvrir
depuis GitHub (**Fichier → Ouvrir un notebook → GitHub**) pour en avoir la
nouvelle version. Un notebook déjà ouvert dans votre navigateur ne se met pas à
jour tout seul.

> Si Colab vous propose d'« enregistrer une copie dans Drive », sachez que cette
> copie ne se mettra plus à jour. Pour rester à jour, réouvrez depuis GitHub.

---

## 13. Récapitulatif : la routine, une fois tout en place

1. Déposer le PDF dans `Troupe 122 - 2026-27` sur le Drive.
2. Ouvrir `01_OCR.ipynb` depuis GitHub.
3. Sections 1 à 3, puis 7 (diagnostic), 8 (`LIMITE_PAGES = 10`), 9, 10.
4. Si l'essai est bon : `LIMITE_PAGES = None`, relancer la section 9.
5. Notebooks 02, 03, 04 — en lisant la table d'inspection au 04.
6. Récupérer le `.docx` sur le Drive.

Bonne édition.
