"""
Tests de `theatre_editor.edition`.

L'attention se porte en priorité sur la **passe de raccord**, qui est le point
le plus risqué du pipeline : elle réécrit les fichiers en place, si bien qu'une
réponse aberrante du modèle détruirait du texte sans retour possible. Plusieurs
tests éprouvent donc explicitement les refus de correction.

Sont également vérifiés l'invariant de reprise sur les deux passes, la
propagation des corrections de jonction en jonction, et le fait que `EDIT.txt`
soit assemblé depuis `_EDIT_raccords/` et non depuis `_EDIT_blocs/`.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from theatre_editor import config, edition
from theatre_editor.utils import api, blocks, io


# ============================================================
# OUTILS
# ============================================================


def fabriquer_ocr(nombre_pages: int) -> str:
    """Fabrique un fichier OCR de synthèse, au format de l'étape 1."""
    pages = [
        f"{config.MARQUEUR_PAGE.format(numero=n)}\n"
        f"PERSONNAGE {n}\nRéplique de la page {n}."
        for n in range(1, nombre_pages + 1)
    ]

    return config.SEPARATEUR_PAGE.join(pages) + "\n"


def reponse_raccord(gauche: str, droite: str) -> str:
    """Formate une réponse de raccord conforme au format imposé."""
    return (
        f"{config.DELIM_RACCORD_GAUCHE}\n{gauche}\n"
        f"{config.DELIM_RACCORD_GAUCHE_FIN}\n"
        f"{config.DELIM_RACCORD_DROIT}\n{droite}\n"
        f"{config.DELIM_RACCORD_DROIT_FIN}"
    )


def resultat_api(texte: str, modele: str = config.MODEL_EDITION) -> api.ResultatAppel:
    return api.ResultatAppel(
        texte=texte,
        modele=modele,
        response_id="resp_test",
        tentative=1,
        duree_secondes=2.0,
        tokens_entree=500,
        tokens_sortie=480,
    )


class BaseEdition(unittest.TestCase):
    """Socle : dossier temporaire, console muette, OCR de synthèse."""

    PAGES = 6
    PAGES_PAR_BLOC = 2

    def setUp(self):
        self._verbosite = config.VERBOSITE
        config.VERBOSITE = 0

        self._patch_taille = mock.patch.object(
            config, "PAGES_PAR_BLOC", self.PAGES_PAR_BLOC
        )
        self._patch_taille.start()

        self._patch_pause = mock.patch.object(api, "patienter")
        self._patch_pause.start()

        self._dossier = tempfile.TemporaryDirectory()
        self.base = Path(self._dossier.name)
        self.chemins = io.resoudre_chemins("Le Malentendu", self.base)

        io.ecrire_texte_atomique(self.chemins.ocr, fabriquer_ocr(self.PAGES))

    def tearDown(self):
        self._patch_pause.stop()
        self._patch_taille.stop()
        self._dossier.cleanup()
        config.VERBOSITE = self._verbosite

    @property
    def nombre_blocs(self) -> int:
        return -(-self.PAGES // self.PAGES_PAR_BLOC)

    def executer(self, effet=None):
        """Lance l'étape avec un `appeler_modele` bouchonné."""
        if effet is None:
            effet = self.effet_par_defaut

        with mock.patch.object(api, "appeler_modele", side_effect=effet) as appel:
            resultats = edition.executer(self.base)

        return resultats, appel

    @staticmethod
    def effet_par_defaut(**kwargs):
        """
        Comportement nominal : l'édition rend un texte plausible, le raccord
        rend les extraits inchangés.
        """
        libelle = kwargs["libelle"]

        if libelle.startswith("bloc"):
            return resultat_api(editer_comme_le_modele(kwargs["message"]))

        gauche, droite = extraire_extraits_du_message(kwargs["message"])
        return resultat_api(reponse_raccord(gauche, droite), config.MODEL_RACCORD)


def extraire_source_du_message(message: str) -> str:
    """Relit le texte OCR envoyé au modèle d'édition."""
    debut = message.index(config.DELIM_SOURCE_DEBUT) + len(config.DELIM_SOURCE_DEBUT)
    fin = message.index(config.DELIM_SOURCE_FIN)

    return message[debut:fin].strip()


def editer_comme_le_modele(message: str) -> str:
    """
    Simule une édition fidèle du bloc reçu.

    Il ne suffit pas de rendre un texte plausible : `verifier_sortie()` compare
    les volumes d'entrée et de sortie, et une réponse deux fois plus courte que
    l'entrée est marquée suspecte — à juste titre. Une doublure qui ignorerait
    cette contrainte ferait échouer la reprise sans révéler aucun défaut du
    code.

    On applique donc au texte source la transformation attendue : suppression
    des marqueurs de page, et mise en forme des noms de personnages.
    """
    source = extraire_source_du_message(message)
    lignes: list[str] = []

    for ligne in source.split("\n"):
        nue = ligne.strip()

        if not nue or nue.startswith("[PAGE") or "<<<PAGE_BREAK>>>" in nue:
            continue

        if nue.startswith("PERSONNAGE"):
            lignes.append(f"**{nue}.**")
        else:
            lignes.append(nue)

    return "\n".join(lignes)


def extraire_extraits_du_message(message: str) -> tuple[str, str]:
    """Relit les deux extraits envoyés au modèle de raccord."""
    return blocks.extraire_blocs_raccord(message)


# ============================================================
# 1. DÉCOUPAGE ET PASSE 2a
# ============================================================


class TestEditionDesBlocs(BaseEdition):
    def test_nombre_de_blocs_conforme_au_decoupage(self):
        resultats, _ = self.executer()

        self.assertEqual(resultats[0].blocs.total, self.nombre_blocs)

    def test_un_appel_par_bloc_puis_un_par_jonction(self):
        _, appel = self.executer()

        attendu = self.nombre_blocs + (self.nombre_blocs - 1)

        self.assertEqual(appel.call_count, attendu)

    def test_blocs_ecrits_avec_leurs_sidecars(self):
        self.executer()

        for numero in range(1, self.nombre_blocs + 1):
            with self.subTest(bloc=numero):
                self.assertTrue(self.chemins.bloc_txt(numero).exists())
                self.assertTrue(io.unite_terminee(self.chemins.bloc_json(numero)))

    def test_sidecar_conserve_les_frontieres_de_pages(self):
        """
        L'étape 3 redécoupe OCR.txt avec ces frontières : sans elles, la
        comparaison bloc à bloc serait impossible.
        """
        self.executer()

        sidecar = io.lire_sidecar(self.chemins.bloc_json(1))

        self.assertEqual(sidecar["page_debut"], 1)
        self.assertEqual(sidecar["page_fin"], self.PAGES_PAR_BLOC)

    def test_prompt_edition_et_delimiteurs_transmis(self):
        _, appel = self.executer()

        appel_bloc = next(
            c for c in appel.call_args_list if c.kwargs["libelle"].startswith("bloc")
        )

        self.assertIn("La fidélité au texte fourni", appel_bloc.kwargs["instructions"])
        self.assertIn(config.DELIM_SOURCE_DEBUT, appel_bloc.kwargs["message"])
        self.assertEqual(appel_bloc.kwargs["modele"], config.MODEL_EDITION)

    def test_avertissement_sur_le_decoupage_arbitraire(self):
        """
        Sans cet avertissement, le modèle aurait tendance à « terminer » une
        phrase coupée ou à fabriquer une transition.
        """
        _, appel = self.executer()

        message = next(
            c.kwargs["message"]
            for c in appel.call_args_list
            if c.kwargs["libelle"].startswith("bloc")
        )

        self.assertIn("Ne crée aucune transition", message)

    def test_bloc_tronque_est_suspect(self):
        def effet(**kwargs):
            if kwargs["libelle"] == "bloc 1":
                return resultat_api("trop court")
            return BaseEdition.effet_par_defaut(**kwargs)

        resultats, _ = self.executer(effet)

        self.assertEqual(resultats[0].blocs.suspectes, 1)

    def test_fichier_ocr_absent_ne_produit_rien(self):
        with tempfile.TemporaryDirectory() as vide:
            self.assertEqual(edition.executer(Path(vide)), [])


# ============================================================
# 2. LE GARDE-FOU DE LA MUTATION EN PLACE
# ============================================================


class TestGardeFouRaccord(BaseEdition):
    """
    La passe de raccord réécrit les fichiers en place. Ces tests vérifient
    qu'une réponse aberrante ne peut pas détruire de texte.
    """

    PAGES = 4

    def _executer_avec_raccord(self, reponse_du_modele):
        def effet(**kwargs):
            libelle = kwargs["libelle"]

            if libelle.startswith("bloc"):
                numero = int(libelle.split()[-1])
                # Blocs volontairement longs, pour que le ratio soit parlant.
                return resultat_api(
                    "\n".join(f"Ligne {i} du bloc {numero}." for i in range(1, 21))
                )

            gauche, droite = extraire_extraits_du_message(kwargs["message"])
            return resultat_api(
                reponse_du_modele(gauche, droite), config.MODEL_RACCORD
            )

        return self.executer(effet)

    def test_format_non_respecte_conserve_les_extraits(self):
        """
        Les délimiteurs sont introuvables : on ne sait pas ce que le modèle a
        voulu dire, donc on ne touche à rien.
        """
        avant = None

        def reponse(gauche, droite):
            nonlocal avant
            avant = gauche
            return "J'ai bien examiné la jonction, tout va bien."

        resultats, _ = self._executer_avec_raccord(reponse)

        contenu = io.lire_texte(self.chemins.raccord_txt(1))

        self.assertIn("Ligne 20 du bloc 1.", contenu)
        self.assertEqual(resultats[0].raccords.suspectes, 1)

    def test_modele_qui_resume_est_refuse(self):
        """
        Cas le plus dangereux : le modèle rend un extrait bien plus court. Sans
        garde-fou, 18 lignes disparaîtraient définitivement.
        """
        resultats, _ = self._executer_avec_raccord(
            lambda gauche, droite: reponse_raccord("Résumé.", droite)
        )

        contenu = io.lire_texte(self.chemins.raccord_txt(1))

        self.assertIn("Ligne 1 du bloc 1.", contenu)
        self.assertIn("Ligne 20 du bloc 1.", contenu)
        self.assertNotIn("Résumé.", contenu)
        self.assertEqual(resultats[0].raccords.suspectes, 1)

    def test_modele_qui_delaye_est_refuse(self):
        resultats, _ = self._executer_avec_raccord(
            lambda gauche, droite: reponse_raccord(
                gauche + "\n" + "\n".join(f"Ajout {i}." for i in range(30)), droite
            )
        )

        self.assertNotIn("Ajout 1.", io.lire_texte(self.chemins.raccord_txt(1)))
        self.assertEqual(resultats[0].raccords.suspectes, 1)

    def test_extrait_vide_est_refuse(self):
        resultats, _ = self._executer_avec_raccord(
            lambda gauche, droite: reponse_raccord("", droite)
        )

        self.assertIn("Ligne 20 du bloc 1.", io.lire_texte(self.chemins.raccord_txt(1)))
        self.assertEqual(resultats[0].raccords.suspectes, 1)

    def test_correction_legitime_est_appliquee(self):
        """
        Contrepartie des tests précédents : une correction de faible amplitude
        doit bien être retenue, sinon le garde-fou serait inutile.
        """

        def reponse(gauche, droite):
            # Ressoudure plausible : une seule ligne modifiée.
            return reponse_raccord(
                gauche.replace("Ligne 20 du bloc 1.", "Ligne 20 du bloc 1 ressoudée."),
                droite,
            )

        resultats, _ = self._executer_avec_raccord(reponse)

        self.assertIn("ressoudée", io.lire_texte(self.chemins.raccord_txt(1)))
        self.assertEqual(resultats[0].raccords.suspectes, 0)


# ============================================================
# 3. MÉCANIQUE DU RACCORD
# ============================================================


class TestMecaniqueRaccord(BaseEdition):
    PAGES = 6

    def test_blocs_copies_vers_le_dossier_de_raccord(self):
        self.executer()

        for numero in range(1, self.nombre_blocs + 1):
            with self.subTest(bloc=numero):
                self.assertTrue(self.chemins.raccord_txt(numero).exists())

    def test_copie_ne_ecrase_pas_les_corrections_acquises(self):
        """
        Recopier depuis `_EDIT_blocs/` à chaque exécution annulerait tout le
        travail de raccord déjà effectué.
        """
        self.executer()

        io.ecrire_texte_atomique(
            self.chemins.raccord_txt(1), "TEXTE DEJA RACCORDE\n"
        )

        liste = blocks.former_blocs(
            blocks.decouper_en_pages(io.lire_texte(self.chemins.ocr)),
            self.PAGES_PAR_BLOC,
        )
        edition.preparer_blocs_raccords(liste, self.chemins)

        self.assertIn("DEJA RACCORDE", io.lire_texte(self.chemins.raccord_txt(1)))

    def test_jonctions_traitees_dans_l_ordre_croissant(self):
        """
        L'ordre est significatif : le bloc droit corrigé à la jonction N sert de
        bloc gauche à la jonction N+1.
        """
        _, appel = self.executer()

        numeros = [
            int(c.kwargs["libelle"].split()[-1])
            for c in appel.call_args_list
            if c.kwargs["libelle"].startswith("raccord")
        ]

        self.assertEqual(numeros, sorted(numeros))
        self.assertEqual(numeros, list(range(1, self.nombre_blocs)))

    def test_propagation_d_une_correction_a_la_jonction_suivante(self):
        """
        La correction appliquée au bloc 2 par la jonction 1 doit être visible du
        modèle lors de la jonction 2.
        """
        vus: dict[int, str] = {}

        def effet(**kwargs):
            libelle = kwargs["libelle"]

            if libelle.startswith("bloc"):
                numero = int(libelle.split()[-1])
                return resultat_api(
                    "\n".join(f"Ligne {i} du bloc {numero}." for i in range(1, 21))
                )

            numero = int(libelle.split()[-1])
            gauche, droite = extraire_extraits_du_message(kwargs["message"])
            vus[numero] = gauche

            if numero == 1:
                # On marque le début du bloc droit (bloc 2).
                droite = droite.replace("Ligne 1 du bloc 2.", "MARQUE JONCTION 1")

            return resultat_api(reponse_raccord(gauche, droite), config.MODEL_RACCORD)

        self.executer(effet)

        # La jonction 2 lit le bloc 2, dont le début porte désormais la marque.
        self.assertIn("MARQUE JONCTION 1", io.lire_texte(self.chemins.raccord_txt(2)))

    def test_recollage_preserve_le_texte_hors_fenetre(self):
        """
        Le raccord ne voit que 50 lignes de chaque côté. Le reste du bloc doit
        traverser la passe intact.
        """
        with mock.patch.object(config, "LIGNES_CONTEXTE_RACCORD", 2):

            def effet(**kwargs):
                libelle = kwargs["libelle"]

                if libelle.startswith("bloc"):
                    numero = int(libelle.split()[-1])
                    return resultat_api(
                        "\n".join(f"Ligne {i} du bloc {numero}." for i in range(1, 11))
                    )

                gauche, droite = extraire_extraits_du_message(kwargs["message"])
                return resultat_api(
                    reponse_raccord(gauche, droite), config.MODEL_RACCORD
                )

            self.executer(effet)

        contenu = io.lire_texte(self.chemins.raccord_txt(1))

        for i in range(1, 11):
            with self.subTest(ligne=i):
                self.assertIn(f"Ligne {i} du bloc 1.", contenu)

    def test_un_seul_bloc_ne_declenche_aucun_raccord(self):
        io.ecrire_texte_atomique(self.chemins.ocr, fabriquer_ocr(1))

        resultats, appel = self.executer()

        self.assertEqual(resultats[0].raccords.total, 0)
        self.assertEqual(appel.call_count, 1)


# ============================================================
# 4. ASSEMBLAGE
# ============================================================


class TestAssemblage(BaseEdition):
    PAGES = 4

    def test_edit_assemble_depuis_les_raccords(self):
        """
        Assembler depuis `_EDIT_blocs/` présenterait les mots coupés et les
        doublons que la passe 2b vient de résoudre.
        """
        self.executer()

        # On distingue les deux sources pour vérifier laquelle est retenue.
        io.ecrire_texte_atomique(self.chemins.bloc_txt(1), "VERSION SANS RACCORD\n")
        io.ecrire_texte_atomique(self.chemins.raccord_txt(1), "VERSION RACCORDEE\n")

        contenu = edition.assembler_edit(self.chemins, self.nombre_blocs)

        self.assertIn("VERSION RACCORDEE", contenu)
        self.assertNotIn("SANS RACCORD", contenu)

    def test_bloc_manquant_laisse_un_trou_visible(self):
        self.executer()
        self.chemins.raccord_txt(1).unlink()

        contenu = edition.assembler_edit(self.chemins, self.nombre_blocs)

        self.assertIn(config.MARQUEUR_ECHEC_BLOC.format(numero=1), contenu)

    def test_edit_termine_par_un_seul_saut_de_ligne(self):
        self.executer()

        contenu = io.lire_texte(self.chemins.edit)

        self.assertTrue(contenu.endswith("\n"))
        self.assertFalse(contenu.endswith("\n\n"))

    def test_edit_relisible_par_l_etape_4(self):
        """
        Contrat entre les étapes 2 et 4 : ce qu'écrit l'édition, la
        classification structurelle doit savoir l'interpréter.
        """
        self.executer()

        texte = io.lire_texte(self.chemins.edit)
        index = blocks.construire_index_structure(texte)

        self.assertGreater(index.compter(blocks.TypeLigne.PERSONNAGE), 0)


# ============================================================
# 5. REPRISE APRÈS INTERRUPTION
# ============================================================


class TestReprise(BaseEdition):
    PAGES = 4

    def test_seconde_execution_n_appelle_plus_rien(self):
        self.executer()
        resultats, appel = self.executer()

        self.assertEqual(appel.call_count, 0)
        self.assertEqual(resultats[0].blocs.sautees, self.nombre_blocs)
        self.assertEqual(resultats[0].raccords.sautees, self.nombre_blocs - 1)

    def test_reprise_ne_refait_que_le_bloc_manquant(self):
        def effet(**kwargs):
            if kwargs["libelle"] == "bloc 1":
                raise api.EchecAppelAPI("panne simulée")
            return BaseEdition.effet_par_defaut(**kwargs)

        self.executer(effet)

        _, appel = self.executer()

        libelles = [c.kwargs["libelle"] for c in appel.call_args_list]

        self.assertIn("bloc 1", libelles)
        self.assertNotIn("bloc 2", libelles)

    def test_txt_orphelin_est_reecrit(self):
        """Coupure entre l'écriture du bloc et celle de son sidecar."""
        io.ecrire_texte_atomique(self.chemins.bloc_txt(1), "édition partielle")

        self.executer()

        self.assertNotIn("partielle", io.lire_texte(self.chemins.bloc_txt(1)))

    def test_raccord_rejoue_est_sans_effet(self):
        """
        Propriété d'idempotence exigée du prompt de raccord : une coupure entre
        l'écriture des deux blocs et celle du sidecar fait refaire la jonction
        sur un texte déjà raccordé, ce qui doit être neutre.
        """
        self.executer()

        avant = io.lire_texte(self.chemins.raccord_txt(1))

        # On efface le sidecar de la jonction 1 : elle sera refaite.
        self.chemins.raccord_json(1).unlink()
        _, appel = self.executer()

        self.assertEqual(appel.call_count, 1)
        self.assertEqual(io.lire_texte(self.chemins.raccord_txt(1)), avant)

    def test_frontieres_changees_forcent_la_reedition(self):
        """
        Régression, et perte de données silencieuse.

        Un essai limité à 10 pages produit un « bloc 2 » couvrant les pages 9
        et 10. Le passage complet du même livre attend un bloc 2 couvrant les
        pages 9 à 16. Le numéro seul n'identifie donc pas un bloc.

        Sans ce contrôle, le bloc de l'essai était tenu pour terminé et sauté,
        et les pages 11 à 16 disparaissaient d'EDIT.txt sans aucune alerte.
        """
        liste = blocks.former_blocs(
            blocks.decouper_en_pages(io.lire_texte(self.chemins.ocr)),
            self.PAGES_PAR_BLOC,
        )
        bloc = liste[0]

        io.ecrire_texte_atomique(self.chemins.bloc_txt(bloc.numero), "ancien")
        io.ecrire_sidecar(
            self.chemins.bloc_json(bloc.numero),
            {
                "statut": config.STATUT_TERMINE,
                # Frontières d'un essai plus court.
                "page_debut": bloc.page_debut,
                "page_fin": bloc.page_fin - 1,
            },
        )

        self.assertFalse(edition.bloc_deja_edite(bloc, self.chemins))

    def test_memes_frontieres_permettent_de_sauter(self):
        """Contrepartie : sans changement, le bloc ne doit pas être repayé."""
        liste = blocks.former_blocs(
            blocks.decouper_en_pages(io.lire_texte(self.chemins.ocr)),
            self.PAGES_PAR_BLOC,
        )
        bloc = liste[0]

        io.ecrire_sidecar(
            self.chemins.bloc_json(bloc.numero),
            {
                "statut": config.STATUT_TERMINE,
                "page_debut": bloc.page_debut,
                "page_fin": bloc.page_fin,
            },
        )

        self.assertTrue(edition.bloc_deja_edite(bloc, self.chemins))

    def test_bloc_reedite_perime_ses_raccords(self):
        """
        Second volet du même problème.

        `preparer_blocs_raccords()` ne recopie jamais par-dessus un fichier
        existant — à raison. Mais si le bloc source vient d'être réédité, sa
        copie dans `_EDIT_raccords/` est périmée, et l'ancienne version se
        retrouverait dans EDIT.txt.
        """
        self.executer()

        # On périme le bloc 2 : frontières incohérentes.
        sidecar = io.lire_sidecar(self.chemins.bloc_json(2))
        sidecar["page_fin"] = sidecar["page_fin"] - 1
        io.ecrire_sidecar(self.chemins.bloc_json(2), sidecar)

        io.ecrire_texte_atomique(self.chemins.raccord_txt(2), "VERSION PERIMEE\n")

        self.executer()

        contenu = io.lire_texte(self.chemins.raccord_txt(2))

        self.assertNotIn("PERIMEE", contenu)
        self.assertNotIn("PERIMEE", io.lire_texte(self.chemins.edit))

    def test_invalidation_cible_les_deux_jonctions_voisines(self):
        """La jonction N relie les blocs N et N+1 : le bloc N touche N-1 et N."""
        # Trois blocs sont nécessaires pour que deux jonctions existent :
        # la classe de base n'en produit que deux.
        io.ecrire_texte_atomique(self.chemins.ocr, fabriquer_ocr(6))

        self.executer()

        for numero in (1, 2):
            self.assertTrue(self.chemins.raccord_json(numero).exists())

        edition.invalider_raccords_voisins(self.chemins, 2)

        self.assertFalse(self.chemins.raccord_txt(2).exists())
        self.assertFalse(self.chemins.raccord_json(1).exists())
        self.assertFalse(self.chemins.raccord_json(2).exists())

    def test_invalidation_du_premier_bloc_ne_cherche_pas_de_jonction_zero(self):
        self.executer()

        edition.invalider_raccords_voisins(self.chemins, 1)

        self.assertFalse(self.chemins.raccord_txt(1).exists())
        self.assertFalse(self.chemins.raccord_json(1).exists())

    def test_bloc_en_echec_n_ecrit_pas_de_txt(self):
        def effet(**kwargs):
            if kwargs["libelle"] == "bloc 1":
                raise api.EchecAppelAPI("panne simulée")
            return BaseEdition.effet_par_defaut(**kwargs)

        self.executer(effet)

        self.assertFalse(self.chemins.bloc_txt(1).exists())
        self.assertFalse(io.unite_terminee(self.chemins.bloc_json(1)))

    def test_jonction_reportee_si_un_bloc_voisin_manque(self):
        def effet(**kwargs):
            if kwargs["libelle"] == "bloc 1":
                raise api.EchecAppelAPI("panne simulée")
            return BaseEdition.effet_par_defaut(**kwargs)

        resultats, _ = self.executer(effet)

        # La jonction 1 ne peut pas être traitée, mais l'étape continue.
        self.assertEqual(resultats[0].raccords.echouees, 1)
        self.assertTrue(self.chemins.edit.exists())


# ============================================================
# 6. JOURNAL
# ============================================================


class TestJournal(BaseEdition):
    PAGES = 4

    def test_journal_distingue_blocs_et_raccords(self):
        self.executer()

        journal = io.lire_sidecar(io.dossier_temporaire(self.base) / "journal_edition.json")
        unites = {appel["unite"] for appel in journal["appels"]}

        self.assertEqual(unites, {"bloc", "raccord"})

    def test_configuration_des_deux_modeles_consignee(self):
        self.executer()

        configuration = io.lire_sidecar(io.dossier_temporaire(self.base) / "journal_edition.json")["configuration"]

        self.assertEqual(configuration["modele_edition"], config.MODEL_EDITION)
        self.assertEqual(configuration["modele_raccord"], config.MODEL_RACCORD)

    def test_bilan_du_livre_journalise(self):
        self.executer()

        bilan = io.lire_sidecar(io.dossier_temporaire(self.base) / "journal_edition.json")["livres"]["Le Malentendu"]

        self.assertEqual(bilan["statut"], config.STATUT_TERMINE)
        self.assertEqual(bilan["blocs"]["total"], self.nombre_blocs)
        self.assertEqual(bilan["raccords"]["total"], self.nombre_blocs - 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
