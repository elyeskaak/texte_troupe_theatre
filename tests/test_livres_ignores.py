"""
Tests du fichier-liste `ignorer.txt`, qui exclut des livres du traitement.

Deux ouvrages étaient déjà traités par un autre outil : les relancer aurait
consommé des tokens pour un résultat inutile. Le fichier-liste permet de les
écarter **depuis le Drive**, en une ligne par livre, sans toucher au code ni à
`config.py` — une liste codée en dur aurait supposé un commit pour chaque livre
ajouté ou retiré (ARCHITECTURE.md §9.9).

La propriété essentielle n'est pas l'exclusion elle-même mais son **annonce** :
un livre écarté en silence serait indiscernable d'un livre oublié, et la
première réaction serait de chercher la panne.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from theatre_editor import config
from theatre_editor.utils import io


class BaseDossier(unittest.TestCase):
    def setUp(self):
        self._verbosite = config.VERBOSITE
        config.VERBOSITE = 0

        self._dossier = tempfile.TemporaryDirectory()
        self.base = Path(self._dossier.name)

        for nom in ("Kermann", "Koltes", "Brecht"):
            (self.base / f"{nom}.pdf").write_bytes(b"%PDF-1.4\n")

    def tearDown(self):
        self._dossier.cleanup()
        config.VERBOSITE = self._verbosite

    def ecrire_liste(self, contenu: str) -> Path:
        """Écrit `ignorer.txt` avec le contenu donné."""
        chemin = io.chemin_fichier_ignorer(self.base)
        chemin.write_text(contenu, encoding="utf-8")

        return chemin

    def marquer_ancien(self, nom: str) -> Path:
        """Dépose un ancien marqueur `<Livre>.ignorer` (mécanisme retiré)."""
        chemin = self.base / f"{nom}.ignorer"
        chemin.write_text("", encoding="utf-8")

        return chemin


class TestDetection(BaseDossier):
    def test_sans_fichier_aucun_livre_ignore(self):
        self.assertFalse(io.livre_ignore("Kermann", self.base))
        self.assertEqual(io.lire_livres_ignores(self.base), [])

    def test_nom_liste_est_ignore(self):
        self.ecrire_liste("Brecht\n")

        self.assertTrue(io.livre_ignore("Brecht", self.base))
        self.assertFalse(io.livre_ignore("Kermann", self.base))

    def test_comparaison_insensible_a_la_casse(self):
        """Le fichier est saisi à la main : « brecht » doit écarter « Brecht »."""
        self.ecrire_liste("brecht\n")

        self.assertTrue(io.livre_ignore("Brecht", self.base))

    def test_extension_pdf_toleree(self):
        """Écrire « Brecht.pdf » est un réflexe naturel : il doit fonctionner."""
        self.ecrire_liste("Brecht.pdf\n")

        self.assertTrue(io.livre_ignore("Brecht", self.base))

    def test_lignes_vides_et_commentaires_ignores(self):
        self.ecrire_liste(
            "# livres deja traites par l'ancien logiciel\n"
            "\n"
            "Brecht\n"
            "\n"
            "# Koltes est en relecture\n"
            "Koltes\n"
        )

        self.assertEqual(io.lire_livres_ignores(self.base), ["Brecht", "Koltes"])
        self.assertTrue(io.livre_ignore("Brecht", self.base))
        self.assertTrue(io.livre_ignore("Koltes", self.base))
        self.assertFalse(io.livre_ignore("Kermann", self.base))

    def test_emplacement_du_fichier_previsible(self):
        """Le chemin est ce que l'utilisateur reproduit sur son Drive."""
        chemin = io.chemin_fichier_ignorer(self.base)

        self.assertEqual(chemin.name, config.NOM_FICHIER_IGNORER)
        self.assertEqual(chemin.parent, self.base)


class TestExclusionEffective(BaseDossier):
    def test_le_livre_liste_disparait(self):
        self.ecrire_liste("Brecht\n")

        noms = [chemin.stem for chemin in io.lister_pdf(self.base)]

        self.assertNotIn("Brecht", noms)
        self.assertEqual(noms, ["Kermann", "Koltes"])

    def test_exclusion_chirurgicale(self):
        """Le défaut redouté serait qu'une entrée écarte tout le dossier."""
        self.ecrire_liste("Brecht\nKoltes\n")

        noms = [chemin.stem for chemin in io.lister_pdf(self.base)]

        self.assertEqual(noms, ["Kermann"])

    def test_nom_orphelin_sans_effet(self):
        """Un nom sans PDF correspondant ne doit rien perturber."""
        self.ecrire_liste("Livre inexistant\n")

        noms = [chemin.stem for chemin in io.lister_pdf(self.base)]

        self.assertEqual(noms, ["Brecht", "Kermann", "Koltes"])

    def test_le_fichier_liste_n_est_pas_pris_pour_une_source(self):
        self.ecrire_liste("Brecht\n")

        for chemin in io.lister_pdf(self.base):
            with self.subTest(chemin=chemin.name):
                self.assertEqual(chemin.suffix.lower(), ".pdf")

    def test_retirer_le_nom_reintegre_le_livre(self):
        """Réversible sans intervention : c'est ce qui rend le mécanisme
        utilisable depuis le Drive."""
        self.ecrire_liste("Brecht\n")
        self.assertNotIn("Brecht", [c.stem for c in io.lister_pdf(self.base)])

        self.ecrire_liste("")
        self.assertIn("Brecht", [c.stem for c in io.lister_pdf(self.base)])


class TestRecensement(BaseDossier):
    def test_vide_par_defaut(self):
        self.assertEqual(io.lire_livres_ignores(self.base), [])

    def test_ordre_du_fichier_preserve(self):
        """L'annonce doit refléter fidèlement ce que l'utilisateur a saisi."""
        self.ecrire_liste("zola\nBrecht\nartaud\n")

        self.assertEqual(
            io.lire_livres_ignores(self.base), ["zola", "Brecht", "artaud"]
        )


class TestMarqueursObsoletes(BaseDossier):
    def test_ancien_marqueur_recense(self):
        self.marquer_ancien("Brecht")

        self.assertEqual(io.marqueurs_ignorer_obsoletes(self.base), ["Brecht.ignorer"])

    def test_ancien_marqueur_sans_effet_sur_le_traitement(self):
        """
        Le mécanisme par marqueur est retiré : un `<Livre>.ignorer` laissé sur
        le Drive n'exclut plus rien. On le recense pour l'annoncer, mais le
        livre repart bel et bien au traitement.
        """
        self.marquer_ancien("Brecht")

        noms = [chemin.stem for chemin in io.lister_pdf(self.base)]

        self.assertIn("Brecht", noms)

    def test_fichier_liste_n_est_pas_un_marqueur_obsolete(self):
        self.ecrire_liste("Brecht\n")

        self.assertEqual(io.marqueurs_ignorer_obsoletes(self.base), [])


class TestAnnonce(BaseDossier):
    def test_les_livres_ecartes_sont_annonces(self):
        """
        La propriété qui compte. Sans annonce, un livre écarté ressemblerait à
        un livre oublié, et la recherche partirait sur une fausse piste.
        """
        from theatre_editor import ocr

        self.ecrire_liste("Brecht\nKoltes\n")
        config.VERBOSITE = 1

        annonces = ocr._annoncer_livres_ignores(self.base)

        self.assertEqual(annonces, ["Brecht", "Koltes"])

    def test_marqueur_obsolete_annonce_sans_exclure(self):
        """Un ancien marqueur est signalé, mais n'écarte plus le livre."""
        from theatre_editor import ocr

        self.marquer_ancien("Brecht")
        config.VERBOSITE = 1

        annonces = ocr._annoncer_livres_ignores(self.base)

        self.assertEqual(annonces, [])
        self.assertIn("Brecht", [c.stem for c in io.lister_pdf(self.base)])

    def test_aucune_annonce_sans_fichier(self):
        from theatre_editor import ocr

        self.assertEqual(ocr._annoncer_livres_ignores(self.base), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
