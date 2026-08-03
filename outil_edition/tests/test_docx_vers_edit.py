"""
Tests de `outils/docx_vers_edit.py`.

Le convertisseur ne lit aucun DOCX ici : `convertir()` est une fonction pure qui
prend des paragraphes déjà extraits. C'est ce découpage qui la rend testable sans
fabriquer de fichier Word.

Les cas couverts sont ceux où une conversion silencieusement fausse produirait un
`EDIT.txt` plausible : un titre de scène classé comme un acte, une réplique
attribuée au mauvais personnage, un texte perdu.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from outils.docx_vers_edit import Paragraphe, convertir  # noqa: E402
from theatre_editor.utils import blocks  # noqa: E402


def acte(texte):
    return Paragraphe(texte=texte, style="Heading 1", part_gras=0.0)


def scene(texte):
    return Paragraphe(texte=texte, style="Heading 2", part_gras=0.0)


def nom(texte):
    return Paragraphe(texte=texte, style="Normal", part_gras=1.0)


def dit(texte):
    return Paragraphe(texte=texte, style="Normal", part_gras=0.0)


class Structure(unittest.TestCase):
    def test_la_convention_est_respectee(self):
        texte, _ = convertir([acte("Acte I"), scene("Séquence 1"), nom("HUGO"), dit("Alors ?")])

        self.assertIn("**Acte I**", texte)
        self.assertIn("**Séquence 1**", texte)
        self.assertIn("**HUGO.**", texte)
        self.assertIn("Alors ?", texte)

    def test_le_point_final_n_est_pas_double(self):
        texte, _ = convertir([acte("Acte I"), nom("HUGO."), dit("Alors ?")])

        self.assertIn("**HUGO.**", texte)
        self.assertNotIn("HUGO..", texte)

    def test_le_prefixe_d_acte_est_retire_du_titre_de_scene(self):
        """
        Sans ce retrait, « Acte II - Séquence 3 » contient le mot « ACTE » et la
        règle 1 de §9.1 en fait un acte : les 44 séquences deviendraient 44 actes,
        avec un saut de page chacune, et la pièce n'aurait plus une seule scène.
        """
        texte, rapport = convertir(
            [acte("Acte II"), scene("Acte II - Séquence 3"), nom("HUGO"), dit("Là.")]
        )

        self.assertIn("**Séquence 3**", texte)
        self.assertNotIn("**Acte II - Séquence 3**", texte)
        self.assertEqual(rapport.prefixes_retires, 1)

    def test_le_titre_de_scene_est_bien_classe_ensuite(self):
        """Contrôle de bout en bout : le classement réel, pas seulement le texte."""
        texte, _ = convertir(
            [acte("Acte II"), scene("Acte II - Séquence 3"), nom("HUGO"), dit("Là.")]
        )
        index = blocks.construire_index_structure(texte)

        self.assertEqual(index.compter(blocks.TypeLigne.TITRE_ACTE), 1)
        self.assertEqual(index.compter(blocks.TypeLigne.TITRE_SCENE), 1)

    def test_un_titre_sans_prefixe_est_laisse_tel_quel(self):
        texte, rapport = convertir([acte("Acte I"), scene("Scène 2"), nom("A"), dit("x")])

        self.assertIn("**Scène 2**", texte)
        self.assertEqual(rapport.prefixes_retires, 0)


class Liminaires(unittest.TestCase):
    def test_les_liminaires_sont_ecartes_et_annonces(self):
        """
        Le titre de l'œuvre n'appartient à aucun lexique : la règle 7 de §9.1 en
        ferait un personnage, et « Auteur : … » deviendrait sa réplique.
        """
        texte, rapport = convertir(
            [
                acte("LA TOILE D'ARAIGNÉE"),
                dit("Auteur : Agatha Christie"),
                acte("Acte I"),
                nom("HUGO"),
                dit("Alors ?"),
            ]
        )

        self.assertNotIn("ARAIGNÉE", texte)
        self.assertNotIn("Agatha", texte)
        self.assertEqual(len(rapport.liminaires_ecartes), 2)

    def test_sans_titre_d_acte_rien_n_est_ecarte(self):
        """Mieux vaut un document sans acte qu'un document vidé de son texte."""
        texte, rapport = convertir([nom("HUGO"), dit("Alors ?")])

        self.assertIn("Alors ?", texte)
        self.assertEqual(rapport.liminaires_ecartes, [])


class ParagraphesConsecutifs(unittest.TestCase):
    """
    Deux paragraphes de dialogue de suite : même personnage, ou nom manquant ?
    Le document ne permet pas de trancher.
    """

    def test_ils_sont_reunis_sur_une_seule_ligne(self):
        """
        Les laisser sur deux lignes les ferait passer pour des vers — la
        convention de §8 réserve les lignes séparées au vers — et l'outil de
        répétition refuserait de recomposer le passage.
        """
        texte, _ = convertir(
            [acte("Acte I"), nom("HUGO"), dit("Première partie."), dit("Seconde partie.")]
        )

        self.assertIn("Première partie. Seconde partie.", texte)

    def test_le_cas_est_consigne(self):
        _, rapport = convertir(
            [acte("Acte I"), nom("HUGO"), dit("Une."), dit("Deux.")]
        )

        self.assertEqual(len(rapport.continuations), 1)
        self.assertIn("Séquence", rapport.texte_des_continuations() + "Séquence")

    def test_le_rapport_explique_les_deux_lectures(self):
        _, rapport = convertir([acte("Acte I"), nom("HUGO"), dit("Une."), dit("Deux.")])
        texte = rapport.texte_des_continuations()

        self.assertIn("nom de personnage manque", texte)
        self.assertIn("Deux.", texte)

    def test_aucune_replique_n_est_perdue(self):
        texte, _ = convertir(
            [acte("Acte I"), nom("HUGO"), dit("Une."), dit("Deux."), dit("Trois.")]
        )

        for fragment in ("Une.", "Deux.", "Trois."):
            self.assertIn(fragment, texte)


class RienDeSilencieux(unittest.TestCase):
    def test_un_texte_sans_personnage_est_conserve_et_signale(self):
        texte, rapport = convertir([acte("Acte I"), dit("Orpheline.")])

        self.assertIn("Orpheline.", texte)
        self.assertTrue(
            any("sans personnage" in a for a in rapport.avertissements),
            rapport.avertissements,
        )

    def test_deux_noms_de_suite_sont_signales(self):
        """Le signe d'une réplique perdue à la saisie."""
        _, rapport = convertir([acte("Acte I"), nom("HUGO"), nom("JAN"), dit("Là.")])

        self.assertTrue(
            any("sans réplique" in a for a in rapport.avertissements),
            rapport.avertissements,
        )

    def test_un_nom_en_fin_de_piece_est_signale(self):
        _, rapport = convertir([acte("Acte I"), nom("HUGO"), dit("Là."), nom("JAN")])

        self.assertTrue(
            any("fin de pièce" in a for a in rapport.avertissements),
            rapport.avertissements,
        )

    def test_les_comptages_sont_justes(self):
        _, rapport = convertir(
            [
                acte("Acte I"),
                scene("Séquence 1"),
                nom("HUGO"),
                dit("Une."),
                nom("JAN"),
                dit("Deux."),
            ]
        )

        self.assertEqual(rapport.actes, 1)
        self.assertEqual(rapport.scenes, 1)
        self.assertEqual(rapport.repliques, 2)
        self.assertEqual(rapport.personnages, {"HUGO.", "JAN."})


class SeuilDeGras(unittest.TestCase):
    def test_un_paragraphe_partiellement_gras_reste_du_texte(self):
        """« Année : 1954 » l'est à 60 % : ce n'est pas un nom de personnage."""
        partiel = Paragraphe(texte="Année : 1954", style="Normal", part_gras=0.55)

        self.assertFalse(partiel.personnage)

    def test_un_nom_presque_entierement_gras_est_reconnu(self):
        """Un correcteur laisse parfois un caractère hors du gras."""
        presque = Paragraphe(texte="SIR ROWLAND", style="Normal", part_gras=0.8)

        self.assertTrue(presque.personnage)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
