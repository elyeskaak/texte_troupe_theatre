"""
Utilitaires transverses du pipeline.

Répartition des responsabilités, volontairement étanche :

- `io`      système de fichiers, résolution des chemins, reprise (sidecars)
- `blocks`  logique texte **pure** — aucune I/O, aucun réseau, aucune horloge
- `logging` affichage console et écriture des journaux JSON
- `api`     client OpenAI, réessais, extraction du texte de réponse

`blocks` est le seul module dont la pureté est une garantie architecturale :
c'est ce qui rend testable, sans clé API ni Drive monté, la logique la plus
délicate du projet (classification acte / scène / personnage).

Aucun import n'est effectué ici : `utils.api` dépend d'`openai`, qui n'a pas à
être installé pour utiliser `utils.blocks`.
"""

from __future__ import annotations
