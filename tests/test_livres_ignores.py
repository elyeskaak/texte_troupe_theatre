"""
Tests du marqueur `.ignorer`, qui exclut un livre du traitement.

Deux ouvrages étaient déjà traités par un autre outil : les relancer aurait
consommé des tokens pour un résultat inutile. Le marqueur permet de les écarter
**depuis le Drive**, en déposant un fichier à côté du PDF, sans toucher au code
ni à `config.py` — une liste codée en dur aurait supposé un commit pour chaque
livre ajouté ou retiré.

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

    def marquer(self, nom: str, raison: str = "") -> Path:
        chemin = io.chemin_marqueur_ignorer(nom, self.base)
        chemin.write_text(raison, encoding="utf-8")

        return chemin


class TestDetectionDuMarqueur(BaseDossier):
    def test_sans_marqueur_le_livre_est_traite(self):
        self.assertIsNone(io.livre_ignore("Kermann", self.base))

    def test_raison_restituee(self):
        self.marquer("Brecht", "déjà traité par l'ancien logiciel")

        self.assertEqual(
            io.livre_ignore("Brecht", self.base),
            "déjà traité par l'ancien logiciel",
        )

    def test_marqueur_vide_donne_une_raison_par_defaut(self):
        """
        Le plus simple à créer depuis le Drive est un fichier vide. Il doit
        fonctionner, et produire tout de même une mention affichable — sinon
        l'annonce afficherait une ligne blanche.
        """
        self.marquer("Brecht")

        raison = io.livre_ignore("Brecht", self.base)

        self.assertTrue(raison)
        self.assertIsInstance(raison, str)

    def test_raison_multiligne_nettoyee(self):
        self.marquer("Brecht", "\n  déjà traité  \n\n")

        self.assertEqual(io.livre_ignore("Brecht", self.base), "déjà traité")

    def test_emplacement_du_marqueur_previsible(self):
        """
        Le chemin est ce que l'utilisateur doit reproduire à la main sur son
        Drive : il doit être exactement « <nom du PDF> + suffixe ».
        """
        chemin = io.chemin_marqueur_ignorer("Kermann", self.base)

        self.assertEqual(chemin.name, f"Kermann{config.SUFFIXE_IGNORER}")
        self.assertEqual(chemin.parent, self.base)


class TestExclusionEffective(BaseDossier):
    def test_le_pdf_marque_disparait_de_la_liste(self):
        self.marquer("Brecht", "déjà traité")

        noms = [chemin.stem for chemin in io.lister_pdf(self.base)]

        self.assertNotIn("Brecht", noms)
        self.assertEqual(noms, ["Kermann", "Koltes"])

    def test_les_autres_livres_restent_traites(self):
        """
        L'exclusion doit être chirurgicale : le défaut redouté serait qu'un
        marqueur écarte tout le dossier.
        """
        self.marquer("Brecht")
        self.marquer("Koltes")

        noms = [chemin.stem for chemin in io.lister_pdf(self.base)]

        self.assertEqual(noms, ["Kermann"])

    def test_marqueur_orphelin_sans_effet(self):
        """Un marqueur sans PDF correspondant ne doit rien perturber."""
        self.marquer("Livre inexistant", "vestige")

        noms = [chemin.stem for chemin in io.lister_pdf(self.base)]

        self.assertEqual(noms, ["Brecht", "Kermann", "Koltes"])

    def test_le_marqueur_n_est_pas_pris_pour_un_pdf(self):
        self.marquer("Brecht")

        for chemin in io.lister_pdf(self.base):
            with self.subTest(chemin=chemin.name):
                self.assertEqual(chemin.suffix.lower(), ".pdf")

    def test_retirer_le_marqueur_reintegre_le_livre(self):
        """
        L'opération doit être réversible sans intervention : c'est ce qui rend le
        mécanisme utilisable depuis le Drive.
        """
        marqueur = self.marquer("Brecht")

        self.assertNotIn("Brecht", [c.stem for c in io.lister_pdf(self.base)])

        marqueur.unlink()

        self.assertIn("Brecht", [c.stem for c in io.lister_pdf(self.base)])


class TestRecensement(BaseDossier):
    def test_aucun_livre_ignore_par_defaut(self):
        self.assertEqual(io.livres_ignores(self.base), {})

    def test_recensement_avec_raisons(self):
        self.marquer("Brecht", "déjà traité")
        self.marquer("Koltes", "en cours de relecture")

        self.assertEqual(
            io.livres_ignores(self.base),
            {"Brecht": "déjà traité", "Koltes": "en cours de relecture"},
        )

    def test_ordre_alphabetique_insensible_a_la_casse(self):
        """L'annonce doit être lisible, donc ordonnée de façon prévisible."""
        for nom in ("zola", "Brecht", "artaud"):
            self.marquer(nom)

        self.assertEqual(
            list(io.livres_ignores(self.base)), ["artaud", "Brecht", "zola"]
        )


class TestAnnonce(BaseDossier):
    def test_les_livres_ecartes_sont_annonces(self):
        """
        La propriété qui compte. Sans annonce, un livre écarté ressemblerait à
        un livre oublié, et la recherche partirait sur une fausse piste.
        """
        from theatre_editor import ocr

        self.marquer("Brecht", "déjà traité par l'ancien logiciel")

        config.VERBOSITE = 1

        annonces = ocr._annoncer_livres_ignores(self.base)

        self.assertEqual(annonces, {"Brecht": "déjà traité par l'ancien logiciel"})

    def test_aucune_annonce_sans_marqueur(self):
        from theatre_editor import ocr

        self.assertEqual(ocr._annoncer_livres_ignores(self.base), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
