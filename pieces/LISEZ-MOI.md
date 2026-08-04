# NE CORRIGEZ RIEN DANS CE DOSSIER

Tout ce qui est ici est **régénéré**. Le moindre fichier que vous y corrigez
sera écrasé à la prochaine génération, sans avertissement.

C'est arrivé une fois : une correction de « SIR ROWLAND » faite sur le
`.docx` de ce dossier, alors que la source vivait ailleurs.

Le document à corriger est dans `../exemples/` (ou son sous-dossier
`Pièces clean/`).

## Ce dossier est partagé

`pieces/` est **partagé entre `outil_repetition` et `outil_lecture`** : les
deux outils consomment le même `<Livre>_REPET.json`, produit une seule fois
ici. Il n'y a donc qu'un seul exemplaire à régénérer, jamais un par outil.

## Régénérer après une correction du docx

Depuis `outil_edition/` :

```bash
python outils/docx_vers_repet.py "../exemples/<Piece>.docx" --dossier ../pieces
```

Un seul fichier, un seul dossier de sortie, **aucun `.docx` n'est produit ni
écrasé** — voir le docstring de `docx_vers_repet.py` pour le détail. Passer
plusieurs chemins à la suite régénère plusieurs pièces d'un coup.

Cette commande met aussi à jour `pieces/manifest.json` (la liste des pièces
disponibles, que les deux outils lisent au démarrage pour proposer
automatiquement toutes les pièces présentes ici — plus besoin de les
importer une par une).

## Ce que contient ce dossier

- `<Livre>_REPET.json` — la sortie consommée par les deux outils.
- `manifest.json` — la liste des pièces disponibles, régénérée à chaque
  passage de `docx_vers_repet.py`.
- `temp/<Livre>/` — fichiers de travail intermédiaires (`EDIT.txt`,
  `CONVERSION.txt`) ; à consulter en cas d'avertissement, jamais à corriger
  ici (voir plus haut).

## Jamais versionné

Ce dossier n'est jamais poussé sur GitHub (`.gitignore`) : un `REPET.json`
contient le texte intégral d'une œuvre, souvent sous droits. Voir
`outil_edition/NOTES_PIECES.md` pour les cas particuliers connus
(personnages non annoncés, corrections manuelles encore nécessaires…).
