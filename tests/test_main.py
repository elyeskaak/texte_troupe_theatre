"""
Tests de `theatre_editor.main`.

L'orchestration n'a pas de logique métier, mais elle porte deux
responsabilités dont l'erreur serait coûteuse : **enchaîner les étapes dans le
bon ordre en s'arrêtant au bon moment**, et **rendre un code de sortie exact**.

Poursuivre après une étape incomplète est le piège principal : l'étape suivante
travaillerait sur des données partielles et produirait un résultat trompeur —
un `EDIT.txt` amputé, un DOCX qui semble complet.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from theatre_editor import ETAPES, config, main


def bilan(statut: str = config.STATUT_TERMINE, complet: bool = True):
    """Fabrique un bilan de livre minimal."""
    return SimpleNamespace(nom="Le Malentendu", statut=statut, complet=complet)


class BaseMain(unittest.TestCase):
    def setUp(self):
        self._verbosite = config.VERBOSITE
        config.VERBOSITE = 0

    def tearDown(self):
        config.VERBOSITE = self._verbosite

    def lancer(self, argv, resultats_par_etape):
        """
        Lance `main()` avec les étapes bouchonnées.

        Args:
            resultats_par_etape: nom d'étape → liste de bilans, ou exception.
        """
        appels: list[str] = []

        def charger(nom):
            def executer(dossier):
                appels.append(nom)
                valeur = resultats_par_etape.get(nom, [bilan()])

                # `BaseException` et non `Exception` : `KeyboardInterrupt` ne
                # dérive pas d'`Exception`, et c'est précisément pourquoi
                # `main()` doit l'attraper par une clause distincte.
                if isinstance(valeur, BaseException):
                    raise valeur

                return valeur

            return executer

        with mock.patch.object(main, "_charger_etape", side_effect=charger):
            code = main.main(argv)

        return code, appels


# ============================================================
# 1. ANALYSE DES ARGUMENTS
# ============================================================


class TestArguments(unittest.TestCase):
    def test_etape_par_defaut(self):
        arguments = main.construire_analyseur().parse_args([])

        self.assertEqual(arguments.etape, "tout")

    def test_les_quatre_etapes_et_tout_sont_admises(self):
        for etape in (*ETAPES, "tout"):
            with self.subTest(etape=etape):
                arguments = main.construire_analyseur().parse_args(["--etape", etape])
                self.assertEqual(arguments.etape, etape)

    def test_etape_inconnue_refusee(self):
        with self.assertRaises(SystemExit):
            main.construire_analyseur().parse_args(["--etape", "traduction"])

    def test_dossier_converti_en_chemin(self):
        arguments = main.construire_analyseur().parse_args(["--dossier", "/tmp/essai"])

        self.assertIsInstance(arguments.dossier, Path)

    def test_verbosite_appliquee(self):
        verbosite = config.VERBOSITE
        try:
            main._appliquer_verbosite(SimpleNamespace(silencieux=True, detaille=False))
            self.assertEqual(config.VERBOSITE, 0)

            main._appliquer_verbosite(SimpleNamespace(silencieux=False, detaille=True))
            self.assertEqual(config.VERBOSITE, 2)
        finally:
            config.VERBOSITE = verbosite


# ============================================================
# 2. CHARGEMENT DIFFÉRÉ
# ============================================================


class TestChargementEtapes(unittest.TestCase):
    def test_les_quatre_etapes_exposent_executer(self):
        for etape in ETAPES:
            with self.subTest(etape=etape):
                self.assertTrue(callable(main._charger_etape(etape)))

    def test_etape_inconnue_leve_une_erreur(self):
        with self.assertRaises(ValueError):
            main._charger_etape("traduction")

    def test_docx_ne_depend_pas_du_sdk_openai(self):
        """
        Import différé : générer un DOCX ne doit pas exiger `openai`. Une
        installation partielle doit échouer sur la dépendance réellement
        manquante, pas à l'import du module.
        """
        import theatre_editor.docx_export as module

        source = Path(module.__file__).read_text(encoding="utf-8")

        self.assertNotIn("import openai", source)
        self.assertNotIn("utils import api", source)


# ============================================================
# 3. ENCHAÎNEMENT
# ============================================================


class TestEnchainement(BaseMain):
    def test_etape_unique(self):
        code, appels = self.lancer(["--etape", "docx"], {})

        self.assertEqual(code, main.CODE_SUCCES)
        self.assertEqual(appels, ["docx"])

    def test_tout_enchaine_les_quatre_dans_l_ordre(self):
        code, appels = self.lancer(["--etape", "tout"], {})

        self.assertEqual(code, main.CODE_SUCCES)
        self.assertEqual(appels, list(ETAPES))

    def test_arret_sur_etape_incomplete(self):
        """
        Le piège principal. Poursuivre ferait travailler l'étape suivante sur
        des données partielles, et produirait un DOCX d'apparence complète.
        """
        code, appels = self.lancer(
            ["--etape", "tout"],
            {"edition": [bilan(complet=False)]},
        )

        self.assertEqual(code, main.CODE_REPRISE_NECESSAIRE)
        self.assertEqual(appels, ["ocr", "edition"])

    def test_arret_sur_etape_en_echec(self):
        code, appels = self.lancer(
            ["--etape", "tout"],
            {"ocr": [bilan(statut=config.STATUT_ECHEC)]},
        )

        self.assertEqual(code, main.CODE_REPRISE_NECESSAIRE)
        self.assertEqual(appels, ["ocr"])

    def test_absence_de_fichier_d_entree_arrete_l_enchainement(self):
        """
        Une étape sans résultat n'est pas une réussite : c'est le signe que la
        précédente n'a pas produit ce qu'il fallait.
        """
        code, appels = self.lancer(["--etape", "tout"], {"ocr": []})

        self.assertEqual(code, main.CODE_REPRISE_NECESSAIRE)
        self.assertEqual(appels, ["ocr"])

    def test_option_pour_continuer_malgre_l_echec(self):
        code, appels = self.lancer(
            ["--etape", "tout", "--continuer-malgre-echec"],
            {"ocr": [bilan(complet=False)]},
        )

        self.assertEqual(appels, list(ETAPES))
        # Le code de sortie reste en échec malgré la poursuite.
        self.assertEqual(code, main.CODE_REPRISE_NECESSAIRE)

    def test_dossier_transmis_aux_etapes(self):
        recu = []

        def charger(nom):
            def executer(dossier):
                recu.append(dossier)
                return [bilan()]

            return executer

        with mock.patch.object(main, "_charger_etape", side_effect=charger):
            main.main(["--etape", "ocr", "--dossier", "/tmp/essai"])

        self.assertEqual(recu, [Path("/tmp/essai")])


# ============================================================
# 4. CODES DE SORTIE ET ERREURS
# ============================================================


class TestCodesDeSortie(BaseMain):
    def test_succes_vaut_zero(self):
        code, _ = self.lancer(["--etape", "ocr"], {})

        self.assertEqual(code, 0)

    def test_interruption_clavier_conserve_le_travail(self):
        """
        Une interruption volontaire n'est pas une erreur : le travail écrit est
        conservé et la reprise repartira de là.
        """
        code, _ = self.lancer(["--etape", "ocr"], {"ocr": KeyboardInterrupt()})

        self.assertEqual(code, main.CODE_REPRISE_NECESSAIRE)

    def test_erreurs_attendues_sont_rattrapees(self):
        """
        Ces messages sont déjà rédigés pour l'utilisateur : on les affiche, on
        ne remonte pas une trace d'exception.
        """
        for erreur in (
            FileNotFoundError("Drive non monté"),
            NotADirectoryError("pas un dossier"),
            RuntimeError("clé API introuvable"),
            ValueError("découpage incohérent"),
        ):
            with self.subTest(erreur=type(erreur).__name__):
                code, _ = self.lancer(["--etape", "ocr"], {"ocr": erreur})
                self.assertEqual(code, main.CODE_REPRISE_NECESSAIRE)

    def test_erreur_inattendue_remonte(self):
        """
        Une erreur non prévue doit remonter avec sa trace : la masquer
        empêcherait de diagnostiquer un vrai défaut.
        """
        with self.assertRaises(ZeroDivisionError):
            self.lancer(["--etape", "ocr"], {"ocr": ZeroDivisionError("bug")})


# ============================================================
# 5. VÉRIFICATION DES MODÈLES
# ============================================================


class TestVerificationModeles(BaseMain):
    def test_tous_les_modeles_disponibles(self):
        from theatre_editor.utils import api

        with mock.patch.object(
            api,
            "verifier_modeles_configures",
            return_value={etape: True for etape in api.MODELES_CONFIGURES},
        ):
            self.assertEqual(main.main(["--verifier-modeles"]), main.CODE_SUCCES)

    def test_modele_manquant_signale(self):
        from theatre_editor.utils import api

        resultats = {etape: True for etape in api.MODELES_CONFIGURES}
        resultats["raccord"] = False

        with mock.patch.object(
            api, "verifier_modeles_configures", return_value=resultats
        ):
            self.assertEqual(
                main.main(["--verifier-modeles"]), main.CODE_REPRISE_NECESSAIRE
            )

    def test_verification_court_circuite_les_etapes(self):
        from theatre_editor.utils import api

        with mock.patch.object(
            api,
            "verifier_modeles_configures",
            return_value={etape: True for etape in api.MODELES_CONFIGURES},
        ):
            _, appels = self.lancer(["--verifier-modeles"], {})

        self.assertEqual(appels, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
