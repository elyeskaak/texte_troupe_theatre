"""
Tests de `theatre_editor.validation`.

Deux points reçoivent une attention particulière.

**L'alignement des blocs.** Le découpage n'est déterministe qu'à
`PAGES_PAR_BLOC` constant. Si cette valeur a changé depuis l'édition, la
comparaison porterait sur des passages différents et produirait un rapport
entièrement faux — le pire résultat possible, car il aurait l'air plausible.

**Les contrôles mécaniques.** Ils doivent détecter une perte réelle sans
signaler les différences légitimes entre OCR brut et texte édité : astérisques
ajoutées, marqueurs supprimés, fautes corrigées.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from theatre_editor import config, validation
from theatre_editor.utils import api, blocks, io


# ============================================================
# OUTILS
# ============================================================

OCR_PAGES = [
    "ACTE PREMIER\n\nUne auberge. Le soir.\n\nJAN\nNous y sommes enfin.",
    "MARIA\nJe t'attendais depuis une heure.\n\nPause.",
    "SCENE 2\n\nLE MESSAGER\nUn pli pour vous.",
    "JAN\nDonnez.\n\nIl sort.",
]

EDIT_BLOCS = [
    "**ACTE PREMIER**\n*Une auberge. Le soir.*\n**JAN.**\n"
    "Nous y sommes enfin.\n**MARIA.**\nJe t'attendais depuis une heure.\n*Pause.*",
    "**SCENE 2**\n**LE MESSAGER.**\nUn pli pour vous.\n**JAN.**\n"
    "Donnez.\n*Il sort.*",
]


def fabriquer_ocr() -> str:
    pages = [
        f"{config.MARQUEUR_PAGE.format(numero=n)}\n{contenu}"
        for n, contenu in enumerate(OCR_PAGES, start=1)
    ]

    return config.SEPARATEUR_PAGE.join(pages) + "\n"


def resultat_api(texte: str) -> api.ResultatAppel:
    return api.ResultatAppel(
        texte=texte,
        modele=config.MODEL_VALIDATION,
        response_id="resp_test",
        tentative=1,
        duree_secondes=2.0,
        tokens_entree=800,
        tokens_sortie=40,
    )


class BaseValidation(unittest.TestCase):
    """Socle : un livre déjà transcrit et édité, prêt à valider."""

    PAGES_PAR_BLOC = 2

    def setUp(self):
        self._verbosite = config.VERBOSITE
        config.VERBOSITE = 0

        self._patchs = [
            mock.patch.object(config, "PAGES_PAR_BLOC", self.PAGES_PAR_BLOC),
            mock.patch.object(api, "patienter"),
        ]
        for patch in self._patchs:
            patch.start()

        self._dossier = tempfile.TemporaryDirectory()
        self.base = Path(self._dossier.name)
        self.chemins = io.resoudre_chemins("Le Malentendu", self.base)

        io.ecrire_texte_atomique(self.chemins.ocr, fabriquer_ocr())

        for numero, contenu in enumerate(EDIT_BLOCS, start=1):
            io.ecrire_texte_atomique(self.chemins.raccord_txt(numero), contenu + "\n")

        io.ecrire_texte_atomique(self.chemins.edit, blocks.assembler(EDIT_BLOCS))

    def tearDown(self):
        for patch in self._patchs:
            patch.stop()
        self._dossier.cleanup()
        config.VERBOSITE = self._verbosite

    def executer(self, reponse=config.MENTION_AUCUN_PROBLEME):
        """Lance l'étape avec un modèle bouchonné."""
        effet = reponse if callable(reponse) else (lambda **_kw: resultat_api(reponse))

        with mock.patch.object(api, "appeler_modele", side_effect=effet) as appel:
            resultats = validation.executer(self.base)

        return resultats, appel

    @property
    def rapport(self) -> str:
        return io.lire_texte(self.chemins.report)


# ============================================================
# 1. CONTRÔLES MÉCANIQUES
# ============================================================


class TestControlesMecaniques(unittest.TestCase):
    """Testés directement, sans passer par l'étape : logique pure."""

    def test_edition_fidele_ne_declenche_rien(self):
        """
        Le point délicat : entre OCR brut et texte édité, les différences
        légitimes sont nombreuses. Aucune ne doit être signalée.
        """
        ocr = fabriquer_ocr()
        edit = blocks.assembler(EDIT_BLOCS)

        self.assertEqual(blocks.controles_mecaniques(ocr, edit), [])

    def test_asterisques_neutralisees_dans_le_ratio(self):
        """
        L'étape 2 ajoute `**` et `*` en quantité. Sans neutralisation, l'édition
        paraîtrait plus longue que la transcription alors qu'elle en aurait
        perdu des passages.
        """
        ocr = "JAN\nBonjour."
        edit = "**JAN.**\nBonjour."

        brut = blocks.normaliser_pour_comptage(edit)
        compare = blocks.normaliser_pour_comparaison(edit)

        self.assertIn("*", brut)
        self.assertNotIn("*", compare)
        self.assertEqual(blocks.comparer_volumes(ocr, edit), [])

    def test_volume_reduit_detecte(self):
        ocr = "JAN\n" + "Une longue réplique. " * 50
        edit = "**JAN.**\nUne longue réplique."

        constats = blocks.comparer_volumes(ocr, edit)

        self.assertTrue(any("volume réduit" in c for c in constats))

    def test_personnage_disparu_detecte(self):
        """
        Perte grave qu'un ratio global ne verrait pas sur 400 pages : un rôle
        entier absent.
        """
        ocr = "JAN\nA.\n\nLE MESSAGER\nB.\n\nMARIA\nC."
        edit = "**JAN.**\nA.\n**MARIA.**\nC."

        constats = blocks.comparer_labels(ocr, edit)

        self.assertEqual(len(constats), 1)
        self.assertIn("LE MESSAGER", constats[0])

    def test_controle_des_labels_asymetrique(self):
        """
        Un label apparu dans l'édition n'est pas signalé : il résulte le plus
        souvent d'une correction légitime de reconnaissance (« IAN » → « JAN »).
        """
        ocr = "IAN\nBonjour."
        edit = "**JAN.**\nBonjour.\n**MARIA.**\nBonsoir."

        constats = blocks.comparer_labels(edit, ocr)

        self.assertTrue(constats)
        self.assertFalse(any("MARIA" in c for c in blocks.comparer_labels(ocr, edit)))

    def test_marqueurs_techniques_ne_sont_pas_des_labels(self):
        """
        Régression. `[PAGE 1]` et `<<<PAGE_BREAK>>>` étaient pris pour des noms
        en capitales ; l'étape 2 les supprimant légitimement, ils étaient
        signalés comme « disparus » — cinq faux positifs à chaque livre,
        exactement le bruit que le rapport doit éviter.
        """
        ocr = "[PAGE 1]\nJAN\nA.\n\n<<<PAGE_BREAK>>>\n\n[PAGE 2]\nJAN\nB."
        edit = "**JAN.**\nA.\n**JAN.**\nB."

        self.assertEqual(blocks.comparer_labels(ocr, edit), [])

    def test_repliques_tres_courtes_ne_sont_pas_des_labels(self):
        """
        Régression. Une réplique « A. » satisfaisait le critère de capitales et
        passait pour un rôle.
        """
        labels = blocks.recenser_labels_capitales("JAN\nA.\nB.\nC.")

        self.assertEqual(labels, {"JAN"})

    def test_dialogue_partiellement_capitalise_ecarte(self):
        """Un seuil partiel de capitales laisserait passer du dialogue."""
        labels = blocks.recenser_labels_capitales(
            "JAN\nJe pars, Maria, et je ne reviendrai JAMAIS ici ce soir."
        )

        self.assertEqual(labels, {"JAN"})

    def test_titre_disparu_detecte(self):
        ocr = "ACTE PREMIER\n\nJAN\nA."
        edit = "**JAN.**\nA."

        self.assertTrue(any("ACTE PREMIER" in c for c in blocks.comparer_labels(ocr, edit)))

    def test_lignes_manquantes_detectees(self):
        ocr = "\n".join(f"Ligne {i}." for i in range(1, 21))
        edit = "Ligne 1.\nLigne 2."

        self.assertTrue(
            any("lignes manquantes" in c for c in blocks.comparer_lignes_non_vides(ocr, edit))
        )

    def test_marqueurs_de_page_exclus_du_comptage_de_lignes(self):
        """Leur suppression est légitime et ne doit pas compter comme une perte."""
        ocr = "[PAGE 1]\nLigne A.\n[PAGE 2]\nLigne B."
        edit = "Ligne A.\nLigne B."

        self.assertEqual(blocks.comparer_lignes_non_vides(ocr, edit), [])

    def test_convention_cassee_detectee(self):
        constats = blocks.controler_convention("**JAN.*\nBonjour.")

        self.assertTrue(any("astérisques" in c for c in constats))

    def test_artefact_non_supprime_detecte(self):
        constats = blocks.controler_convention("**JAN.**\n<<<PAGE_BREAK>>>\nBonjour.")

        self.assertTrue(any("artefact" in c for c in constats))


# ============================================================
# 2. ALIGNEMENT DES BLOCS
# ============================================================


class TestAlignement(BaseValidation):
    def test_alignement_nominal(self):
        resultats, _ = self.executer()

        self.assertEqual(resultats[0].statut, config.STATUT_TERMINE)
        self.assertEqual(resultats[0].blocs.total, len(EDIT_BLOCS))

    def test_pages_par_bloc_modifie_est_refuse(self):
        """
        Le rapport produit serait entièrement faux mais d'apparence plausible :
        mieux vaut refuser bruyamment que comparer des passages différents.
        """
        with mock.patch.object(config, "PAGES_PAR_BLOC", 1):
            resultats, appel = self.executer()

        self.assertEqual(resultats[0].statut, config.STATUT_ECHEC)
        self.assertIn("découpage incohérent", resultats[0].erreur)
        self.assertIn("PAGES_PAR_BLOC", resultats[0].erreur)
        # Aucun appel ne doit être payé sur un découpage incohérent.
        self.assertEqual(appel.call_count, 0)

    def test_edition_absente_est_signalee(self):
        self.chemins.edit.unlink()

        resultats, appel = self.executer()

        self.assertEqual(resultats[0].statut, config.STATUT_ECHEC)
        self.assertIn("edition", resultats[0].erreur)
        self.assertEqual(appel.call_count, 0)

    def test_blocs_raccordes_absents_sont_signales(self):
        for numero in range(1, len(EDIT_BLOCS) + 1):
            self.chemins.raccord_txt(numero).unlink()

        resultats, _ = self.executer()

        self.assertEqual(resultats[0].statut, config.STATUT_ECHEC)
        self.assertIn("aucun bloc raccordé", resultats[0].erreur)

    def test_portion_ocr_correspond_au_bloc(self):
        """Le modèle doit comparer deux versions du *même* passage."""
        pages = blocks.decouper_en_pages(fabriquer_ocr())
        liste = blocks.former_blocs(pages, self.PAGES_PAR_BLOC)

        portion = validation.texte_ocr_du_bloc(pages, liste[1])

        self.assertIn("LE MESSAGER", portion)
        self.assertNotIn("Nous y sommes enfin", portion)


# ============================================================
# 3. COMPOSITION DU RAPPORT
# ============================================================


class TestRapport(BaseValidation):
    def test_sections_attendues(self):
        self.executer()

        for section in (
            "RAPPORT DE CONTRÔLE QUALITÉ",
            "CONTRÔLES AUTOMATIQUES",
            "STRUCTURE DÉTECTÉE",
        ):
            with self.subTest(section=section):
                self.assertIn(section, self.rapport)

    def test_structure_detectee_reportee(self):
        """
        Permet de repérer un défaut de classification avant de générer le DOCX,
        au moment où l'on relit déjà le rapport.
        """
        self.executer()

        self.assertIn("Actes : 1", self.rapport)
        self.assertIn("Scènes : 1", self.rapport)
        self.assertIn("Personnages : 3", self.rapport)

    def test_blocs_sains_ne_sont_pas_detailles(self):
        """
        Énumérer trente-sept sections « rien à signaler » noierait les deux qui
        comptent.
        """
        self.executer()

        self.assertNotIn("BLOC 1 —", self.rapport)
        self.assertIn("aucun constat sur les 2 bloc(s)", self.rapport)

    def test_bloc_avec_constats_detaille(self):
        constat = (
            "[DIDASCALIE PERDUE] « Il sort » absente\n"
            "                  Après la réplique de JAN"
        )

        def effet(**kwargs):
            if kwargs["libelle"] == "bloc 2":
                return resultat_api(constat)
            return resultat_api(config.MENTION_AUCUN_PROBLEME)

        resultats, _ = self.executer(effet)

        self.assertIn("BLOC 2 — pages 3 à 4", self.rapport)
        self.assertIn("DIDASCALIE PERDUE", self.rapport)
        self.assertEqual(resultats[0].constats_modele, 1)
        self.assertEqual(resultats[0].blocs_sains, 1)

    def test_constats_comptes(self):
        deux = (
            "[TEXTE RACCOURCI] Réplique abrégée\n"
            "                  Vers « Donnez »\n"
            "[LIEU PERDU] « Une auberge » absent\n"
            "                  Au début du bloc"
        )

        self.assertEqual(validation.compter_constats(deux), 2)

    def test_mention_aucun_probleme_reconnue(self):
        self.assertTrue(validation.est_sain(config.MENTION_AUCUN_PROBLEME))
        self.assertTrue(validation.est_sain("aucun probleme detecte"))
        self.assertFalse(validation.est_sain("[LIGNE DISPARUE] quelque chose"))

    def test_constats_mecaniques_dans_le_rapport(self):
        # On ampute l'édition : le contrôle mécanique doit le voir.
        io.ecrire_texte_atomique(self.chemins.edit, "**JAN.**\nDonnez.\n")

        resultats, _ = self.executer()

        self.assertTrue(resultats[0].constats_mecaniques)
        self.assertIn("[ALERTE]", self.rapport)

    def test_aucun_ecart_mecanique_affiche_ok(self):
        self.executer()

        self.assertIn("aucun écart mécanique détecté", self.rapport)

    def test_bloc_non_verifie_signale(self):
        self.executer()
        self.chemins.report_bloc_txt(1).unlink()

        # On recompose sans relancer les appels.
        pages = blocks.decouper_en_pages(io.lire_texte(self.chemins.ocr))
        liste = blocks.former_blocs(pages, self.PAGES_PAR_BLOC)

        rapport, _, _ = validation.composer_rapport(
            nom_livre="Le Malentendu",
            ocr=io.lire_texte(self.chemins.ocr),
            edit=io.lire_texte(self.chemins.edit),
            liste_blocs=liste,
            chemins=self.chemins,
            constats_mecaniques=[],
        )

        self.assertIn("[NON VÉRIFIÉ]", rapport)


# ============================================================
# 4. LE TEXTE N'EST JAMAIS MODIFIÉ
# ============================================================


class TestAucuneModification(BaseValidation):
    def test_edit_intact_apres_validation(self):
        """
        Exigence absolue : cette étape produit un diagnostic, elle ne répare
        rien. Une boucle de correction automatique serait la porte ouverte à la
        violation du principe de fidélité.
        """
        avant = io.lire_texte(self.chemins.edit)

        self.executer("[LIGNE DISPARUE] une ligne manque\n     quelque part")

        self.assertEqual(io.lire_texte(self.chemins.edit), avant)

    def test_blocs_raccordes_intacts(self):
        avant = [
            io.lire_texte(self.chemins.raccord_txt(n))
            for n in range(1, len(EDIT_BLOCS) + 1)
        ]

        self.executer("[TEXTE RACCOURCI] abrégé\n     ici")

        apres = [
            io.lire_texte(self.chemins.raccord_txt(n))
            for n in range(1, len(EDIT_BLOCS) + 1)
        ]

        self.assertEqual(avant, apres)

    def test_ocr_intact(self):
        avant = io.lire_texte(self.chemins.ocr)

        self.executer()

        self.assertEqual(io.lire_texte(self.chemins.ocr), avant)


# ============================================================
# 5. REPRISE
# ============================================================


class TestReprise(BaseValidation):
    def test_seconde_execution_n_appelle_plus_rien(self):
        self.executer()
        resultats, appel = self.executer()

        self.assertEqual(appel.call_count, 0)
        self.assertEqual(resultats[0].blocs.sautees, len(EDIT_BLOCS))

    def test_rapport_recompose_a_chaque_execution(self):
        """
        Les contrôles mécaniques sont gratuits : le rapport doit refléter l'état
        courant, même sans nouvel appel.
        """
        self.executer()
        io.ecrire_texte_atomique(self.chemins.report, "rapport obsolète")

        self.executer()

        self.assertNotIn("obsolète", self.rapport)

    def test_bloc_porteur_de_constats_n_est_pas_refait(self):
        """
        Un bloc signalant un problème a été parfaitement vérifié : c'est le
        texte qui pose problème, pas la vérification. Confondre les deux ferait
        repayer l'appel à chaque exécution.
        """
        self.executer("[LIGNE DISPARUE] une ligne manque\n     ici")

        resultats, appel = self.executer()

        self.assertEqual(appel.call_count, 0)
        self.assertEqual(resultats[0].blocs.sautees, len(EDIT_BLOCS))

    def test_echec_est_repris(self):
        def effet(**kwargs):
            if kwargs["libelle"] == "bloc 1":
                raise api.EchecAppelAPI("panne simulée")
            return resultat_api(config.MENTION_AUCUN_PROBLEME)

        self.executer(effet)

        _, appel = self.executer()

        libelles = [c.kwargs["libelle"] for c in appel.call_args_list]

        self.assertEqual(libelles, ["bloc 1"])


# ============================================================
# 6. PARAMÈTRES ET JOURNAL
# ============================================================


class TestParametresEtJournal(BaseValidation):
    def test_les_deux_versions_sont_transmises(self):
        _, appel = self.executer()

        message = appel.call_args_list[0].kwargs["message"]

        self.assertIn(config.DELIM_SOURCE_DEBUT, message)
        self.assertIn(config.DELIM_EDIT_DEBUT, message)
        self.assertIn("Nous y sommes enfin", message)

    def test_modele_et_prompt_de_validation(self):
        _, appel = self.executer()

        kwargs = appel.call_args_list[0].kwargs

        self.assertEqual(kwargs["modele"], config.MODEL_VALIDATION)
        self.assertIn("Tu ne modifies jamais le texte", kwargs["instructions"])

    def test_journal_ecrit(self):
        self.executer()

        journal = io.lire_sidecar(io.dossier_temporaire(self.base) / "journal_validation.json")

        self.assertEqual(journal["etape"], "validation")
        self.assertEqual(len(journal["appels"]), len(EDIT_BLOCS))
        self.assertEqual(
            {a["unite"] for a in journal["appels"]}, {"validation"}
        )

    def test_sidecar_marque_les_blocs_sains(self):
        self.executer()

        sidecar = io.lire_sidecar(self.chemins.report_bloc_json(1))

        self.assertTrue(sidecar["sain"])
        self.assertEqual(sidecar["nombre_constats"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
