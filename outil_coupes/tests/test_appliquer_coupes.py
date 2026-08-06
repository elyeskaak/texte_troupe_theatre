"""
Tests de `appliquer_coupes`.

La résolution des plages et l'analyse des lignes sont testées sans dépendance.
La génération du .docx exige `python-docx` (dépendance réelle de l'outil de
matérialisation) : ce test se saute proprement si le module est absent.
"""
from __future__ import annotations

import unittest

import appliquer_coupes as ac


class ResoudrePlages(unittest.TestCase):
    TEXTE = "**JAN.**\nBonjour, comment vas-tu ce matin.\n\n**MARTHA.**\nTrès bien.\n"

    def test_texte_exact(self):
        plages = ac.resoudre_plages(self.TEXTE, [{"passe": 1, "texte": ", comment vas-tu"}])
        self.assertEqual(len(plages), 1)
        self.assertEqual(self.TEXTE[plages[0].debut:plages[0].fin], ", comment vas-tu")
        self.assertEqual(plages[0].passe, 1)

    def test_debut_fin_inclut_la_fin(self):
        plages = ac.resoudre_plages(self.TEXTE, [{"passe": 2, "debut": "comment", "fin": "ce matin"}])
        self.assertEqual(self.TEXTE[plages[0].debut:plages[0].fin], "comment vas-tu ce matin")

    def test_ancre_introuvable_leve(self):
        with self.assertRaises(ValueError):
            ac.resoudre_plages(self.TEXTE, [{"passe": 1, "texte": "absent du texte"}])

    def test_ancre_ambigue_leve(self):
        texte = "Oui. Oui. Oui."
        with self.assertRaises(ValueError):
            ac.resoudre_plages(texte, [{"passe": 1, "texte": "Oui."}])

    def test_passe_inconnue_leve(self):
        with self.assertRaises(ValueError):
            ac.resoudre_plages(self.TEXTE, [{"passe": 3, "texte": "Bonjour"}])

    def test_chevauchement_leve(self):
        coupes = [
            {"passe": 1, "texte": "Bonjour, comment"},
            {"passe": 2, "texte": "comment vas-tu"},
        ]
        with self.assertRaises(ValueError):
            ac.resoudre_plages(self.TEXTE, coupes)

    def test_plages_triees(self):
        coupes = [
            {"passe": 2, "texte": "Très bien"},
            {"passe": 1, "texte": "Bonjour"},
        ]
        plages = ac.resoudre_plages(self.TEXTE, coupes)
        self.assertLess(plages[0].debut, plages[1].debut)


class PasseAPosition(unittest.TestCase):
    def test_dedans_et_dehors(self):
        plages = [ac.Plage(2, 5, 1)]
        self.assertEqual(ac.passe_a_position(1, plages), 0)
        self.assertEqual(ac.passe_a_position(2, plages), 1)
        self.assertEqual(ac.passe_a_position(4, plages), 1)
        self.assertEqual(ac.passe_a_position(5, plages), 0)


class AnalyserLigne(unittest.TestCase):
    def _passes(self, ligne):
        return [0] * len(ligne)

    def test_titre_en_gras_sans_marqueurs(self):
        type_ligne, frags = ac.analyser_ligne("**ACTE I.**", self._passes("**ACTE I.**"))
        self.assertEqual(type_ligne, "titre")
        self.assertEqual("".join(f.texte for f in frags), "ACTE I.")
        self.assertTrue(all(f.gras for f in frags))

    def test_didascalie_en_italique(self):
        ligne = "*Une rue. Le soir.*"
        type_ligne, frags = ac.analyser_ligne(ligne, self._passes(ligne))
        self.assertEqual(type_ligne, "didascalie")
        self.assertEqual("".join(f.texte for f in frags), "Une rue. Le soir.")
        self.assertTrue(all(f.italique for f in frags))

    def test_separateur(self):
        type_ligne, frags = ac.analyser_ligne("***", self._passes("***"))
        self.assertEqual(type_ligne, "separateur")

    def test_replique_avec_emphase_inline(self):
        ligne = "Je crois *il hésite* que oui."
        type_ligne, frags = ac.analyser_ligne(ligne, self._passes(ligne))
        self.assertEqual(type_ligne, "replique")
        # les astérisques disparaissent, « il hésite » passe en italique
        self.assertEqual("".join(f.texte for f in frags), "Je crois il hésite que oui.")
        italiques = "".join(f.texte for f in frags if f.italique)
        self.assertEqual(italiques, "il hésite")

    def test_fragment_marque_la_coupe(self):
        ligne = "Bonjour tout le monde."
        passes = [0] * len(ligne)
        for i in range(8, 12):  # « tout »
            passes[i] = 1
        _, frags = ac.analyser_ligne(ligne, passes)
        coupes = "".join(f.texte for f in frags if f.passe == 1)
        self.assertEqual(coupes, "tout")


try:
    import docx  # noqa: F401

    _DOCX = True
except ImportError:
    _DOCX = False


@unittest.skipUnless(_DOCX, "python-docx non installé")
class GenerationDocx(unittest.TestCase):
    def test_deux_passes_produisent_deux_suppressions_colorees(self):
        import tempfile
        import zipfile
        from pathlib import Path

        texte = "**JAN.**\nBonjour tout le monde, vraiment.\n\n**MARTHA.**\nJe pars.\n"
        coupes = [
            {"passe": 1, "texte": ", vraiment"},
            {"passe": 2, "texte": "Je pars."},
        ]
        plages = ac.resoudre_plages(texte, coupes)
        document = ac.construire_document(texte, plages)

        with tempfile.TemporaryDirectory() as tmp:
            chemin = Path(tmp) / "out.docx"
            document.save(str(chemin))
            xml = zipfile.ZipFile(chemin).read("word/document.xml").decode("utf-8")

        self.assertEqual(xml.count("<w:del "), 2)
        self.assertIn("Coupe passe 1", xml)
        self.assertIn("Coupe passe 2", xml)
        self.assertIn("C00000", xml)
        self.assertIn("0070C0", xml)


if __name__ == "__main__":
    unittest.main()
