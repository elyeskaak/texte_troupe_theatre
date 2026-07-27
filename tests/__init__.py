"""
Tests du pipeline theatre_editor.

Ces tests ne portent que sur les modules **purs** : aucune clé API, aucun
Google Drive monté, aucune dépendance externe n'est nécessaire. C'est
délibéré — la logique la plus délicate du projet doit pouvoir être validée
avant le premier appel API facturé.

Exécution, depuis la racine du projet :

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations
