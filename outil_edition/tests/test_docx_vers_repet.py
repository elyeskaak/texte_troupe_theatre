"""
Tests de `outils/docx_vers_repet.py`.

Le point qui compte ici n'est pas repris ailleurs : cet outil régénère le
`REPET.json` d'un DOCX déjà mis en forme **sans jamais produire ni écraser de
`.docx`**. `docx_vers_edit.py` et `repet_export.py` sont déjà couverts chacun
de leur côté ; ces tests portent sur l'assemblage des deux et sur l'absence de
`.docx` en sortie, qui est la raison d'être de ce module.
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

import docx  # noqa: E402

from outils.docx_vers_repet import regenerer_repet  # noqa: E402
from theatre_editor import config  # noqa: E402
from theatre_editor.utils import io  # noqa: E402


def _ecrire_docx_minimal(chemin: Path) -> None:
    """Un DOCX minimal, avec exactement ce que `docx_vers_edit` sait lire."""
    document = docx.Document()
    document.add_paragraph("ACTE PREMIER", style="Heading 1")

    personnage = document.add_paragraph()
    personnage.add_run("JAN").bold = True

    document.add_paragraph("Nous y sommes enfin.")

    document.save(str(chemin))


class SansDocxEnSortie(unittest.TestCase):
    """L'invariant qui justifie l'existence de ce module."""

    def test_aucun_docx_n_est_ecrit(self):
        with tempfile.TemporaryDirectory() as brut:
            dossier = Path(brut)
            source = dossier / "source" / "Ma pièce.docx"
            source.parent.mkdir(parents=True)
            _ecrire_docx_minimal(source)

            travail = dossier / "travail"
            regenerer_repet(source, travail)

            chemins = io.resoudre_chemins("Ma pièce", travail)

            self.assertFalse(chemins.docx.exists())
            self.assertTrue(chemins.repet.exists())
            self.assertTrue(chemins.edit.exists())

    def test_relancable_a_volonte(self):
        """Une deuxième exécution ne doit ni échouer, ni laisser de trace."""
        with tempfile.TemporaryDirectory() as brut:
            dossier = Path(brut)
            source = dossier / "source" / "Ma pièce.docx"
            source.parent.mkdir(parents=True)
            _ecrire_docx_minimal(source)

            travail = dossier / "travail"
            regenerer_repet(source, travail)
            regenerer_repet(source, travail)

            chemins = io.resoudre_chemins("Ma pièce", travail)

            self.assertFalse(chemins.docx.exists())
            self.assertTrue(chemins.repet.exists())


class ContenuDuRepet(unittest.TestCase):
    """Le JSON produit est celui qu'écrirait l'étape 4, à l'identique."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        dossier = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        source = dossier / "source" / "Ma pièce.docx"
        source.parent.mkdir(parents=True)
        _ecrire_docx_minimal(source)

        self.travail = dossier / "travail"
        self.chemin_repet = regenerer_repet(source, self.travail)

    def test_le_schema_et_la_piece_sont_corrects(self):
        document = json.loads(self.chemin_repet.read_text(encoding="utf-8"))

        self.assertEqual(document["schema"], config.SCHEMA_REPET)
        self.assertEqual(document["piece"], "Ma pièce")

    def test_la_replique_est_presente(self):
        document = json.loads(self.chemin_repet.read_text(encoding="utf-8"))
        repliques = [
            e
            for u in document["unites"]
            for e in u["elements"]
            if e["type"] == "replique"
        ]

        self.assertEqual(len(repliques), 1)
        self.assertEqual(repliques[0]["personnages"], ["JAN"])
        self.assertEqual(repliques[0]["texte"], "Nous y sommes enfin.")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
