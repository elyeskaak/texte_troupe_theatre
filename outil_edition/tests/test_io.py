"""
Tests de la disposition des fichiers et de la migration.

La disposition a changé après une remarque d'usage : le dossier Drive
principal était encombré de fichiers intermédiaires. Il ne montre désormais que
le PDF source et le DOCX final, tout le reste vivant dans `temp/<Livre>/`.

Ce changement porte un risque grave : rendre invisibles des transcriptions déjà
payées, qui seraient alors refaites. `migrer_livre()` existe pour cela, et ces
tests le vérifient.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from theatre_editor import config
from theatre_editor.utils import io


class BaseDisposition(unittest.TestCase):
    def setUp(self):
        self._dossier = tempfile.TemporaryDirectory()
        self.base = Path(self._dossier.name)
        self.chemins = io.resoudre_chemins("Le Malentendu", self.base)

    def tearDown(self):
        self._dossier.cleanup()


class TestDisposition(BaseDisposition):
    def test_pdf_et_docx_dans_le_dossier_principal(self):
        """Les deux seuls fichiers qui intéressent l'utilisateur."""
        self.assertEqual(self.chemins.pdf.parent, self.base)
        self.assertEqual(self.chemins.docx.parent, self.base)

    def test_tout_le_reste_dans_le_dossier_de_travail(self):
        travail = self.base / config.DOSSIER_TEMPORAIRE / "Le Malentendu"

        for chemin in (
            self.chemins.ocr,
            self.chemins.edit,
            self.chemins.report,
            self.chemins.dossier_pages,
            self.chemins.dossier_blocs,
            self.chemins.dossier_raccords,
            self.chemins.dossier_report,
        ):
            with self.subTest(chemin=chemin.name):
                self.assertTrue(str(chemin).startswith(str(travail)))

    def test_deux_livres_ne_se_melangent_pas(self):
        autre = io.resoudre_chemins("Les Justes", self.base)

        self.assertNotEqual(self.chemins.dossier_travail, autre.dossier_travail)
        self.assertNotEqual(self.chemins.ocr, autre.ocr)

    def test_recensement_des_livres(self):
        io.ecrire_texte_atomique(self.chemins.ocr, "[PAGE 1]\nA.")
        io.ecrire_texte_atomique(
            io.resoudre_chemins("Les Justes", self.base).ocr, "[PAGE 1]\nB."
        )

        self.assertEqual(io.lister_livres(self.base), ["Le Malentendu", "Les Justes"])

    def test_recensement_filtre_sur_le_fichier_attendu(self):
        io.ecrire_texte_atomique(self.chemins.ocr, "[PAGE 1]\nA.")
        io.assurer_dossier(io.resoudre_chemins("Les Justes", self.base).dossier_travail)

        avec_ocr = io.lister_livres_avec(config.NOM_OCR, self.base)

        self.assertEqual([c.nom for c in avec_ocr], ["Le Malentendu"])

    def test_dossier_absent_ne_leve_pas(self):
        self.assertEqual(io.lister_livres(self.base), [])


class TestMigration(BaseDisposition):
    """
    Sans migration, les transcriptions déjà payées deviendraient invisibles.
    """

    def _ancienne_disposition(self) -> None:
        io.ecrire_texte_atomique(
            self.base / f"Le Malentendu{config.SUFFIXE_OCR}", "[PAGE 1]\nJAN\nA."
        )
        dossier_pages = io.assurer_dossier(
            self.base / f"Le Malentendu{config.SUFFIXE_OCR_PAGES}"
        )
        io.ecrire_texte_atomique(dossier_pages / "page_0001.txt", "JAN\nA.")
        io.ecrire_sidecar(
            dossier_pages / "page_0001.json",
            {"statut": config.STATUT_TERMINE, "numero": 1},
        )
        io.ecrire_texte_atomique(
            self.base / f"Le Malentendu{config.SUFFIXE_EDIT}", "**JAN.**\nA.\n"
        )

    def test_detection(self):
        self._ancienne_disposition()

        self.assertEqual(io.livres_a_migrer(self.base), ["Le Malentendu"])

    def test_aucune_detection_sur_un_dossier_neuf(self):
        self.assertEqual(io.livres_a_migrer(self.base), [])

    def test_deplacement_conserve_la_validation(self):
        """
        Le point décisif : une page déjà transcrite doit rester reconnue comme
        terminée, sinon elle serait refaite et repayée.
        """
        self._ancienne_disposition()

        io.migrer_livre("Le Malentendu", self.base)

        self.assertTrue(io.unite_terminee(self.chemins.page_json(1)))
        self.assertEqual(io.lire_texte(self.chemins.page_txt(1)), "JAN\nA.")
        self.assertEqual(io.lire_texte(self.chemins.edit), "**JAN.**\nA.\n")

    def test_anciens_fichiers_retires_du_dossier_principal(self):
        self._ancienne_disposition()

        io.migrer_livre("Le Malentendu", self.base)

        self.assertEqual(io.livres_a_migrer(self.base), [])

    def test_idempotente(self):
        """Relancer la migration ne doit rien faire, ni rien casser."""
        self._ancienne_disposition()

        premier = io.migrer_livre("Le Malentendu", self.base)
        second = io.migrer_livre("Le Malentendu", self.base)

        self.assertTrue(premier)
        self.assertEqual(second, [])
        self.assertTrue(io.unite_terminee(self.chemins.page_json(1)))

    def test_ne_touche_pas_au_pdf_ni_au_docx(self):
        self.base.joinpath("Le Malentendu.pdf").write_bytes(b"%PDF")
        self.base.joinpath("Le Malentendu.docx").write_bytes(b"docx")
        self._ancienne_disposition()

        io.migrer_livre("Le Malentendu", self.base)

        self.assertTrue(self.chemins.pdf.is_file())
        self.assertTrue(self.chemins.docx.is_file())

    def test_journaux_migres(self):
        for etape in ("ocr", "edition"):
            io.ecrire_texte_atomique(
                self.base / config.NOM_JOURNAL.format(etape=etape), "{}"
            )

        deplaces = io.migrer_journaux(self.base)

        self.assertEqual(len(deplaces), 2)
        self.assertTrue(
            (io.dossier_temporaire(self.base) / "journal_ocr.json").is_file()
        )

    def test_destination_existante_preservee(self):
        """
        Si le nouveau fichier existe déjà, il est plus récent : on ne l'écrase
        pas avec l'ancien.
        """
        self._ancienne_disposition()
        io.ecrire_texte_atomique(self.chemins.ocr, "VERSION RECENTE")

        io.migrer_livre("Le Malentendu", self.base)

        self.assertEqual(io.lire_texte(self.chemins.ocr), "VERSION RECENTE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
