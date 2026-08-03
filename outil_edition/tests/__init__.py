"""
Tests du pipeline theatre_editor.

Ces tests ne portent que sur du code exécutable **sans dépendance externe** :
`openai`, `pymupdf` et `python-docx` sont remplacés par des doublures, et les
imports du code de production sont différés en conséquence. C'est délibéré — la
logique la plus délicate du projet doit pouvoir être validée avant le premier
appel API facturé.

Exécution, depuis la racine du projet :

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

from theatre_editor import config

# ------------------------------------------------------------
# La synchronisation disque est désactivée pour toute la suite.
#
# `os.fsync` est indispensable en production — sur un Drive monté en FUSE, il
# évite de publier un fichier encore en mémoire tampon — mais il coûte une
# dizaine de millisecondes par fichier. Les tests écrivent des centaines de
# fichiers minuscules, sans appel API pour amortir ce coût : la suite passait
# de 0,1 s à plus de 4 s.
#
# Le réglage est appliqué ici, au chargement du paquet de tests, plutôt que
# répété dans chaque classe.
# ------------------------------------------------------------
config.ECRITURE_SYNCHRONE = False
