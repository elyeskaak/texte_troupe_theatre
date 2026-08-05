"""
Tests des invariants de `theatre_editor.config`.

`config.py` n'est que des données, mais ces données portent des exigences du
cahier des charges qu'aucun autre test ne vérifierait : hiérarchie des corps,
absence de couleur, marges généreuses, complétude des définitions de style.

Une faute de frappe dans `DEFINITIONS_STYLES` ne provoquerait pas d'erreur à
l'import — elle produirait un DOCX subtilement faux, plusieurs étapes plus
loin. Ces tests la font échouer immédiatement.
"""

from __future__ import annotations

import unittest

from theatre_editor import config

# Clés que toute définition de style doit fournir.
CLES_ATTENDUES = {
    "nom",
    "alignement",
    "gras",
    "italique",
    "taille_pt",
    "espace_avant_pt",
    "espace_apres_pt",
    "saut_de_page",
}

# Alignements que `docx_export._alignement()` sait traduire.
ALIGNEMENTS_VALIDES = {"centre", "justifie", "gauche", "droite"}


class TestHierarchieTypographique(unittest.TestCase):
    """Les corps demandés : acte 20, scène 18, personnage et texte 15."""

    def test_ordre_decroissant_des_titres(self):
        self.assertGreater(config.TAILLE_TITRE_ACTE_PT, config.TAILLE_TITRE_SCENE_PT)
        self.assertGreater(config.TAILLE_TITRE_SCENE_PT, config.TAILLE_TEXTE_PT)

    def test_valeurs_demandees(self):
        self.assertEqual(config.TAILLE_TITRE_ACTE_PT, 20)
        self.assertEqual(config.TAILLE_TITRE_SCENE_PT, 18)
        self.assertEqual(config.TAILLE_TEXTE_PT, 15)

    def test_personnage_a_la_taille_du_corps(self):
        """
        Exigence explicite : le nom de personnage se distingue par le gras et
        le centrage, jamais par la taille.
        """
        self.assertEqual(
            config.DEFINITIONS_STYLES["personnage"]["taille_pt"],
            config.TAILLE_TEXTE_PT,
        )

    def test_didascalie_et_lieu_a_la_taille_du_corps(self):
        for cle in ("lieu", "didascalie", "entree_distribution"):
            with self.subTest(style=cle):
                self.assertEqual(
                    config.DEFINITIONS_STYLES[cle]["taille_pt"],
                    config.TAILLE_TEXTE_PT,
                )


class TestDefinitionsStyles(unittest.TestCase):
    def test_toutes_les_cles_presentes(self):
        """Une clé oubliée produirait un style incomplet, pas une erreur."""
        for cle, definition in config.DEFINITIONS_STYLES.items():
            with self.subTest(style=cle):
                self.assertEqual(set(definition), CLES_ATTENDUES)

    def test_alignements_reconnus(self):
        """`docx_export` ne sait traduire que ces deux valeurs."""
        for cle, definition in config.DEFINITIONS_STYLES.items():
            with self.subTest(style=cle):
                self.assertIn(definition["alignement"], ALIGNEMENTS_VALIDES)

    def test_noms_de_styles_uniques(self):
        noms = [d["nom"] for d in config.DEFINITIONS_STYLES.values()]

        self.assertEqual(len(noms), len(set(noms)))

    def test_types_des_valeurs(self):
        for cle, definition in config.DEFINITIONS_STYLES.items():
            with self.subTest(style=cle):
                self.assertIsInstance(definition["nom"], str)
                self.assertIsInstance(definition["gras"], bool)
                self.assertIsInstance(definition["italique"], bool)
                self.assertIsInstance(definition["saut_de_page"], bool)
                self.assertGreater(definition["taille_pt"], 0)
                self.assertGreaterEqual(definition["espace_avant_pt"], 0)
                self.assertGreaterEqual(definition["espace_apres_pt"], 0)

    def test_aucune_couleur_definie(self):
        """
        « Aucune couleur » : on ne définit jamais de couleur, la valeur héritée
        étant le noir automatique. Aucun style ne doit donc porter une telle clé.
        """
        for cle, definition in config.DEFINITIONS_STYLES.items():
            with self.subTest(style=cle):
                self.assertFalse(
                    [c for c in definition if "couleur" in c or "color" in c]
                )

    def test_texte_justifie_et_titres_centres(self):
        self.assertEqual(config.DEFINITIONS_STYLES["texte"]["alignement"], "justifie")

        for cle in ("titre_acte", "titre_scene", "personnage", "didascalie", "lieu"):
            with self.subTest(style=cle):
                self.assertEqual(
                    config.DEFINITIONS_STYLES[cle]["alignement"], "centre"
                )

        # Les entrées de la liste des rôles sont alignées à gauche : ce sont des
        # lignes courtes, qu'une justification étirerait d'un bord à l'autre.
        self.assertEqual(
            config.DEFINITIONS_STYLES["entree_distribution"]["alignement"], "gauche"
        )


class TestSautsDePage(unittest.TestCase):
    """Le saut de page est réservé aux actes (décision n° 7)."""

    def test_acte_suit_sa_constante(self):
        self.assertIs(
            config.DEFINITIONS_STYLES["titre_acte"]["saut_de_page"],
            config.SAUT_DE_PAGE_AVANT_ACTE,
        )

    def test_scene_suit_sa_constante(self):
        self.assertIs(
            config.DEFINITIONS_STYLES["titre_scene"]["saut_de_page"],
            config.SAUT_DE_PAGE_AVANT_SCENE,
        )

    def test_distribution_suit_sa_constante(self):
        """La liste des rôles occupe une page à part entière."""
        self.assertIs(
            config.DEFINITIONS_STYLES["distribution"]["saut_de_page"],
            config.SAUT_DE_PAGE_AVANT_DISTRIBUTION,
        )

    def test_aucun_autre_style_ne_saute_de_page(self):
        for cle in ("entree_distribution", "lieu", "personnage", "didascalie", "texte"):
            with self.subTest(style=cle):
                self.assertFalse(config.DEFINITIONS_STYLES[cle]["saut_de_page"])

    def test_espace_avant_nul_sur_l_acte_si_saut_de_page(self):
        """
        Un espacement avant, en haut d'une page neuve, ne ferait que décaler
        le titre vers le bas sans rien apporter.
        """
        if config.SAUT_DE_PAGE_AVANT_ACTE:
            self.assertEqual(
                config.DEFINITIONS_STYLES["titre_acte"]["espace_avant_pt"], 0
            )


class TestMiseEnPage(unittest.TestCase):
    def test_marges_genereuses(self):
        self.assertGreaterEqual(config.MARGE_CM, 2.5)

    def test_police_demandee(self):
        self.assertEqual(config.POLICE_TEXTE, "EB Garamond")


class TestCoherenceGenerale(unittest.TestCase):
    def test_ratio_dans_un_intervalle_sensé(self):
        self.assertTrue(0.0 < config.RATIO_MINIMAL_LONGUEUR <= 1.0)

    def test_decoupage_exploitable(self):
        self.assertGreaterEqual(config.PAGES_PAR_BLOC, 1)
        self.assertGreaterEqual(config.LIGNES_CONTEXTE_RACCORD, 1)

    def test_tentatives_et_pauses(self):
        self.assertGreaterEqual(config.MAX_TENTATIVES, 1)
        self.assertGreaterEqual(config.PAUSE_ENTRE_APPELS, 0)
        self.assertGreater(config.ATTENTE_MAX_BACKOFF, config.ATTENTE_BASE_BACKOFF)

    def test_degradation_dpi_possible(self):
        self.assertLess(config.DPI_MINIMAL, config.DPI_RASTERISATION)
        self.assertTrue(0 < config.FACTEUR_REDUCTION_DPI < 1)

    def test_lexiques_sans_accents(self):
        """
        Les lexiques sont comparés à une forme normalisée sans accents. Un
        « SCÈNE » accentué dans le lexique ne matcherait jamais.
        """
        for lexique in (
            config.LEXIQUE_ACTE,
            config.LEXIQUE_SCENE,
            config.NOMBRES_ECRITS,
            config.ETIQUETTES_DISTRIBUTION,
        ):
            for mot in lexique:
                with self.subTest(mot=mot):
                    self.assertEqual(mot, mot.upper())
                    self.assertTrue(mot.isascii())

    def test_lexiques_acte_et_scene_disjoints(self):
        """Un même mot dans les deux lexiques rendrait le classement ambigu."""
        self.assertEqual(config.LEXIQUE_ACTE & config.LEXIQUE_SCENE, frozenset())

    def test_statuts_distincts(self):
        statuts = {config.STATUT_TERMINE, config.STATUT_SUSPECT, config.STATUT_ECHEC}

        self.assertEqual(len(statuts), 3)

    def test_separateur_page_contient_le_marqueur(self):
        self.assertIn("<<<PAGE_BREAK>>>", config.SEPARATEUR_PAGE)

    def test_marqueur_page_formatable(self):
        self.assertEqual(config.MARQUEUR_PAGE.format(numero=7), "[PAGE 7]")


if __name__ == "__main__":
    unittest.main(verbosity=2)
