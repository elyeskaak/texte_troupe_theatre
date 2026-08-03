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
from theatre_editor.utils import api, blocks, io


# ============================================================
# DOUBLURES
# ============================================================


class PixmapFactice:
    def __init__(self, octets: bytes):
        self._octets = octets

    def tobytes(self, _format: str) -> bytes:
        return self._octets


# Couche texte de bonne qualité : français accentué, longueur suffisante.
COUCHE_TEXTE_BONNE = (
    "ACTE PREMIER\n\n"
    "Une auberge à la tombée du soir. La pièce est basse, mal éclairée.\n\n"
    "JAN\n"
    "Nous y sommes enfin arrivés, après tant d'années d'absence. "
    "Rien n'a changé, et pourtant je ne reconnais rien.\n\n"
    "MARIA\n"
    "Je t'attendais depuis une heure déjà. Tu m'avais promis d'être là "
    "avant la nuit tombée, et voilà que tu arrives à cette heure.\n\n"
    "JAN\n"
    "Le voyage était long. Nous avons dû nous arrêter à deux reprises.\n"
)


class PageFactice:
    """
    Page dont le poids de l'image dépend du DPI.

    `poids_par_dpi` permet de simuler une page trop lourde à pleine résolution,
    afin d'éprouver la boucle de dégradation. `couche_texte` simule un PDF déjà
    passé à l'OCR ; la chaîne vide simule un scan pur.
    """

    def __init__(self, poids_par_dpi: int = 1000, couche_texte: str = ""):
        self.poids_par_dpi = poids_par_dpi
        self.couche_texte = couche_texte
        self.dpi_demandes: list[int] = []
        self.extractions = 0

    def get_pixmap(self, dpi: int) -> PixmapFactice:
        self.dpi_demandes.append(dpi)
        return PixmapFactice(b"\x89PNG" + b"x" * (dpi * self.poids_par_dpi))

    def get_text(self, _format: str = "text", sort: bool = False) -> str:
        self.extractions += 1
        return self.couche_texte


class DocumentFactice:
    def __init__(
        self,
        nombre_pages: int,
        poids_par_dpi: int = 1000,
        couches_texte: list[str] | None = None,
    ):
        self.page_count = nombre_pages
        self.pages = [
            PageFactice(
                poids_par_dpi,
                couches_texte[i] if couches_texte else "",
            )
            for i in range(nombre_pages)
        ]
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

    def test_reprises_d_une_page_suspecte_sont_bornees(self):
        """
        Garde-fou contre la facturation sans fin.

        Un avertissement reproductible — ici le modèle ajoute obstinément de la
        mise en forme — provoquerait sinon une reprise à chaque exécution, et
        une facturation à chaque fois, sans que rien ne puisse s'améliorer.
        """
        obstine = lambda **_kw: resultat_api("**JAN.**\nMort ?")

        appels = []

        for _ in range(config.MAX_REPRISES_SUSPECTES + 3):
            _, appel = self.executer(effet=obstine)
            appels.append(appel.call_count)

        # Premier passage plus MAX_REPRISES_SUSPECTES reprises, puis plus rien.
        self.assertEqual(appels[0], self.NOMBRE_PAGES)
        self.assertEqual(appels[config.MAX_REPRISES_SUSPECTES], 0)
        self.assertEqual(appels[-1], 0)

    def test_compteur_de_reprises_consigne(self):
        """Le compteur doit être lisible dans le sidecar, pour diagnostic."""
        obstine = lambda **_kw: resultat_api("**JAN.**\nMort ?")

        self.executer(effet=obstine)

        self.assertEqual(io.reprises_effectuees(self.chemins.page_json(1)), 1)

        self.executer(effet=obstine)

        self.assertEqual(io.reprises_effectuees(self.chemins.page_json(1)), 2)

    def test_avertissements_conserves_apres_acceptation(self):
        """
        Une page finalement acceptée doit garder trace de son problème : c'est
        la seule façon de le retrouver après coup.
        """
        obstine = lambda **_kw: resultat_api("**JAN.**\nMort ?")

        for _ in range(config.MAX_REPRISES_SUSPECTES + 1):
            self.executer(effet=obstine)

        sidecar = io.lire_sidecar(self.chemins.page_json(1))

        self.assertEqual(sidecar["statut"], config.STATUT_SUSPECT)
        self.assertTrue(sidecar["avertissements"])


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

    def test_asterisque_imprimee_n_est_pas_signalee(self):
        """
        Régression, et fuite d'argent.

        Signaler la moindre astérisque produisait un faux positif sur toute page
        dont le texte imprimé en contient une — séparateur `*  *  *`, appel de
        note. La page était marquée suspecte, donc retranscrite et **repayée à
        chaque exécution**, puisqu'une astérisque imprimée ne disparaîtra jamais.
        """
        for contenu in (
            "JAN\nBonjour.\n\n*  *  *\n\nMARIA\nBonsoir.",
            "Une note en bas de page*, puis la suite du texte imprimé.",
            "***",
        ):
            with self.subTest(contenu=contenu[:24]):
                self.assertEqual(blocks.verifier_page_ocr(contenu), [])

    def test_replique_avec_je_ne_peux_pas_n_est_pas_signalee(self):
        """
        Régression, et perte de page. Le motif de refus « je ne peux pas » se
        déclenchait sur une réplique banale (« WANG. Je ne peux pas te le
        dire »), marquant la page suspecte au point de la faire disparaître du
        fichier assemblé. Un vrai refus de transcription reste capté par
        `est_declaration_echec` : l'objet du verbe doit être la page (§9.7).
        """
        for contenu in (
            "WANG. Je ne peux pas te le dire maintenant.",
            "SHEN TÉ. Je ne peux pas refuser.",
        ):
            with self.subTest(contenu=contenu[:24]):
                self.assertEqual(blocks.verifier_page_ocr(contenu), [])

    def test_emphase_markdown_reste_signalee(self):
        """
        Contrepartie : la vraie mise en forme ajoutée doit toujours être vue,
        sinon le contrôle n'aurait plus d'objet.
        """
        for contenu in ("**JAN.**\nMort ?", "Texte\n*Pause.*\nSuite"):
            with self.subTest(contenu=contenu[:24]):
                self.assertTrue(blocks.verifier_page_ocr(contenu))

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

        journal = io.lire_sidecar(io.dossier_temporaire(self.base) / "journal_ocr.json")

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

        journal = io.lire_sidecar(io.dossier_temporaire(self.base) / "journal_ocr.json")
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

        journal = io.lire_sidecar(io.dossier_temporaire(self.base) / "journal_ocr.json")

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


# ============================================================
# 8. COUCHE TEXTE DÉJÀ PRÉSENTE DANS LE PDF
# ============================================================


class TestEvaluationCoucheTexte(unittest.TestCase):
    """
    Le jugement porté sur une couche texte, testé sans PDF.

    Le sens de la prudence est l'enjeu : accepter une mauvaise couche texte
    dégrade tout le livre, puisque l'étape 2 ne réécrit pas l'auteur. Rasteriser
    à tort ne coûte que des jetons. Les contrôles doivent donc pencher vers le
    refus.
    """

    def test_couche_texte_de_qualite_acceptee(self):
        self.assertEqual(blocks.evaluer_couche_texte(COUCHE_TEXTE_BONNE), [])

    def test_absence_de_couche_texte(self):
        for vide in ("", "   \n\n  "):
            with self.subTest(valeur=repr(vide)):
                self.assertEqual(
                    blocks.evaluer_couche_texte(vide), ["aucune couche texte"]
                )

    def test_couche_texte_trop_courte_refusee(self):
        raisons = blocks.evaluer_couche_texte("JAN\nBonjour.")

        self.assertTrue(any("trop courte" in r for r in raisons))

    def test_accents_depouilles_refuses(self):
        """
        Signal le plus fiable d'un OCR ancien : sur une page de français, une
        absence totale d'accents ne s'explique pas autrement.
        """
        raisons = blocks.evaluer_couche_texte(
            blocks.sans_accents(COUCHE_TEXTE_BONNE)
        )

        self.assertTrue(any("accent" in r for r in raisons))

    def test_caracteres_de_remplacement_refuses(self):
        abime = COUCHE_TEXTE_BONNE.replace("e", "�")

        self.assertTrue(blocks.evaluer_couche_texte(abime))

    def test_trop_peu_de_lettres_refuse(self):
        raisons = blocks.evaluer_couche_texte("### $$$ %%% &&& " * 40)

        self.assertTrue(any("lettres" in r for r in raisons))

    def test_seuils_lus_dans_la_configuration(self):
        court = "Jérôme entre. " * 5

        with mock.patch.object(config, "MIN_CARACTERES_COUCHE_TEXTE", 10_000):
            self.assertTrue(blocks.evaluer_couche_texte(court))

        with mock.patch.object(config, "MIN_CARACTERES_COUCHE_TEXTE", 10):
            self.assertEqual(blocks.evaluer_couche_texte(court), [])


class TestNormalisationCoucheTexte(unittest.TestCase):
    def test_ligatures_defaites(self):
        """Fréquentes dans une couche texte, elles casseraient les comparaisons."""
        resultat = blocks.normaliser_couche_texte("La ﬁn de l'aﬀaire, enﬂammé.")

        self.assertEqual(resultat, "La fin de l'affaire, enflammé.")

    def test_espaces_de_fin_de_ligne_retires(self):
        self.assertEqual(
            blocks.normaliser_couche_texte("JAN   \nBonjour.  "), "JAN\nBonjour."
        )

    def test_lignes_vides_excessives_ramenees_a_deux(self):
        self.assertEqual(
            blocks.normaliser_couche_texte("A\n\n\n\n\nB"), "A\n\nB"
        )

    def test_ponctuation_de_l_auteur_preservee(self):
        """
        On ne normalise pas en NFKC : cela transformerait les points de
        suspension en trois points et altérerait la ponctuation.
        """
        texte = "Je ne sais pas… peut-être « oui » ?"

        self.assertEqual(blocks.normaliser_couche_texte(texte), texte)

    def test_accents_preserves(self):
        texte = "Où êtes-vous allé, çà et là ?"

        self.assertEqual(blocks.normaliser_couche_texte(texte), texte)


class TestStrategieCoucheTexte(unittest.TestCase):
    def test_auto_accepte_une_bonne_couche(self):
        with mock.patch.object(config, "STRATEGIE_COUCHE_TEXTE", "auto"):
            self.assertTrue(ocr.couche_texte_retenue(COUCHE_TEXTE_BONNE, []))

    def test_auto_refuse_une_couche_douteuse(self):
        with mock.patch.object(config, "STRATEGIE_COUCHE_TEXTE", "auto"):
            self.assertFalse(
                ocr.couche_texte_retenue(COUCHE_TEXTE_BONNE, ["accents dépouillés"])
            )

    def test_jamais_ignore_meme_une_bonne_couche(self):
        with mock.patch.object(config, "STRATEGIE_COUCHE_TEXTE", "jamais"):
            self.assertFalse(ocr.couche_texte_retenue(COUCHE_TEXTE_BONNE, []))

    def test_toujours_accepte_malgre_les_reserves(self):
        with mock.patch.object(config, "STRATEGIE_COUCHE_TEXTE", "toujours"):
            self.assertTrue(
                ocr.couche_texte_retenue(COUCHE_TEXTE_BONNE, ["accents dépouillés"])
            )

    def test_toujours_ne_peut_rien_inventer(self):
        """Même en mode « toujours », une page sans texte passe par la vision."""
        with mock.patch.object(config, "STRATEGIE_COUCHE_TEXTE", "toujours"):
            self.assertFalse(ocr.couche_texte_retenue("", ["aucune couche texte"]))

    def test_strategie_invalide_leve_une_erreur_explicite(self):
        with mock.patch.object(config, "STRATEGIE_COUCHE_TEXTE", "peut-etre"):
            with self.assertRaises(ValueError) as contexte:
                ocr.couche_texte_retenue(COUCHE_TEXTE_BONNE, [])

        self.assertIn("STRATEGIE_COUCHE_TEXTE", str(contexte.exception))


class TestReutilisationCoucheTexte(BaseOcr):
    """L'intégration : une couche texte exploitable ne coûte aucun appel."""

    NOMBRE_PAGES = 3

    def _document_avec_couches(self, couches: list[str]) -> None:
        self.document = DocumentFactice(self.NOMBRE_PAGES, couches_texte=couches)
        mock.patch.object(ocr, "ouvrir_pdf", return_value=self.document).start()

    def test_livre_entierement_deja_ocrise_ne_coute_rien(self):
        """Le cas qui motive la fonctionnalité : ne pas payer deux fois."""
        self._document_avec_couches([COUCHE_TEXTE_BONNE] * self.NOMBRE_PAGES)

        resultats, appel = self.executer()

        self.assertEqual(appel.call_count, 0)
        self.assertEqual(resultats[0].pages_couche_texte, self.NOMBRE_PAGES)
        self.assertEqual(resultats[0].statut, config.STATUT_TERMINE)
        self.assertTrue(self.chemins.ocr.exists())

    def test_texte_de_la_couche_ecrit_tel_quel(self):
        self._document_avec_couches([COUCHE_TEXTE_BONNE] * self.NOMBRE_PAGES)

        self.executer()

        self.assertIn("Nous y sommes enfin arrivés", io.lire_texte(self.chemins.ocr))

    def test_provenance_consignee_dans_le_sidecar(self):
        """
        Indispensable : si le résultat final surprend, il faut pouvoir savoir
        d'où vient chaque page.
        """
        self._document_avec_couches([COUCHE_TEXTE_BONNE] * self.NOMBRE_PAGES)

        self.executer()

        sidecar = io.lire_sidecar(self.chemins.page_json(1))

        self.assertEqual(sidecar["source"], ocr.SOURCE_COUCHE_TEXTE)
        self.assertIsNone(sidecar["modele"])
        self.assertEqual(sidecar["statut"], config.STATUT_TERMINE)

    def test_provenance_vision_consignee_aussi(self):
        resultats, _ = self.executer()

        self.assertEqual(
            io.lire_sidecar(self.chemins.page_json(1))["source"], ocr.SOURCE_VISION
        )

    def test_livre_hybride(self):
        """
        Cas réaliste : un PDF dont seule une partie des pages porte une couche
        texte exploitable.
        """
        self._document_avec_couches([COUCHE_TEXTE_BONNE, "", COUCHE_TEXTE_BONNE])

        resultats, appel = self.executer()

        self.assertEqual(appel.call_count, 1)
        self.assertEqual([c.kwargs["libelle"] for c in appel.call_args_list], ["page 2"])
        self.assertEqual(resultats[0].pages_couche_texte, 2)
        self.assertEqual(resultats[0].pages_traitees, 1)

    def test_couche_texte_douteuse_renvoyee_a_la_vision(self):
        """Accents dépouillés : on préfère payer plutôt que dégrader le livre."""
        depouillee = blocks.sans_accents(COUCHE_TEXTE_BONNE)
        self._document_avec_couches([depouillee] * self.NOMBRE_PAGES)

        resultats, appel = self.executer()

        self.assertEqual(appel.call_count, self.NOMBRE_PAGES)
        self.assertEqual(resultats[0].pages_couche_texte, 0)

    def test_strategie_jamais_force_la_vision(self):
        self._document_avec_couches([COUCHE_TEXTE_BONNE] * self.NOMBRE_PAGES)

        with mock.patch.object(config, "STRATEGIE_COUCHE_TEXTE", "jamais"):
            resultats, appel = self.executer()

        self.assertEqual(appel.call_count, self.NOMBRE_PAGES)
        self.assertEqual(resultats[0].pages_couche_texte, 0)

    def test_pages_gratuites_journalisees_sans_jetons(self):
        self._document_avec_couches([COUCHE_TEXTE_BONNE] * self.NOMBRE_PAGES)

        self.executer()

        journal = io.lire_sidecar(io.dossier_temporaire(self.base) / "journal_ocr.json")
        appels = journal["appels"]

        self.assertEqual(len(appels), self.NOMBRE_PAGES)
        for entree in appels:
            with self.subTest(numero=entree["numero"]):
                self.assertEqual(entree["source"], ocr.SOURCE_COUCHE_TEXTE)
                self.assertEqual(entree["tokens_entree"], 0)
                self.assertEqual(entree["tokens_sortie"], 0)

    def test_reprise_saute_les_pages_issues_de_la_couche(self):
        self._document_avec_couches([COUCHE_TEXTE_BONNE] * self.NOMBRE_PAGES)

        self.executer()
        resultats, appel = self.executer()

        self.assertEqual(appel.call_count, 0)
        self.assertEqual(resultats[0].pages_sautees, self.NOMBRE_PAGES)

    def test_sortie_relisible_par_l_etape_2(self):
        """Le contrat inter-étapes vaut aussi pour ce chemin."""
        self._document_avec_couches([COUCHE_TEXTE_BONNE] * self.NOMBRE_PAGES)

        self.executer()

        pages = blocks.decouper_en_pages(io.lire_texte(self.chemins.ocr))

        self.assertEqual(len(pages), self.NOMBRE_PAGES)


class TestDiagnostic(BaseOcr):
    """Le diagnostic doit être entièrement gratuit."""

    NOMBRE_PAGES = 4

    def _diagnostiquer(self, couches: list[str]):
        document = DocumentFactice(self.NOMBRE_PAGES, couches_texte=couches)

        with mock.patch.object(ocr, "ouvrir_pdf", return_value=document), \
             mock.patch.object(api, "appeler_modele") as appel:
            diagnostics = ocr.diagnostiquer_couches_texte(self.base)

        return diagnostics, appel

    def test_aucun_appel_api(self):
        _, appel = self._diagnostiquer([COUCHE_TEXTE_BONNE] * self.NOMBRE_PAGES)

        appel.assert_not_called()

    def test_comptage_exact_sur_un_livre_hybride(self):
        diagnostics, _ = self._diagnostiquer(
            [COUCHE_TEXTE_BONNE, "", COUCHE_TEXTE_BONNE, "trop court"]
        )

        diagnostic = diagnostics[0]

        self.assertEqual(diagnostic.pages_totales, 4)
        self.assertEqual(diagnostic.pages_exploitables, 2)
        self.assertEqual(diagnostic.pages_a_ocriser, 2)
        self.assertAlmostEqual(diagnostic.part_gratuite, 0.5)

    def test_motifs_de_refus_denombres(self):
        """
        Savoir *pourquoi* une couche est écartée permet de juger s'il faut
        relâcher un seuil ou accepter de payer.
        """
        diagnostics, _ = self._diagnostiquer(
            ["", "", blocks.sans_accents(COUCHE_TEXTE_BONNE), "court"]
        )

        raisons = diagnostics[0].raisons

        self.assertEqual(sum(raisons.values()), 4)
        self.assertTrue(any("accent" in motif for motif in raisons))

    def test_pages_deja_transcrites_comptees_comme_gratuites(self):
        io.ecrire_texte_atomique(self.chemins.page_txt(1), "déjà transcrite")
        io.ecrire_sidecar(
            self.chemins.page_json(1), {"statut": config.STATUT_TERMINE}
        )

        diagnostics, _ = self._diagnostiquer([""] * self.NOMBRE_PAGES)

        self.assertEqual(diagnostics[0].pages_deja_faites, 1)
        self.assertEqual(diagnostics[0].pages_a_ocriser, self.NOMBRE_PAGES - 1)

    def test_pdf_illisible_signale_sans_interrompre(self):
        with mock.patch.object(
            ocr, "ouvrir_pdf", side_effect=RuntimeError("PDF corrompu")
        ):
            diagnostics = ocr.diagnostiquer_couches_texte(self.base)

        self.assertIn("corrompu", diagnostics[0].erreur)
        self.assertEqual(diagnostics[0].pages_totales, 0)

    def test_dossier_sans_pdf(self):
        with tempfile.TemporaryDirectory() as vide:
            self.assertEqual(ocr.diagnostiquer_couches_texte(Path(vide)), [])


# ============================================================
# 9. LIMITE DE PAGES (essais)
# ============================================================


class TestPagesRetenues(unittest.TestCase):
    """Le calcul du plafond, isolé."""

    def test_sans_limite_tout_est_retenu(self):
        with mock.patch.object(config, "LIMITE_PAGES", None):
            self.assertEqual(ocr.pages_retenues(289), 289)

    def test_limite_appliquee(self):
        self.assertEqual(ocr.pages_retenues(289, 10), 10)

    def test_limite_superieure_au_document_sans_effet(self):
        self.assertEqual(ocr.pages_retenues(4, 10), 4)

    def test_parametre_prime_sur_la_configuration(self):
        with mock.patch.object(config, "LIMITE_PAGES", 5):
            self.assertEqual(ocr.pages_retenues(100, 20), 20)

    def test_limite_nulle_refusee(self):
        """
        Une limite à zéro produirait un OCR.txt vide d'apparence normale : mieux
        vaut échouer bruyamment.
        """
        for invalide in (0, -3):
            with self.subTest(limite=invalide):
                with self.assertRaises(ValueError) as contexte:
                    ocr.pages_retenues(100, invalide)

                self.assertIn("LIMITE_PAGES", str(contexte.exception))


class TestEssaiLimite(BaseOcr):
    """Un essai sur les premières pages, puis le passage complet."""

    NOMBRE_PAGES = 12

    def test_seules_les_premieres_pages_sont_traitees(self):
        _, appel = self.executer_avec_limite(4)

        numeros = [int(c.kwargs["libelle"].split()[-1]) for c in appel.call_args_list]

        self.assertEqual(numeros, [1, 2, 3, 4])

    def test_bilan_distingue_pages_du_pdf_et_pages_retenues(self):
        resultats, _ = self.executer_avec_limite(4)

        self.assertEqual(resultats[0].pages_du_pdf, self.NOMBRE_PAGES)
        self.assertEqual(resultats[0].pages_totales, 4)

    def test_ocr_ne_contient_que_les_pages_retenues(self):
        """
        Aucun marqueur d'échec pour les pages hors périmètre : elles n'ont pas
        échoué, elles n'ont simplement pas été demandées.
        """
        self.executer_avec_limite(4)

        contenu = io.lire_texte(self.chemins.ocr)

        self.assertIn(config.MARQUEUR_PAGE.format(numero=4), contenu)
        self.assertNotIn(config.MARQUEUR_PAGE.format(numero=5), contenu)
        self.assertNotIn("ÉCHEC OCR", contenu)

    def test_essai_declare_termine(self):
        resultats, _ = self.executer_avec_limite(4)

        self.assertEqual(resultats[0].statut, config.STATUT_TERMINE)
        self.assertTrue(resultats[0].complet)

    def test_passage_complet_reutilise_l_essai(self):
        """
        Le cœur de l'intérêt : les pages de l'essai ne sont ni perdues ni
        repayées.
        """
        self.executer_avec_limite(4)

        resultats, appel = self.executer()

        numeros = [int(c.kwargs["libelle"].split()[-1]) for c in appel.call_args_list]

        self.assertEqual(numeros, list(range(5, self.NOMBRE_PAGES + 1)))
        self.assertEqual(resultats[0].pages_sautees, 4)
        self.assertEqual(resultats[0].pages_totales, self.NOMBRE_PAGES)

    def test_ocr_complet_apres_le_passage_complet(self):
        self.executer_avec_limite(4)
        self.executer()

        pages = blocks.decouper_en_pages(io.lire_texte(self.chemins.ocr))

        self.assertEqual(len(pages), self.NOMBRE_PAGES)

    def test_limite_consignee_dans_le_journal(self):
        self.executer_avec_limite(4)

        configuration = io.lire_sidecar(io.dossier_temporaire(self.base) / "journal_ocr.json")["configuration"]

        self.assertEqual(configuration["limite_pages"], 4)

    def test_limite_lue_dans_la_configuration(self):
        with mock.patch.object(config, "LIMITE_PAGES", 3):
            _, appel = self.executer()

        self.assertEqual(appel.call_count, 3)

    def test_diagnostic_respecte_la_limite(self):
        document = DocumentFactice(self.NOMBRE_PAGES)

        with mock.patch.object(ocr, "ouvrir_pdf", return_value=document), \
             mock.patch.object(api, "appeler_modele") as appel:
            diagnostics = ocr.diagnostiquer_couches_texte(self.base, limite_pages=4)

        appel.assert_not_called()
        self.assertEqual(diagnostics[0].pages_du_pdf, self.NOMBRE_PAGES)
        self.assertEqual(diagnostics[0].pages_totales, 4)

    def executer_avec_limite(self, limite: int):
        """Lance l'étape avec un plafond de pages."""
        sequence = ["Texte de la page."] * 50

        with mock.patch.object(
            api, "appeler_modele", side_effect=lambda **_kw: resultat_api(sequence.pop(0))
        ) as appel:
            resultats = ocr.executer(self.base, limite_pages=limite)

        return resultats, appel


if __name__ == "__main__":
    unittest.main(verbosity=2)
