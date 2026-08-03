"""
Tests des pages liminaires et des pages blanches.

Ces cas viennent d'éditions réelles : page de titre, épigraphes, note
d'éditeur, monologue introductif en italique, numéros de page décorés, et pages
blanches intercalées.

Le point le plus important est la **page blanche**. Elle est normale dans un
livre imprimé, et la soumettre au modèle coûte un appel pour rien — mais
l'expose surtout à répondre autre chose que la mention attendue, réponse qui
serait alors écrite dans `OCR.txt` comme du texte de la pièce.
"""

from __future__ import annotations

import unittest
from unittest import mock

from theatre_editor import config, ocr
from theatre_editor.utils import blocks


class PageFactice:
    """Page dont on choisit la couche texte et la proportion d'encre."""

    def __init__(self, couche_texte: str = "", part_encre: float = 0.0):
        self.couche_texte = couche_texte
        self.part_encre = part_encre

    def get_text(self, *_args, **_kwargs) -> str:
        return self.couche_texte

    def get_pixmap(self, dpi: int):
        total = 10_000
        sombres = int(total * self.part_encre)
        octets = b"\x00" * sombres + b"\xff" * (total - sombres)

        return type("Pixmap", (), {"samples": octets})()


# ============================================================
# 1. DÉCLARATIONS DE PAGE VIDE
# ============================================================


class TestDeclarationPageVide(unittest.TestCase):
    """
    Le prompt impose une mention exacte, mais un modèle paraphrase parfois.

    Sans reconnaissance des variantes, sa phrase était écrite dans `OCR.txt`
    **comme si c'était le texte de la pièce**, puis rendue dans le DOCX. C'est
    pire qu'une erreur : une corruption silencieuse.
    """

    def test_mention_exacte(self):
        self.assertTrue(
            blocks.est_declaration_page_vide(config.MENTION_PAGE_SANS_TEXTE)
        )

    def test_paraphrases_reconnues(self):
        for reponse in (
            "Cette page est vide.",
            "Page blanche.",
            "Il n'y a aucun texte sur cette image.",
            "Il n'y a pas de texte.",
            "This page is blank.",
            "The page is empty.",
            "No text found.",
        ):
            with self.subTest(reponse=reponse):
                self.assertTrue(blocks.est_declaration_page_vide(reponse))

    def test_reponse_vide_n_en_est_pas_une(self):
        """
        Une réponse vide peut trahir un incident d'appel : elle est traitée
        séparément, et donne lieu à une reprise.
        """
        for vide in ("", "   ", "\n\n"):
            with self.subTest(valeur=repr(vide)):
                self.assertFalse(blocks.est_declaration_page_vide(vide))

    def test_vraie_page_contenant_la_formule_non_confondue(self):
        """
        Garde-fou : le plafond de longueur empêche de prendre une page réelle
        pour une déclaration, même si la formule y figure par hasard.
        """
        page = "JAN\nBonjour. " * 60 + "il n'y a pas de texte ici"

        self.assertGreater(len(page), config.MAX_LONGUEUR_DECLARATION_VIDE)
        self.assertFalse(blocks.est_declaration_page_vide(page))


# ============================================================
# 2. DÉTECTION LOCALE DES PAGES BLANCHES
# ============================================================


class TestPageBlanche(unittest.TestCase):
    """
    Le test est sévère à dessein. L'asymétrie est nette : manquer une page
    blanche coûte un appel, sauter une page imprimée perdrait du texte.
    """

    def test_page_entierement_blanche(self):
        self.assertTrue(ocr.page_blanche(PageFactice(part_encre=0.0)))

    def test_poussiere_de_numerisation_toleree(self):
        part = config.PROPORTION_ENCRE_MAXIMALE / 2

        self.assertTrue(ocr.page_blanche(PageFactice(part_encre=part)))

    def test_page_imprimee_non_blanche(self):
        """Une seule ligne de texte dépasse déjà largement le seuil."""
        self.assertFalse(ocr.page_blanche(PageFactice(part_encre=0.01)))

    def test_page_a_impression_pale_passe_par_la_vision(self):
        part = config.PROPORTION_ENCRE_MAXIMALE * 5

        self.assertFalse(ocr.page_blanche(PageFactice(part_encre=part)))

    def test_couche_texte_interdit_de_conclure_a_la_blancheur(self):
        page = PageFactice(couche_texte="JAN\nBonjour.", part_encre=0.0)

        self.assertFalse(ocr.page_blanche(page))

    def test_desactivation_par_configuration(self):
        with mock.patch.object(config, "DETECTER_PAGES_BLANCHES", False):
            self.assertFalse(ocr.page_blanche(PageFactice(part_encre=0.0)))

    def test_echec_de_rasterisation_n_est_jamais_blanc(self):
        """
        Une page illisible ne doit pas être prise pour blanche : mieux vaut
        payer un appel que perdre une page imprimée.
        """

        class PageCassee:
            def get_text(self, *_args, **_kwargs) -> str:
                return ""

            def get_pixmap(self, dpi: int):
                raise RuntimeError("pixmap indisponible")

        self.assertEqual(ocr.proportion_encre(PageCassee()), 1.0)
        self.assertFalse(ocr.page_blanche(PageCassee()))


# ============================================================
# 3. MISE EN FORME DES LIMINAIRES
# ============================================================


class TestLiminaires(unittest.TestCase):
    def test_titre_de_l_oeuvre_reconnu(self):
        """
        Le premier intitulé d'un document, qu'aucun indice ne permet de classer,
        est le titre de l'œuvre. Sans cette règle il était rendu en corps 11,
        comme un nom de personnage.
        """
        texte = (
            "**La mastication des morts**\n"
            "**Patrick Kermann**\n"
            "\n"
            "**JAN.**\nBonjour.\n**JAN.**\nEncore.\n"
        )

        index = blocks.construire_index_structure(texte)

        self.assertIs(
            index.type_de("LA MASTICATION DES MORTS"), blocks.TypeLigne.TITRE_OEUVRE
        )

    def test_un_personnage_identifie_n_est_jamais_promu_titre(self):
        """
        La règle ne s'applique qu'aux labels incertains : un rôle reconnu par
        une réplique ou par la distribution ne doit pas être touché.
        """
        texte = "**JAN.**\nBonjour.\n**JAN.**\nEncore.\n"

        index = blocks.construire_index_structure(texte)

        self.assertIs(index.type_de("JAN"), blocks.TypeLigne.PERSONNAGE)

    def test_intitule_tardif_non_promu(self):
        """Un intitulé apparaissant loin du début n'ouvre pas une page de titre."""
        texte = "\n".join(f"Ligne {i}." for i in range(40))
        texte += "\n**UNE VOIX TARDIVE**\n\n*Silence.*\n"

        index = blocks.construire_index_structure(texte)

        self.assertIsNot(
            index.type_de("UNE VOIX TARDIVE"), blocks.TypeLigne.TITRE_OEUVRE
        )

    def test_prose_italique_longue_justifiee(self):
        """Centrer un monologue liminaire de quarante lignes serait illisible."""
        longue = "*" + "A Landon, je suis descendu de la micheline rouge. " * 8 + "*"

        index = blocks.construire_index_structure(longue)
        lignes = blocks.classifier_document(longue, index)

        self.assertIs(lignes[0].type, blocks.TypeLigne.DIDASCALIE_LONGUE)

    def test_didascalie_breve_reste_centree(self):
        index = blocks.construire_index_structure("*Pause.*\n")
        lignes = blocks.classifier_document("*Pause.*\n", index)

        self.assertIs(lignes[0].type, blocks.TypeLigne.DIDASCALIE)

    def test_seuil_de_bascule_lu_dans_la_configuration(self):
        texte = "*" + "x" * (config.LONGUEUR_DIDASCALIE_LONGUE + 10) + "*"

        index = blocks.construire_index_structure(texte)
        lignes = blocks.classifier_document(texte, index)

        self.assertIs(lignes[0].type, blocks.TypeLigne.DIDASCALIE_LONGUE)

    def test_numeros_de_page_decores_ecartes(self):
        """
        L'étape 2 devrait les retirer, mais sa consigne ne parle que de
        « numéros isolés » : la version encadrée peut lui échapper.
        """
        for ligne in ("——— 7 ———", "- 52 -", "« 19 »", "7", "· 3 ·"):
            with self.subTest(ligne=ligne):
                index = blocks.construire_index_structure(ligne)
                lignes = blocks.classifier_document(ligne, index)

                self.assertIs(lignes[0].type, blocks.TypeLigne.VIDE)

    def test_texte_contenant_un_nombre_conserve(self):
        for ligne in ("JAN 7 fois", "Il en reste 3 dans la boîte."):
            with self.subTest(ligne=ligne):
                index = blocks.construire_index_structure(ligne)
                lignes = blocks.classifier_document(ligne, index)

                self.assertIs(lignes[0].type, blocks.TypeLigne.TEXTE)


# ============================================================
# 4. OÙ S'ARRÊTE LA LISTE DES RÔLES
# ============================================================


class TestFinDeLaDistribution(unittest.TestCase):
    """
    La distribution est lue **par position** : toute ligne suivant l'étiquette
    lui appartient. Cette lecture est ce qui permet de traiter une liste en un
    seul bloc, sans avoir à reconnaître chaque nom. Sa contrepartie est qu'il
    faut savoir où elle s'arrête.

    Le critère est l'enchaînement sur une réplique : une entrée de distribution
    n'en est jamais suivie, un nom de personnage l'est toujours. Sans lui, la
    liste avalait tout le document — défaut observé sur un livre réel.
    """

    def test_s_arrete_au_premier_nom_suivi_d_une_replique(self):
        texte = (
            "**PERSONNAGES**\n"
            "Gilles Rimey.\n"
            "Alphonsine Rouart.\n"
            "\n"
            "**JAN.**\n"
            "Bonjour.\n"
            "**JAN.**\n"
            "Encore.\n"
        )

        index = blocks.construire_index_structure(texte)
        types = {ligne.texte: ligne.type for ligne in blocks.classifier_document(texte, index)}

        self.assertIs(types["Gilles Rimey."], blocks.TypeLigne.ENTREE_DISTRIBUTION)
        self.assertIs(types["Bonjour."], blocks.TypeLigne.TEXTE)
        self.assertIs(types["JAN."], blocks.TypeLigne.PERSONNAGE)

    def test_s_arrete_devant_une_replique_en_ligne(self):
        """Même défaut, avec la forme « **NOM.** texte » sur une seule ligne."""
        texte = "**PERSONNAGES**\nGilles Rimey.\n**JAN.** Bonjour.\n**JAN.** Encore.\n"

        _, indices = blocks.recenser_distribution(texte)

        lignes = texte.split("\n")
        retenues = {lignes[i] for i in indices}

        self.assertIn("Gilles Rimey.", retenues)
        self.assertNotIn("**JAN.** Bonjour.", retenues)

    def test_liste_en_un_seul_bloc_n_emprunte_rien_au_dehors(self):
        """
        Cas Brecht : toute la distribution tient sur une seule ligne. Les
        intitulés qui la suivent ne doivent pas être pris pour des rôles — ils
        deviendraient des amorces, et chaque occurrence de l'intitulé dans le
        corps du texte serait rendue en gras centré.

        Cette liste ne fournit pour autant aucune amorce exploitable : les noms
        y sont agglutinés, et les séparer demanderait de deviner où l'un finit.
        C'est une limite assumée, que l'étape des liminaires absorbe. Ce test
        garantit seulement l'innocuité, qui est le point important : une amorce
        fausse dégrade toutes les pages, une amorce absente n'en dégrade aucune.
        """
        texte = (
            "**PERSONNAGES**\n"
            "LES TROIS DIEUX. SHEN TÉ. WANG, marchand d'eau.\n"
            "\n"
            "**LIEU DE L'ACTION**\n"
            "La capitale du Se-Tchouan.\n"
            "\n"
            "**WANG.** Je suis porteur d'eau.\n"
        )

        noms, indices = blocks.recenser_distribution(texte)

        # Aucune amorce ne provient d'une ligne située hors de la liste.
        self.assertEqual(indices, frozenset({1}))

        for nom in noms:
            with self.subTest(nom=nom):
                self.assertNotIn("LIEU", nom)
                self.assertNotIn("CAPITALE", nom)

    def test_roles_en_gras_un_par_ligne_conserves(self):
        """
        L'inverse du test précédent : une liste dont chaque rôle est en gras ne
        doit pas être tronquée par le nouveau critère. Ces lignes s'enchaînent
        entre elles, jamais sur une réplique.
        """
        texte = (
            "**PERSONNAGES**\n"
            "**MARK**, 18 ans.\n"
            "**JAN**, 18 ans.\n"
            "**LÉA**, 18 ans.\n"
            "\n"
            "**JAN.** Tu es venu ?\n"
        )

        index = blocks.construire_index_structure(texte)
        entrees = [
            ligne.texte
            for ligne in blocks.classifier_document(texte, index)
            if ligne.type is blocks.TypeLigne.ENTREE_DISTRIBUTION
        ]

        self.assertEqual(len(entrees), 3)


# ============================================================
# 5. UN NOM AU MILIEU D'UNE RÉPLIQUE
# ============================================================


class TestNomAuMilieuDUneReplique(unittest.TestCase):
    """
    Un nom mis en valeur dans une réplique n'annonce pas une réplique.

    « **MARK** est parti sans rien dire. » était scindée en un nom centré gras
    suivi d'un fragment ouvrant sur une minuscule : un faux changement de
    locuteur, et la réplique coupée en deux dans le document final.

    Le discriminant est la suite. Un appel de personnage précède le début d'une
    phrase ; une mise en valeur se poursuit au milieu de l'une.
    """

    def test_nom_en_valeur_suivi_d_une_minuscule_n_est_pas_un_appel(self):
        for ligne in (
            "**MARK** est parti sans rien dire.",
            "**MARK** ne veut plus me parler.",
            "**MARK** arrive toujours en retard.",
        ):
            with self.subTest(ligne=ligne):
                self.assertIsNone(blocks.dedoubler_replique_en_ligne(ligne))

    def test_appel_veritable_conserve(self):
        for ligne, nom in (
            ("**JAN.** Bonjour.", "JAN."),
            ("**JAN** Bonjour.", "JAN"),
            ("**JAN.** « Je reviendrai », dit-il.", "JAN."),
            ("**JAN.** — Bonjour.", "JAN."),
            ("**JAN.** 7 heures déjà.", "JAN."),
            ("**JAN.** (Il entre.) Bonjour.", "JAN."),
        ):
            with self.subTest(ligne=ligne):
                resultat = blocks.dedoubler_replique_en_ligne(ligne)

                self.assertIsNotNone(resultat, "appel légitime rejeté")
                self.assertEqual(resultat.nom, nom)

    def test_ponctuation_d_appel_autorise_une_minuscule(self):
        """
        Le point final est la ponctuation d'appel de l'éditeur, qu'une mise en
        valeur ne porte jamais. Il faut donc qu'il dispense du contrôle de casse,
        sans quoi les répliques ouvrant sur une minuscule — courantes en vers
        libres — perdraient leur locuteur.
        """
        resultat = blocks.dedoubler_replique_en_ligne("**JAN.** bonjour, je suis là.")

        self.assertIsNotNone(resultat)
        self.assertEqual(resultat.nom, "JAN.")

    def test_didascalie_intercalee_autorise_une_minuscule(self):
        """Même raisonnement : une mise en valeur ne porte pas de didascalie."""
        resultat = blocks.dedoubler_replique_en_ligne(
            "**LES DIEUX, souriant.** bien sûr."
        )

        self.assertIsNotNone(resultat)
        self.assertEqual(resultat.nom, "LES DIEUX")
        self.assertEqual(resultat.didascalie, "souriant.")

    def test_nom_ailleurs_dans_la_replique_jamais_un_appel(self):
        """Les positions non initiales étaient déjà correctes : on le verrouille."""
        texte = (
            "**JAN.**\n"
            "Tu as vu **MARK** hier soir ?\n"
            "Je lui ai dit : MARK. Viens ici.\n"
            "*Il regarde **MARK** puis se tourne.*\n"
        )

        index = blocks.construire_index_structure(texte)
        types = {
            ligne.texte: ligne.type
            for ligne in blocks.classifier_document(texte, index)
        }

        self.assertIs(types["Tu as vu **MARK** hier soir ?"], blocks.TypeLigne.TEXTE)
        self.assertIs(
            types["Je lui ai dit : MARK. Viens ici."], blocks.TypeLigne.TEXTE
        )

    def test_replique_non_coupee_dans_le_document(self):
        """
        La propriété observable : la réplique reste un seul paragraphe, et aucun
        locuteur n'est inventé.
        """
        texte = "**JAN.**\nMARK est parti.\n**MARK** ne reviendra pas.\n"

        index = blocks.construire_index_structure(texte)
        personnages = [
            ligne.texte
            for ligne in blocks.classifier_document(texte, index)
            if ligne.type is blocks.TypeLigne.PERSONNAGE
        ]

        self.assertEqual(personnages, ["JAN."])


if __name__ == "__main__":
    unittest.main(verbosity=2)
