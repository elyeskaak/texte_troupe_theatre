# Prompts

Un fichier par prompt, chargé par `utils.io.charger_prompt()` et transmis tel
quel au paramètre `instructions` de la Responses API.

> **Ce fichier n'est jamais envoyé à un modèle.** `charger_prompt()` ne
> reconnaît que les fichiers nommés `prompt_*.md`. C'est précisément pourquoi
> cette documentation est ici et non en tête des prompts : **tout ce qu'un
> fichier de prompt contient part au modèle**, commentaires compris. Un prompt
> ne contient donc que le prompt.

## Les quatre prompts

| Fichier | Étape | Modèle | Entrée | Sortie attendue |
|---|---|---|---|---|
| `prompt_ocr.md` | 1 — OCR | `MODEL_OCR` | image PNG d'une page | texte nu, sans mise en forme |
| `prompt_edition.md` | 2a — édition | `MODEL_EDITION` | bloc de pages OCR | texte édité, convention typographique appliquée |
| `prompt_raccord.md` | 2b — raccord | `MODEL_RACCORD` | deux extraits de 50 lignes | format délimité `<<<BLOC_GAUCHE>>>…` |
| `prompt_validation.md` | 3 — contrôle | `MODEL_VALIDATION` | couple (OCR, EDIT) d'un bloc | constats, ou `AUCUN PROBLEME DETECTE` |

## Contrats à ne pas rompre

Trois prompts contiennent des chaînes que le code analyse ensuite. Les modifier
sans modifier `config.py` casserait le pipeline **silencieusement** — d'où
`tests/test_prompts.py`, qui vérifie la concordance.

- **`prompt_raccord.md`** doit produire les quatre délimiteurs
  `DELIM_RACCORD_*`. Le parseur de `edition.py` en dépend.
- **`prompt_validation.md`** doit répondre exactement `MENTION_AUCUN_PROBLEME`
  quand le bloc est sain, et n'employer que les `CATEGORIES_VALIDATION`.
- **`prompt_ocr.md`** doit répondre `MENTION_PAGE_SANS_TEXTE` pour une page
  vide, sinon une page blanche produirait une réponse vide — indiscernable
  d'un échec d'appel.

## Répartition des rôles entre l'OCR et l'édition

C'est la décision la plus importante que ces prompts traduisent, et elle mérite
d'être rappelée avant toute retouche.

**`prompt_ocr.md` interdit toute correction.** Pas seulement par prudence : la
transcription brute est la **référence de vérité** de l'étape 3. Si le modèle
OCR corrigeait déjà, il n'existerait plus aucun texte permettant de détecter ce
que l'étape 2 aurait perdu, et le contrôle qualité deviendrait creux.

Il interdit aussi toute mise en forme — aucune astérisque. La convention
typographique est appliquée exclusivement à l'étape 2. Un OCR qui produirait
déjà du `**JAN.**` rendrait la comparaison de l'étape 3 illisible.

## Le piège du prompt de validation

Sa section la plus longue est celle qui énumère ce qu'il ne faut **pas**
signaler. Ce n'est pas du remplissage : entre `OCR.txt` et `EDIT.txt`, les
différences légitimes sont bien plus nombreuses que les pertes réelles —
marqueurs supprimés, astérisques ajoutées, fautes corrigées, mots ressoudés.
Sans cette liste, chaque bloc remonterait des dizaines de faux positifs et le
rapport deviendrait inexploitable.

## Modifier un prompt

Les prompts évoluent sans toucher au Python : c'est tout l'intérêt de les avoir
sortis du code. Deux précautions.

1. Lancer `python -m unittest discover -s tests -t .` — les contrats ci-dessus
   sont testés.
2. Ne pas changer de prompt **au milieu d'un livre**. Les blocs déjà produits
   ne seront pas refaits, et deux prompts différents sur un même texte
   introduiraient une hétérogénéité que la passe de raccord ne rattrape pas.
   Pour refaire un livre entier avec un prompt révisé, supprimer son dossier
   `_EDIT_blocs/`.
