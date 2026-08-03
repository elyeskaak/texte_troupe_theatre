# Théâtre — outils pour la Troupe 122

Dépôt regroupant les outils développés pour la troupe. Chaque outil est un
sous-projet indépendant, dans son propre dossier.

## Sous-projets

- **[outil_edition/](outil_edition/README.md)** — pipeline d'édition de
  pièces : scans PDF → DOCX propre (OCR, raccord, mise en forme). Conçu pour
  tourner dans Google Colab. Voir aussi son
  [tutoriel pas à pas](outil_edition/TUTORIEL.md) et son
  [architecture](outil_edition/ARCHITECTURE.md).
- **[outil_coupes/](outil_coupes/DOCTRINE.md)** — équilibrage et coupes d'une
  pièce entre comédiens (`analyze.py`), avec la doctrine de coupe à suivre.
- **[outil_repetition/](outil_repetition/CAHIER_DES_CHARGES.md)** — outil de
  répétition de son texte, page web publiée en HTTPS et utilisable sur iPhone.
  Lit le `REPET.json` produit par `outil_edition`. En cours de conception : voir
  son [cahier des charges](outil_repetition/CAHIER_DES_CHARGES.md).
- **outil_lecture/** — outil de lecture interactif à venir, pour projeter une
  pièce lors d'une lecture avec la troupe.

## Autres dossiers

- **[exemples/](exemples/)** — pièces sources utilisées par les outils
  ci-dessus (scans, textes). Jamais versionné sur GitHub (droits d'auteur) —
  voir `.gitignore`.

## Note sur les tests et scripts d'outil_edition

`outil_edition/` a déplacé sa racine : les commandes qui s'exécutaient
« depuis la racine du dépôt » (tests, génération des notebooks) s'exécutent
maintenant depuis `outil_edition/` :

```bash
cd outil_edition
python -m unittest discover -s tests -t .
```
