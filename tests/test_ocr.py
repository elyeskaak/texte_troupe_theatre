"""
Tests de `theatre_editor.ocr`.

Ni PyMuPDF ni `openai` ne sont nécessaires : le document PDF et l'appel API
sont remplacés par des doublures. L'étape entière — reprise, dégradation de
résolution, assemblage, tolérance aux pages en échec — est donc vérifiable
hors ligne.

Ce qui est réellement mis à l'épreuve ici, c'est l'invariant de reprise : une
page terminée ne doit **jamais** provoquer un second appel payant, et une page
interrompue ne doit **jamais** être tenue pour terminée.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from theatre_editor import config, ocr
from theatre_editor.utils import api, io


# ============================================================
# DOUBLURES
# ============================================================


class PixmapFactice:
    def __init__(self, octets: bytes):
        self._octets = octets

    def tobytes(self, _format: str) -> bytes:
        return self._octets


class PageFactice:
    """
    Page dont le poids de l'image dépend du DPI.

    `poids_par_dpi` permet de simuler une page trop lourde à pleine résolution,
    afin d'éprouver la boucle de dégradation.
    """

    def __init__(self, poids_par_dpi: int = 1000):
        self.poids_par_dpi = poids_par_dpi
        self.dpi_demandes: list[int] = []

    def get_pixmap(self, dpi: int) -> PixmapFactice:
        self.dpi_demandes.append(dpi)
        return PixmapFactice(b"\x89PNG" + b"x" * (dpi * self.poids_par_dpi))


class DocumentFactice:
    def __init__(self, nombre_pages: int, poids_par_dpi: int = 1000):
        self.page_count = nombre_pages
        self.pages = [PageFactice(poids_par_dpi) for _ in range(nombre_pages)]
        self.ferme = False

    def load_page(self, index: int) -> PageFactice:
        return self.pages[index]

    def close(self) -> None:
        self.ferme = True


def resultat_api(texte: str = "Texte de la page.") -> api.ResultatAppel:
    return api.ResultatAppel(
        texte=texte,
        modele=config.MODEL_OCR,
        response_id="resp_test",
        tentative=1,
        duree_secondes=1.5,
        tokens_entree=100,
        tokens_sortie=50,
    )


class BaseOcr(unittest.TestCase):
    """Socle : dossier temporaire, console muette, API bouchonnée."""

    NOMBRE_PAGES = 3

    def setUp(self):
        self._verbosite = config.VERBOSITE
        config.VERBOSITE = 0

        self._dossier = tempfile.TemporaryDirectory()
        self.base = Path(self._dossier.name)
        self.pdf = self.base / "Le Malentendu.pdf"
        self.pdf.write_bytes(b"%PDF-1.7 factice")

        self.chemins = io.resoudre_chemins("Le Malentendu", self.base)
        self.document = DocumentFactice(self.NOMBRE_PAGES)

        self.patchs = [
            mock.patch.object(ocr, "ouvrir_pdf", return_value=self.document),
            mock.patch.object(api, "patienter"),
        ]
        for patch in self.patchs:
            patch.start()

    def tearDown(self):
        for patch in self.patchs:
            patch.stop()
        self._dossier.cleanup()
        config.VERBOSITE = self._verbosite

    def executer(self, reponses=None, effet=None):
        """
        Lance l'étape avec un `appeler_modele` bouchonné.

        Args:
            reponses: liste de textes à rendre, un par appel.
            effet: fonction `**kwargs -> ResultatAppel` pour les cas complexes.
        """
        if effet is None:
            sequence = list(reponses or ["Texte de la page."] * 20)

            def effet(**_kwargs):
                return resultat_api(sequence.pop(0))

        with mock.patch.object(
            api, "appeler_modele", side_effect=effet
        ) as appel:
            resultats = ocr.executer(self.base)

        return resultats, appel


# ============================================================
# 1. RASTERISATION
# ============================================================


class TestRasterisation(unittest.TestCase):
    def test_dpi_transmis(self):
        page = PageFactice()

        ocr.rasteriser_page(page, 200)

        self.assertEqual(page.dpi_demandes, [200])

    def test_reduire_dpi_respecte_le_plancher(self):
        self.assertEqual(ocr.reduire_dpi(config.DPI_MINIMAL), config.DPI_MINIMAL)

    def test_reduire_dpi_decroit(self):
        self.assertLess(ocr.reduire_dpi(400), 400)

    def test_image_legere_conserve_le_dpi_nominal(self):
        image, dpi, avertissements = ocr.rasteriser_avec_degradation(PageFactice(1))

        self.assertEqual(dpi, config.DPI_RASTERISATION)
        self.assertEqual(avertissements, [])
        self.assertTrue(image.startswith(b"\x89PNG"))

    def _avec_seuil(self, seuil_mo: float):
        """
        Abaisse temporairement la limite de taille d'image.

        On agit sur le seuil plutôt que sur le poids de la page : fabriquer une
        image réellement supérieure à 18 Mo demanderait d'allouer plusieurs
        gigaoctets au fil de la dégradation, ce qui rendrait le test lent et
        susceptible d'épuiser la mémoire d'une machine modeste.
        """
        patch = mock.patch.object(config, "TAILLE_MAX_IMAGE_MO", seuil_mo)
        patch.start()
        self.addCleanup(patch.stop)

    def test_image_lourde_declenche_la_degradation(self):
        """
        Une page trop lourde doit être dégradée plutôt que refusée : une
        transcription à 110 dpi vaut mieux qu'une page absente.
        """
        page = PageFactice(poids_par_dpi=1000)

        # 200 dpi → 0,19 Mo ; 150 dpi → 0,14 Mo. Le seuil ne laisse donc
        # passer que la résolution dégradée.
        self._avec_seuil(0.16)

        _, dpi, avertissements = ocr.rasteriser_avec_degradation(page)

        self.assertLess(dpi, config.DPI_RASTERISATION)
        self.assertTrue(any("résolution réduite" in a for a in avertissements))

    def test_degradation_termine_au_plancher(self):
        """Garde-fou contre une boucle infinie sur une page démesurée."""
        page = PageFactice(poids_par_dpi=1000)

        # Seuil inatteignable, même au plancher de résolution.
        self._avec_seuil(0.0001)

        _, dpi, avertissements = ocr.rasteriser_avec_degradation(page)

        self.assertEqual(dpi, config.DPI_MINIMAL)
        self.assertTrue(any("plancher atteint" in a for a in avertissements))


# ============================================================
# 2. ASSEMBLAGE
# ============================================================


class TestAssemblage(BaseOcr):
    def test_marqueurs_ajoutes_par_le_code(self):
        """
        Les marqueurs [PAGE X] viennent du code, jamais du modèle : c'est ce
        qui rend leur format déterministe pour l'étape 2.
        """
        self.executer(["Page une.", "Page deux.", "Page trois."])

        contenu = io.lire_texte(self.chemins.ocr)

        for numero in (1, 2, 3):
            self.assertIn(config.MARQUEUR_PAGE.format(numero=numero), contenu)

    def test_separateur_entre_les_pages(self):
        self.executer()

        contenu = io.lire_texte(self.chemins.ocr)

        self.assertEqual(contenu.count("<<<PAGE_BREAK>>>"), self.NOMBRE_PAGES - 1)

    def test_sortie_relisible_par_le_decoupeur_de_l_etape_2(self):
        """
        Contrat entre les étapes : ce que l'étape 1 écrit, l'étape 2 doit savoir
        redécouper, et retrouver exactement le même nombre de pages.
        """
        from theatre_editor.utils import blocks

        self.executer(["Page une.", "Page deux.", "Page trois."])

        pages = blocks.decouper_en_pages(io.lire_texte(self.chemins.ocr))

        self.assertEqual(len(pages), self.NOMBRE_PAGES)
        self.assertIn("Page deux.", pages[1])

    def test_page_en_echec_laisse_un_trou_visible(self):
        """
        Un trou silencieux serait indétectable. Le marqueur d'échec permet de
        le chercher, de le compter et de le reprendre.
        """

        def effet(**kwargs):
            if "page 2" in kwargs.get("libelle", ""):
                raise api.EchecAppelAPI("panne simulée")
            return resultat_api()

        self.executer(effet=effet)

        contenu = io.lire_texte(self.chemins.ocr)

        self.assertIn(config.MARQUEUR_ECHEC_PAGE.format(numero=2), contenu)

    def test_assemblage_refait_a_chaque_execution(self):
        """
        L'assemblage ne « complète » jamais un fichier existant : il le
        reconstruit depuis le cache, seule source de vérité.
        """
        self.executer()
        self.chemins.ocr.write_text("contenu obsolète", encoding="utf-8")

        self.executer()

        self.assertNotIn("obsolète", io.lire_texte(self.chemins.ocr))


# ============================================================
# 3. REPRISE APRÈS INTERRUPTION
# ============================================================


class TestReprise(BaseOcr):
    def test_premiere_execution_appelle_chaque_page(self):
        _, appel = self.executer()

        self.assertEqual(appel.call_count, self.NOMBRE_PAGES)

    def test_seconde_execution_n_appelle_plus_rien(self):
        """
        Le cœur de l'exigence : ne jamais recalculer une étape terminée. Un
        second appel serait un appel payé pour rien.
        """
        self.executer()
        resultats, appel = self.executer()

        self.assertEqual(appel.call_count, 0)
        self.assertEqual(resultats[0].pages_sautees, self.NOMBRE_PAGES)

    def test_reprise_ne_refait_que_la_page_manquante(self):
        def effet(**kwargs):
            if "page 2" in kwargs.get("libelle", ""):
                raise api.EchecAppelAPI("panne simulée")
            return resultat_api()

        self.executer(effet=effet)

        # Second passage, sans panne : seule la page 2 doit être rappelée.
        _, appel = self.executer()

        self.assertEqual(appel.call_count, 1)
        libelles = [c.kwargs["libelle"] for c in appel.call_args_list]
        self.assertEqual(libelles, ["page 2"])

    def test_txt_orphelin_est_reecrit(self):
        """
        Coupure entre l'écriture du .txt et celle du sidecar. Le .txt existe
        mais n'est pas validé : la page doit être refaite.
        """
        io.ecrire_texte_atomique(self.chemins.page_txt(1), "transcription partielle")

        _, appel = self.executer()

        self.assertEqual(appel.call_count, self.NOMBRE_PAGES)
        self.assertNotIn("partielle", io.lire_texte(self.chemins.page_txt(1)))

    def test_sidecar_ecrit_apres_le_contenu(self):
        """
        L'ordre porte tout l'invariant. On vérifie qu'aucun sidecar validé ne
        peut exister sans son contenu.
        """
        self.executer()

        for numero in range(1, self.NOMBRE_PAGES + 1):
            with self.subTest(page=numero):
                if io.unite_terminee(self.chemins.page_json(numero)):
                    self.assertTrue(self.chemins.page_txt(numero).exists())

    def test_page_suspecte_est_reprise(self):
        """Un statut « suspect » ne vaut pas « terminé »."""
        # Le modèle ajoute une mise en forme interdite : la page est suspecte.
        self.executer(["**JAN.**", "Texte normal.", "Texte normal."])

        resultats, _ = self.executer()

        self.assertEqual(resultats[0].pages_sautees, self.NOMBRE_PAGES - 1)


# ============================================================
# 4. CONTRÔLES DE CONTENU
# ============================================================


class TestControlesContenu(BaseOcr):
    NOMBRE_PAGES = 1

    def test_page_blanche_declaree_est_acceptee(self):
        resultats, _ = self.executer([config.MENTION_PAGE_SANS_TEXTE])

        self.assertEqual(resultats[0].pages_traitees, 1)
        self.assertEqual(resultats[0].pages_suspectes, 0)
        # Le marqueur est un signal de protocole, pas du contenu.
        self.assertEqual(io.lire_texte(self.chemins.page_txt(1)).strip(), "")

    def test_sortie_vide_non_declaree_est_suspecte(self):
        """
        Sans la mention de page blanche, une sortie vide est indiscernable d'un
        problème : la page doit être reprise.
        """
        resultats, _ = self.executer(["   "])

        self.assertEqual(resultats[0].pages_suspectes, 1)

    def test_mise_en_forme_ajoutee_est_suspecte(self):
        """
        L'OCR doit rendre du texte nu : la convention typographique appartient
        exclusivement à l'étape 2.
        """
        resultats, _ = self.executer(["**JAN.**\nMort ?"])

        self.assertEqual(resultats[0].pages_suspectes, 1)

    def test_marque_illisible_est_acceptee(self):
        """Seule astérisque autorisée en sortie d'OCR."""
        resultats, _ = self.executer([f"Début {config.MARQUE_ILLISIBLE} fin."])

        self.assertEqual(resultats[0].pages_suspectes, 0)

    def test_marqueur_de_page_ajoute_par_le_modele_est_suspect(self):
        resultats, _ = self.executer(["[PAGE 1]\nTexte de la page."])

        self.assertEqual(resultats[0].pages_suspectes, 1)

    def test_enveloppe_de_code_retiree(self):
        resultats, _ = self.executer(["```\nTexte de la page.\n```"])

        self.assertEqual(io.lire_texte(self.chemins.page_txt(1)).strip(), "Texte de la page.")
        self.assertEqual(resultats[0].pages_suspectes, 0)


# ============================================================
# 5. TOLÉRANCE AUX PANNES
# ============================================================


class TestTolerancePannes(BaseOcr):
    def test_une_page_en_echec_n_interrompt_pas_le_livre(self):
        """
        Perdre 288 pages parce que la page 96 est illisible serait absurde.
        """

        def effet(**kwargs):
            if "page 1" in kwargs.get("libelle", ""):
                raise api.EchecAppelAPI("panne simulée")
            return resultat_api()

        resultats, appel = self.executer(effet=effet)

        self.assertEqual(appel.call_count, self.NOMBRE_PAGES)
        self.assertEqual(resultats[0].pages_echouees, 1)
        self.assertEqual(resultats[0].numeros_echoues, [1])
        self.assertTrue(self.chemins.ocr.exists())

    def test_page_en_echec_n_ecrit_pas_de_txt(self):
        """
        Un .txt vide pourrait être pris pour une page blanche légitime : mieux
        vaut n'en écrire aucun.
        """

        def effet(**_kwargs):
            raise api.EchecAppelAPI("panne simulée")

        self.executer(effet=effet)

        self.assertFalse(self.chemins.page_txt(1).exists())
        self.assertFalse(io.unite_terminee(self.chemins.page_json(1)))

    def test_pdf_illisible_ne_bloque_pas_l_etape(self):
        with mock.patch.object(
            ocr, "ouvrir_pdf", side_effect=RuntimeError("PDF corrompu")
        ):
            resultats = ocr.executer(self.base)

        self.assertEqual(resultats[0].statut, config.STATUT_ECHEC)
        self.assertIn("corrompu", resultats[0].erreur)

    def test_document_ferme_meme_en_cas_d_erreur(self):
        def effet(**_kwargs):
            raise api.EchecAppelAPI("panne simulée")

        self.executer(effet=effet)

        self.assertTrue(self.document.ferme)

    def test_dossier_sans_pdf(self):
        with tempfile.TemporaryDirectory() as vide:
            self.assertEqual(ocr.executer(Path(vide)), [])


# ============================================================
# 6. JOURNAL ET SIDECARS
# ============================================================


class TestJournalEtSidecars(BaseOcr):
    NOMBRE_PAGES = 2

    def test_journal_ecrit_avec_les_champs_attendus(self):
        self.executer()

        journal = io.lire_sidecar(self.base / "journal_ocr.json")

        self.assertEqual(journal["etape"], "ocr")
        self.assertEqual(len(journal["appels"]), self.NOMBRE_PAGES)

        appel = journal["appels"][0]
        for champ in (
            "date",
            "modele",
            "response_id",
            "duree_secondes",
            "longueur_entree",
            "longueur_sortie",
            "avertissements",
        ):
            with self.subTest(champ=champ):
                self.assertIn(champ, appel)

    def test_bilan_du_livre_journalise(self):
        self.executer()

        journal = io.lire_sidecar(self.base / "journal_ocr.json")
        bilan = journal["livres"]["Le Malentendu"]

        self.assertEqual(bilan["pages_totales"], self.NOMBRE_PAGES)
        self.assertEqual(bilan["statut"], config.STATUT_TERMINE)

    def test_sidecar_de_page_documente_le_dpi_et_la_taille(self):
        self.executer()

        sidecar = io.lire_sidecar(self.chemins.page_json(1))

        self.assertEqual(sidecar["statut"], config.STATUT_TERMINE)
        self.assertEqual(sidecar["unite"], "page")
        self.assertEqual(sidecar["dpi"], config.DPI_RASTERISATION)
        # L'entrée est une image : la longueur est en octets.
        self.assertGreater(sidecar["longueur_entree"], 0)

    def test_journal_survit_a_une_seconde_execution(self):
        self.executer()
        self.executer()

        journal = io.lire_sidecar(self.base / "journal_ocr.json")

        # Aucun appel supplémentaire, mais les précédents sont conservés.
        self.assertEqual(len(journal["appels"]), self.NOMBRE_PAGES)


# ============================================================
# 7. PARAMÈTRES DE L'APPEL
# ============================================================


class TestParametresAppel(BaseOcr):
    NOMBRE_PAGES = 1

    def test_appel_en_mode_vision_avec_le_bon_modele(self):
        _, appel = self.executer()

        kwargs = appel.call_args.kwargs

        self.assertEqual(kwargs["modele"], config.MODEL_OCR)
        self.assertTrue(kwargs["image_png"].startswith(b"\x89PNG"))
        self.assertIn("Transcris", kwargs["message"])

    def test_prompt_ocr_transmis(self):
        _, appel = self.executer()

        instructions = appel.call_args.kwargs["instructions"]

        self.assertIn("Tu transcris. Tu ne corriges pas.", instructions)


if __name__ == "__main__":
    unittest.main(verbosity=2)
