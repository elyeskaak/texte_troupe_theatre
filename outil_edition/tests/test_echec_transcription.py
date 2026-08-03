"""
Tests de la détection des **déclarations d'échec** de transcription.

Défaut observé sur une exécution réelle : le modèle a répondu « Erreur -
Impossible d'OCR cette page ». Cette phrase a été écrite dans `OCR.txt` comme du
texte de la pièce, avec le statut « terminé ». Trois conséquences, aucune
signalée :

- le message d'erreur entrait dans le texte, et l'étape 2 le mettait en forme ;
- la page n'était **jamais reprise**, son sidecar la déclarant terminée ;
- l'étape 3 comparait un `OCR.txt` corrompu, donc ne pouvait rien détecter.

Le contraire d'une page vide, qui est un signal de protocole légitime. La
distinction entre les deux est l'objet principal de ce fichier : la confondre
dans un sens fait perdre une page, dans l'autre fait payer indéfiniment la
reprise d'une page qui n'a rien à transcrire.
"""

from __future__ import annotations

import unittest

from theatre_editor import config
from theatre_editor.utils import blocks


class TestDeclarationEchec(unittest.TestCase):
    def test_le_message_observe_est_reconnu(self):
        """La formulation exacte relevée sur une exécution réelle."""
        self.assertTrue(
            blocks.est_declaration_echec("Erreur - Impossible d'OCR cette page")
        )

    def test_formulations_variees_reconnues(self):
        for texte in (
            "Erreur : impossible de lire cette page.",
            "Impossible d'OCR cette image.",
            "Je ne peux pas lire cette page, la qualité est insuffisante.",
            "Je n'arrive pas à transcrire ce document.",
            "Cette page est illisible.",
            "L'image est corrompue.",
            "Unable to process this image.",
            "Error: cannot read the page.",
            "**Erreur** — impossible de transcrire.",
        ):
            with self.subTest(texte=texte):
                self.assertTrue(blocks.est_declaration_echec(texte))

    def test_apostrophe_typographique_reconnue(self):
        """
        Les modèles alternent entre `'` et `’`. N'en reconnaître qu'une laisserait
        passer la moitié des cas.
        """
        for apostrophe in ("'", "’", "‘"):
            with self.subTest(apostrophe=apostrophe):
                self.assertTrue(
                    blocks.est_declaration_echec(f"Impossible d{apostrophe}OCR")
                )


class TestAucunFauxPositif(unittest.TestCase):
    """
    Le risque symétrique, et le plus coûteux : une réplique prise pour une
    déclaration d'échec ferait retenter la page à chaque exécution, indéfiniment.
    """

    def test_repliques_contenant_le_mot_erreur(self):
        for texte in (
            "**JAN.**\nC'est une erreur, je te dis.",
            "**LÉA.**\nTu fais erreur sur la personne.",
            "*Il comprend son erreur.*",
        ):
            with self.subTest(texte=texte):
                self.assertFalse(blocks.est_declaration_echec(texte))

    def test_replique_disant_l_impossible(self):
        """
        Le discriminant est **l'objet du verbe**, pas la préposition : c'est ce
        qui sépare « je ne peux pas lire cette page » de « je ne peux pas lire
        dans tes pensées ». Un critère purement lexical confondrait les deux.
        """
        for texte in (
            "Impossible de lui parler, il ne m'écoute plus.",
            "Je ne peux pas lire dans tes pensées.",
            "Je n'arrive pas à te suivre.",
            "Tu ne peux pas lire par-dessus mon épaule.",
        ):
            with self.subTest(texte=texte):
                self.assertFalse(blocks.est_declaration_echec(texte))

    def test_ambiguite_residuelle_tranchee_en_faveur_de_l_echec(self):
        """
        Une page dont **tout** le contenu déclare l'illisibilité reste ambiguë :
        aucun indice ne distingue le modèle qui renonce du personnage qui parle
        d'une lettre effacée. Elle est comptée comme un échec, délibérément.

        L'asymétrie des conséquences le justifie. Un échec est annoncé au
        récapitulatif, donc visible et corrigible à la main ; l'erreur inverse
        écrit le message dans le texte de la pièce en silence. Et une page réelle
        réduite à cette seule phrase est bien plus rare que la panne qu'elle
        imite.
        """
        self.assertTrue(blocks.est_declaration_echec("Cette page est illisible."))

    def test_page_longue_jamais_un_echec(self):
        """
        Une déclaration d'échec est courte. Au-delà du seuil, c'est du texte —
        même s'il commence par le mot « Erreur ».
        """
        texte = "Erreur. " + "Il marchait sans savoir où il allait. " * 30

        self.assertGreater(len(texte), config.MAX_LONGUEUR_DECLARATION_ECHEC)
        self.assertFalse(blocks.est_declaration_echec(texte))

    def test_page_de_theatre_ordinaire(self):
        texte = (
            "**ACTE I**\n\n*Une rue. Mark et Jan.*\n\n"
            "**MARK.**\nTu es venu.\n\n**JAN.**\nJe suis là.\n"
        )

        self.assertFalse(blocks.est_declaration_echec(texte))

    def test_texte_vide_n_est_pas_une_declaration(self):
        """L'absence de réponse est traitée ailleurs, comme un échec d'appel."""
        for texte in ("", "   ", "\n\n"):
            with self.subTest(texte=repr(texte)):
                self.assertFalse(blocks.est_declaration_echec(texte))


class TestDistinctionAvecPageVide(unittest.TestCase):
    """
    Les deux déclarations doivent rester discernables : l'une est un signal
    légitime qui vaut une page conservée vide, l'autre un échec à retenter.
    Les confondre reviendrait à perdre silencieusement une page de texte, ou à
    repayer indéfiniment une page qui n'a rien à transcrire.
    """

    def test_page_vide_n_est_pas_un_echec(self):
        for texte in (
            config.MENTION_PAGE_SANS_TEXTE,
            "Cette page est vide.",
            "Page blanche.",
        ):
            with self.subTest(texte=texte):
                self.assertTrue(blocks.est_declaration_page_vide(texte))
                self.assertFalse(blocks.est_declaration_echec(texte))

    def test_echec_n_est_pas_une_page_vide(self):
        for texte in (
            "Erreur - Impossible d'OCR cette page",
            "Je ne peux pas lire cette page.",
        ):
            with self.subTest(texte=texte):
                self.assertTrue(blocks.est_declaration_echec(texte))
                self.assertFalse(blocks.est_declaration_page_vide(texte))


class TestMotifsBienFormes(unittest.TestCase):
    def test_tous_les_motifs_compilent(self):
        """
        Un motif mal formé ne lèverait qu'au premier appel, en pleine exécution
        d'OCR — après plusieurs dizaines de pages payées.
        """
        import re

        for motif in config.MOTIFS_ECHEC_TRANSCRIPTION:
            with self.subTest(motif=motif):
                re.compile(motif, re.IGNORECASE)

    def test_seuils_coherents(self):
        """
        Une déclaration d'échec est plus verbeuse qu'une déclaration de page
        vide : son seuil doit être le plus large des deux.
        """
        self.assertGreaterEqual(
            config.MAX_LONGUEUR_DECLARATION_ECHEC,
            config.MAX_LONGUEUR_DECLARATION_VIDE,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
