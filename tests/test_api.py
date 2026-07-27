"""
Tests de `theatre_editor.utils.api`.

Aucun appel réseau, aucune clé API, et `openai` n'a pas besoin d'être
installé : l'import du SDK est différé, et le tri des erreurs se fonde sur le
code HTTP plutôt que sur les classes d'exception du SDK. Toute la mécanique
qui décide *quand réessayer* et *quoi lire dans une réponse* est donc
vérifiable hors ligne, avec des doublures.

C'est la partie du module où une erreur coûte le plus cher en production :
un tri fautif transforme une clé invalide en quatre minutes d'attente, et une
troncature non détectée fait disparaître du texte sans bruit.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from theatre_editor import config
from theatre_editor.utils import api


# ============================================================
# DOUBLURES
# ============================================================


class ErreurHttp(Exception):
    """Exception portant un code HTTP, comme celles du SDK OpenAI."""

    def __init__(self, status_code: int):
        super().__init__(f"erreur HTTP {status_code}")
        self.status_code = status_code


class ErreurHttpImbriquee(Exception):
    """Exception dont le code est porté par un attribut `response`."""

    def __init__(self, status_code: int):
        super().__init__(f"erreur HTTP {status_code}")
        self.response = SimpleNamespace(status_code=status_code)


def reponse(
    texte: str = "Texte de sortie.",
    identifiant: str = "resp_abc123",
    statut: str = "completed",
    raison_incomplete: str | None = None,
    jetons: tuple[int, int] | None = (120, 340),
) -> SimpleNamespace:
    """Fabrique une réponse imitant celle de la Responses API."""
    details = (
        SimpleNamespace(reason=raison_incomplete)
        if raison_incomplete is not None
        else None
    )
    usage = (
        SimpleNamespace(input_tokens=jetons[0], output_tokens=jetons[1])
        if jetons
        else None
    )

    return SimpleNamespace(
        id=identifiant,
        output_text=texte,
        status=statut,
        incomplete_details=details,
        usage=usage,
        output=[],
    )


# ============================================================
# 1. CONSTRUCTION DE LA REQUÊTE
# ============================================================


class TestConstruireEntree(unittest.TestCase):
    def test_entree_texte_seul(self):
        entree = api.construire_entree("Bonjour")

        self.assertEqual(len(entree), 1)
        self.assertEqual(entree[0]["role"], "user")
        self.assertEqual(entree[0]["content"], [{"type": "input_text", "text": "Bonjour"}])

    def test_types_de_la_responses_api(self):
        """
        `input_text` / `input_image`, et non les types de Chat Completions
        (`text` / `image_url`) : confusion classique lors d'une migration.
        """
        entree = api.construire_entree("Transcris", image_png=b"\x89PNG-faux")
        types = [partie["type"] for partie in entree[0]["content"]]

        self.assertEqual(types, ["input_text", "input_image"])

    def test_image_encodee_en_url_de_donnees(self):
        entree = api.construire_entree("Transcris", image_png=b"abc")
        url = entree[0]["content"][1]["image_url"]

        self.assertTrue(url.startswith("data:image/png;base64,"))
        self.assertEqual(url, api.encoder_image_png(b"abc"))

    def test_texte_avant_image(self):
        """L'instruction doit précéder l'image pour être prise en compte."""
        entree = api.construire_entree("Transcris", image_png=b"abc")

        self.assertEqual(entree[0]["content"][0]["type"], "input_text")


class TestConstruireParametres(unittest.TestCase):
    def _parametres(self, **surcharges):
        base = {
            "modele": "gpt-4o",
            "instructions": "Tu es un éditeur.",
            "message": "Voici le texte.",
        }
        base.update(surcharges)

        return api.construire_parametres(**base)

    def test_parametres_essentiels(self):
        parametres = self._parametres()

        self.assertEqual(parametres["model"], "gpt-4o")
        self.assertEqual(parametres["instructions"], "Tu es un éditeur.")
        self.assertEqual(parametres["max_output_tokens"], config.MAX_OUTPUT_TOKENS)

    def test_store_suit_la_configuration(self):
        self.assertIs(self._parametres()["store"], config.STOCKER_REPONSES)

    def test_temperature_omise_si_none(self):
        """
        Certains modèles récents refusent `temperature` : l'envoyer
        systématiquement ferait échouer chaque appel.
        """
        if config.TEMPERATURE is None:
            self.assertNotIn("temperature", self._parametres())
        else:
            self.assertEqual(self._parametres()["temperature"], config.TEMPERATURE)

    def test_max_output_tokens_surchargeable(self):
        self.assertEqual(self._parametres(max_output_tokens=999)["max_output_tokens"], 999)

    def test_aucun_parametre_de_chat_completions(self):
        """Garde-fou : la Responses API n'utilise pas `messages`."""
        parametres = self._parametres()

        self.assertNotIn("messages", parametres)
        self.assertIn("input", parametres)


# ============================================================
# 2. LECTURE DE LA RÉPONSE
# ============================================================


class TestExtraireTexte(unittest.TestCase):
    def test_output_text_utilise_en_priorite(self):
        self.assertEqual(api.extraire_texte(reponse("  Bonjour  ")), "Bonjour")

    def test_repli_sur_la_structure_output(self):
        """
        Couvre les réponses dont `output_text` est vide alors que le contenu
        existe — par exemple lorsqu'un bloc de raisonnement précède le texte.
        """
        brute = SimpleNamespace(
            output_text="",
            output=[
                SimpleNamespace(content=[]),
                SimpleNamespace(content=[SimpleNamespace(text="Première partie.")]),
                SimpleNamespace(content=[SimpleNamespace(text="Seconde partie.")]),
            ],
        )

        self.assertEqual(
            api.extraire_texte(brute), "Première partie.\nSeconde partie."
        )

    def test_reponse_sans_texte_leve_une_erreur(self):
        brute = SimpleNamespace(output_text="", output=[])

        with self.assertRaises(api.ReponseVide):
            api.extraire_texte(brute)

    def test_reponse_blanche_leve_une_erreur(self):
        with self.assertRaises(api.ReponseVide):
            api.extraire_texte(SimpleNamespace(output_text="   \n  ", output=[]))


class TestTroncature(unittest.TestCase):
    def test_reponse_complete(self):
        self.assertIsNone(api.raison_troncature(reponse()))

    def test_troncature_detectee_avec_sa_raison(self):
        """
        Une réponse tronquée contient du texte valide, simplement incomplet.
        Sans ce contrôle, elle passerait pour un succès.
        """
        brute = reponse(statut="incomplete", raison_incomplete="max_output_tokens")

        self.assertEqual(api.raison_troncature(brute), "max_output_tokens")

    def test_troncature_sans_raison_precisee(self):
        brute = SimpleNamespace(status="incomplete", incomplete_details=None)

        self.assertEqual(api.raison_troncature(brute), "raison non précisée")


class TestLireJetons(unittest.TestCase):
    def test_jetons_lus(self):
        self.assertEqual(api.lire_jetons(reponse()), (120, 340))

    def test_absence_d_usage_toleree(self):
        self.assertEqual(api.lire_jetons(reponse(jetons=None)), (None, None))


# ============================================================
# 3. POLITIQUE DE RÉESSAI
# ============================================================


class TestEstReessayable(unittest.TestCase):
    def test_erreurs_non_reessayables(self):
        """
        Clé invalide, droits manquants, modèle inexistant, requête malformée :
        réessayer ne changerait rien et retarderait l'erreur réelle.
        """
        for code in (400, 401, 403, 404, 422):
            with self.subTest(code=code):
                self.assertFalse(api.est_reessayable(ErreurHttp(code)))

    def test_erreurs_reessayables(self):
        """Quota, délai dépassé, panne serveur : transitoires."""
        for code in (408, 409, 429, 500, 502, 503, 504):
            with self.subTest(code=code):
                self.assertTrue(api.est_reessayable(ErreurHttp(code)))

    def test_code_porte_par_l_attribut_response(self):
        self.assertFalse(api.est_reessayable(ErreurHttpImbriquee(401)))
        self.assertTrue(api.est_reessayable(ErreurHttpImbriquee(429)))

    def test_erreur_sans_code_est_reessayee(self):
        """Une erreur réseau n'a pas de code HTTP, et elle est transitoire."""
        self.assertTrue(api.est_reessayable(ConnectionError("connexion perdue")))

    def test_reponse_vide_est_reessayee(self):
        """Un modèle qui n'a rien renvoyé peut répondre à la tentative suivante."""
        self.assertTrue(api.est_reessayable(api.ReponseVide("vide")))

    def test_code_non_entier_ignore(self):
        """Un attribut `status_code` fantaisiste ne doit pas faire échouer le tri."""
        erreur = Exception("bizarre")
        erreur.status_code = "429"  # type: ignore[attr-defined]

        self.assertTrue(api.est_reessayable(erreur))


class TestCalculerAttente(unittest.TestCase):
    def test_croissance_exponentielle(self):
        attentes = [api.calculer_attente(n) for n in range(1, 5)]

        for precedente, suivante in zip(attentes, attentes[1:]):
            self.assertGreater(suivante, precedente)

    def test_plancher_conforme_a_la_base(self):
        base = config.ATTENTE_BASE_BACKOFF

        self.assertGreaterEqual(api.calculer_attente(1), base)

    def test_plafonnement(self):
        """L'attente ne doit pas exploser, jitter compris."""
        maximum = config.ATTENTE_MAX_BACKOFF * (1 + config.JITTER_BACKOFF)

        for tentative in range(1, 12):
            with self.subTest(tentative=tentative):
                self.assertLessEqual(api.calculer_attente(tentative), maximum)

    def test_jitter_produit_des_valeurs_variables(self):
        """
        Sans aléa, plusieurs reprises issues du même incident se
        resynchroniseraient et provoqueraient une nouvelle salve d'erreurs.
        """
        valeurs = {api.calculer_attente(3) for _ in range(40)}

        self.assertGreater(len(valeurs), 1)


# ============================================================
# 4. RÉSULTAT D'APPEL
# ============================================================


class TestResultatAppel(unittest.TestCase):
    def _resultat(self, **surcharges):
        base = {
            "texte": "Texte édité.",
            "modele": "gpt-5.5-2026-04-23",
            "response_id": "resp_1",
            "tentative": 2,
            "duree_secondes": 18.42,
            "tokens_entree": 1204,
            "tokens_sortie": 498,
        }
        base.update(surcharges)

        return api.ResultatAppel(**base)

    def test_champs_journal_couvrent_le_cahier_des_charges(self):
        champs = self._resultat().champs_journal()

        for attendu in (
            "modele",
            "response_id",
            "duree_secondes",
            "tokens_entree",
            "tokens_sortie",
            "longueur_sortie",
        ):
            with self.subTest(champ=attendu):
                self.assertIn(attendu, champs)

    def test_longueur_sortie_calculee(self):
        self.assertEqual(
            self._resultat(texte="abcde").champs_journal()["longueur_sortie"], 5
        )

    def test_avertissements_independants_entre_instances(self):
        """Piège du champ mutable partagé par défaut."""
        premier, second = self._resultat(), self._resultat()
        premier.avertissements.append("troncature")

        self.assertEqual(second.avertissements, [])


# ============================================================
# 5. CONSTRUCTION DU RÉSULTAT
# ============================================================


class TestConstruireResultat(unittest.TestCase):
    def test_reponse_complete_sans_avertissement(self):
        resultat = api._construire_resultat(
            reponse=reponse(),
            modele="gpt-4o",
            tentative=1,
            duree=3.5,
            libelle="page 1",
        )

        self.assertEqual(resultat.texte, "Texte de sortie.")
        self.assertEqual(resultat.response_id, "resp_abc123")
        self.assertFalse(resultat.tronquee)
        self.assertEqual(resultat.avertissements, [])

    def test_troncature_remontee_en_avertissement(self):
        verbosite = config.VERBOSITE
        config.VERBOSITE = 0  # silence la console pendant le test

        try:
            resultat = api._construire_resultat(
                reponse=reponse(statut="incomplete", raison_incomplete="max_output_tokens"),
                modele="gpt-4o",
                tentative=1,
                duree=3.5,
                libelle="bloc 12",
            )
        finally:
            config.VERBOSITE = verbosite

        self.assertTrue(resultat.tronquee)
        self.assertTrue(any("tronquée" in a for a in resultat.avertissements))


# ============================================================
# 6. BOUCLE DE RÉESSAI
# ============================================================


class ClientFactice:
    """
    Imite `client.responses.create()` en rejouant une séquence imposée.

    Chaque élément de `sequence` est soit une exception à lever, soit une
    réponse à retourner. Compte ses appels, ce qui permet de vérifier qu'une
    erreur non réessayable n'en déclenche pas quatre.
    """

    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.appels = 0
        self.derniers_parametres: dict | None = None
        self.responses = self

    def create(self, **parametres):
        self.appels += 1
        self.derniers_parametres = parametres

        element = self.sequence.pop(0)

        if isinstance(element, Exception):
            raise element

        return element


class TestAppelerModele(unittest.TestCase):
    """
    La boucle de réessai, exécutée de bout en bout sans réseau.

    `time.sleep` est neutralisé : sans cela, le seul test d'épuisement des
    tentatives durerait plus d'une minute.
    """

    def setUp(self):
        self._verbosite = config.VERBOSITE
        config.VERBOSITE = 0

        self._dormir = mock.patch.object(api.time, "sleep")
        self.dormir = self._dormir.start()

    def tearDown(self):
        self._dormir.stop()
        config.VERBOSITE = self._verbosite

    def _appeler(self, sequence, **surcharges):
        client = ClientFactice(sequence)

        with mock.patch.object(api, "obtenir_client", return_value=client):
            base = {
                "modele": "gpt-4o",
                "instructions": "Tu es un éditeur.",
                "message": "Voici le texte.",
                "libelle": "page 1",
            }
            base.update(surcharges)

            return client, api.appeler_modele(**base)

    def test_succes_du_premier_coup(self):
        client, resultat = self._appeler([reponse("Transcription.")])

        self.assertEqual(resultat.texte, "Transcription.")
        self.assertEqual(resultat.tentative, 1)
        self.assertEqual(client.appels, 1)
        self.dormir.assert_not_called()

    def test_erreur_transitoire_puis_succes(self):
        client, resultat = self._appeler(
            [ErreurHttp(429), reponse("Transcription.")]
        )

        self.assertEqual(resultat.tentative, 2)
        self.assertEqual(client.appels, 2)
        # Une seule attente, entre les deux tentatives.
        self.assertEqual(self.dormir.call_count, 1)

    def test_erreur_non_reessayable_echoue_immediatement(self):
        """
        Une clé invalide ne deviendra pas valide en attendant. Le pipeline doit
        afficher l'erreur tout de suite, pas après quatre attentes.
        """
        with self.assertRaises(api.EchecAppelAPI) as contexte:
            self._appeler([ErreurHttp(401)])

        self.assertIn("non réessayable", str(contexte.exception))
        self.dormir.assert_not_called()

    def test_modele_inexistant_echoue_immediatement_avec_son_nom(self):
        with self.assertRaises(api.EchecAppelAPI) as contexte:
            self._appeler([ErreurHttp(404)], modele="gpt-5.5-mini")

        # Le message doit nommer le modèle fautif : c'est la cause la plus
        # probable d'un 404, et l'utilisateur doit savoir quoi corriger.
        self.assertIn("gpt-5.5-mini", str(contexte.exception))

    def test_epuisement_des_tentatives(self):
        sequence = [ErreurHttp(503)] * config.MAX_TENTATIVES

        with self.assertRaises(api.EchecAppelAPI) as contexte:
            self._appeler(sequence)

        self.assertIn(str(config.MAX_TENTATIVES), str(contexte.exception))
        # Une attente de moins que de tentatives : on ne patiente pas après
        # le dernier échec.
        self.assertEqual(self.dormir.call_count, config.MAX_TENTATIVES - 1)

    def test_reponse_vide_declenche_une_nouvelle_tentative(self):
        vide = SimpleNamespace(output_text="", output=[], status="completed")

        client, resultat = self._appeler([vide, reponse("Enfin du texte.")])

        self.assertEqual(resultat.texte, "Enfin du texte.")
        self.assertEqual(client.appels, 2)

    def test_parametres_transmis_au_client(self):
        client, _ = self._appeler([reponse()], modele="gpt-5.5-2026-04-23")

        parametres = client.derniers_parametres
        self.assertEqual(parametres["model"], "gpt-5.5-2026-04-23")
        self.assertEqual(parametres["instructions"], "Tu es un éditeur.")
        self.assertIs(parametres["store"], config.STOCKER_REPONSES)
        self.assertIn("input", parametres)

    def test_mode_vision_joint_l_image(self):
        client, _ = self._appeler([reponse()], image_png=b"\x89PNG-faux")

        contenu = client.derniers_parametres["input"][0]["content"]

        self.assertEqual([p["type"] for p in contenu], ["input_text", "input_image"])

    def test_duree_mesuree(self):
        _, resultat = self._appeler([reponse()])

        self.assertGreaterEqual(resultat.duree_secondes, 0.0)


# ============================================================
# 7. MODÈLES CONFIGURÉS
# ============================================================


class TestModelesConfigures(unittest.TestCase):
    def test_les_quatre_etapes_sont_couvertes(self):
        self.assertEqual(
            set(api.MODELES_CONFIGURES), {"ocr", "edition", "raccord", "validation"}
        )

    def test_identifiants_non_vides(self):
        for etape, modele in api.MODELES_CONFIGURES.items():
            with self.subTest(etape=etape):
                self.assertTrue(modele.strip())

    def test_raccord_distinct_de_l_edition(self):
        """Décision n° 1 : un modèle léger pour la passe de raccord."""
        self.assertNotEqual(config.MODEL_RACCORD, config.MODEL_EDITION)


if __name__ == "__main__":
    unittest.main(verbosity=2)
