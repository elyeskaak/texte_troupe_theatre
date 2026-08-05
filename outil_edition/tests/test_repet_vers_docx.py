"""
Tests de `outils/repet_vers_docx.py`.

Le point qui compte ici : reconstruire un `.docx` fidèle à partir d'un
`REPET.json`, sans reprendre l'`EDIT.txt` d'origine. La comparaison la plus
solide part donc du même texte source que `test_docx_export.py`, génère les
deux sorties de l'étape 4 (`.docx` et `REPET.json`), et vérifie que
reconstruire un troisième document à partir du seul JSON reproduit la même
séquence de styles et de textes que le DOCX d'origine.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

try:
    import docx  # noqa: F401

    from outils import repet_vers_docx
    from theatre_editor import config, docx_export, repet_export
    from theatre_editor.utils import blocks

    DOCX_DISPONIBLE = True
except ImportError:  # pragma: no cover - dépend de l'environnement
    DOCX_DISPONIBLE = False


PIECE = (
    "**PERSONNAGES**\n"
    "JAN, le frère\n"
    "MARIA, sa femme\n"
    "LE MESSAGER\n"
    "\n"
    "\n"
    "**ACTE PREMIER**\n"
    "\n"
    "*Une auberge. Le soir.*\n"
    "\n"
    "**JAN.**\n"
    "Nous y sommes enfin.\n"
    "\n"
    "**MARIA.**\n"
    "Je t'attendais *elle se lève* depuis une heure.\n"
    "\n"
    "*Pause.*\n"
    "\n"
    "***\n"
    "\n"
    "*Le messager entre.*\n"
    "\n"
    "**LE MESSAGER.**\n"
    "Un pli pour vous.\n"
    "\n"
    "**SCÈNE 2**\n"
    "\n"
    "**JAN.**\n"
    "Donnez.\n"
    "\n"
    "**ACTE DEUXIÈME**\n"
    "\n"
    "**MARIA.**\n"
    "Enfin seuls.\n"
)


def _sequence(document) -> list[tuple[str, str]]:
    """Suite (style, texte) de tous les paragraphes d'un document."""
    return [(p.style.name, p.text) for p in document.paragraphs]


@unittest.skipUnless(DOCX_DISPONIBLE, "python-docx n'est pas installé")
class ReconstructionFidele(unittest.TestCase):
    """Le DOCX reconstruit reproduit le DOCX d'origine, paragraphe par paragraphe."""

    def setUp(self):
        index = blocks.construire_index_structure(PIECE)
        lignes = docx_export.lignes_classees(PIECE, index)

        self.original, _, _ = docx_export.construire_docx(PIECE)
        self.repet = repet_export.construire_repet(lignes, index, piece="Le Malentendu")
        self.reconstruit = repet_vers_docx.construire_document(self.repet)

    def test_meme_sequence_de_styles_et_de_textes(self):
        self.assertEqual(_sequence(self.reconstruit), _sequence(self.original))

    def test_emphase_interne_reproduite(self):
        """La didascalie « elle se lève » doit rester en italique, pas fondue."""
        paragraphe = next(
            p for p in self.reconstruit.paragraphs if "Je t'attendais" in p.text
        )
        italiques = [r.text for r in paragraphe.runs if r.italic]

        self.assertEqual(italiques, ["elle se lève"])


@unittest.skipUnless(DOCX_DISPONIBLE, "python-docx n'est pas installé")
class Validation(unittest.TestCase):
    def test_schema_inconnu_refuse(self):
        with tempfile.TemporaryDirectory() as brut:
            chemin = Path(brut) / "Mauvais_REPET.json"
            chemin.write_text(json.dumps({"schema": "autre/1"}), encoding="utf-8")

            with self.assertRaises(ValueError):
                repet_vers_docx.charger_repet(chemin)


@unittest.skipUnless(DOCX_DISPONIBLE, "python-docx n'est pas installé")
class ConversionDeFichier(unittest.TestCase):
    def test_ecrit_le_docx_dans_le_dossier_demande(self):
        with tempfile.TemporaryDirectory() as brut:
            dossier = Path(brut)
            source = dossier / "pieces" / "Le Malentendu_REPET.json"
            source.parent.mkdir(parents=True)

            index = blocks.construire_index_structure(PIECE)
            lignes = docx_export.lignes_classees(PIECE, index)
            repet = repet_export.construire_repet(lignes, index, piece="Le Malentendu")
            repet["genere_le"] = "2026-01-01T00:00:00"
            source.write_text(json.dumps(repet, ensure_ascii=False), encoding="utf-8")

            sortie = dossier / "reconstitutions"
            chemin_docx = repet_vers_docx.convertir_fichier(source, sortie)

            self.assertEqual(chemin_docx, sortie / "Le Malentendu.docx")
            self.assertTrue(chemin_docx.exists())
            # Le dossier des REPET.json n'est jamais touché.
            self.assertFalse((source.parent / "Le Malentendu.docx").exists())

    def test_main_signale_un_fichier_introuvable(self):
        with tempfile.TemporaryDirectory() as brut:
            dossier = Path(brut)
            code = repet_vers_docx.main(
                [str(dossier / "Absent_REPET.json"), "--dossier", str(dossier / "sortie")]
            )

            self.assertEqual(code, 1)

    def test_dossier_est_obligatoire(self):
        with tempfile.TemporaryDirectory() as brut:
            with self.assertRaises(SystemExit):
                repet_vers_docx.main([str(Path(brut) / "Piece_REPET.json")])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
