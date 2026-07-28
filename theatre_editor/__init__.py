"""
theatre_editor — pipeline d'édition de pièces de théâtre à partir de scans PDF.

Le pipeline se compose de quatre étapes strictement indépendantes, chacune
lisant et écrivant des fichiers, sans état partagé en mémoire :

    1. `ocr`         PDF            → <Livre>_OCR.txt
    2. `edition`     OCR.txt        → <Livre>_EDIT.txt
    3. `validation`  OCR + EDIT     → <Livre>_REPORT.txt
    4. `docx_export` EDIT.txt       → <Livre>.docx

Voir `ARCHITECTURE.md` pour la conception détaillée.

Ce module est délibérément **vide de tout import de sous-module**. Importer
`theatre_editor` ne doit jamais déclencher le chargement d'`openai`, de
`pymupdf` ni de `python-docx` : les tests de `utils/blocks.py` doivent pouvoir
s'exécuter sur une machine où aucune de ces dépendances n'est installée.
Chaque étape s'importe donc explicitement :

    from theatre_editor import ocr          # nécessite openai + pymupdf
    from theatre_editor.utils import blocks # ne nécessite rien
"""

from __future__ import annotations

__version__ = "1.0.0"

# Étapes exposées, dans l'ordre du pipeline. Sert à `main.py` pour valider
# l'argument `--etape` sans avoir à importer les modules correspondants.
ETAPES = ("ocr", "edition", "liminaires", "validation", "docx")
