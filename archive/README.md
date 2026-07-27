# Archive

## `Édition_OCR.ipynb`

Prototype d'origine, conservé **tel quel** et jamais modifié. Il constitue le
point de départ du projet et le premier commit du dépôt.

### Pourquoi le garder

Deux raisons, et la seconde est la plus importante.

D'abord la traçabilité : c'est de ce notebook que proviennent
`prompt_edition.md` et `prompt_raccord.md`, repris **mot pour mot**. La
concordance a été vérifiée par diff automatique — 103 et 40 lignes, aucune
divergence hors les marqueurs Markdown ajoutés aux titres de section.

Ensuite, il documente ce que la restructuration a résolu.

### Ce qui n'allait pas

Ce notebook **ne peut pas s'exécuter en l'état** :

- les cellules 9 à 12 sont **dupliquées à l'identique** en cellules 13 à 16 ;
- il appelle sept symboles jamais définis : `traiter_fichier_ocr`,
  `diviser_fenetre_fin`, `diviser_fenetre_debut`, `raccorder_extraits_api`,
  `MODEL_RACCORD`, `REPRENDRE_RACCORDS`, `LIGNES_CONTEXTE_RACCORD`.

Il contenait par ailleurs `RATIO_MINIMAL_LONGUEUR = 0.55`, seuil très permissif :
un bloc pouvait perdre 40 % de son volume sans déclencher d'alerte. Le pipeline
retient `0.80`.

### Le seul écart de fond

Une section a été **ajoutée** à `prompt_raccord.md` : « PLACEMENT D'UNE
RESSOUDURE ». Le prompt d'origine autorisait à ressouder un mot coupé sans dire
où poser le résultat ; un mot laissé à cheval sur les deux extraits restait donc
coupé en deux dans l'édition finale. Défaut observé sur une exécution réelle du
pipeline, non une supposition.

---

Ce dossier n'est pas importé par le code et ne fait pas partie du pipeline.
