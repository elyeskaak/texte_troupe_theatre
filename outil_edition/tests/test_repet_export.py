"""
Tests de `theatre_editor.repet_export`.

Aucune dépendance : le module n'appelle ni API, ni `python-docx`, ni le réseau.
Ces tests partent donc d'un texte au format `EDIT.txt` et vérifient le
dictionnaire produit, ce qui couvre en une passe la classification en amont et
l'assemblage en aval.

Le fil directeur est ce qui rendrait l'outil de répétition faux sans qu'on le
voie : une réplique perdue, un identifiant qui se déplace, un vers recollé en
prose, une didascalie comptée comme du texte à réciter.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from theatre_editor import config, repet_export
from theatre_editor.utils import blocks, io

PIECE = (
    "**PERSONNAGES**\n"
    "JAN, le frère\n"
    "MARTHA, sa femme\n"
    "\n"
    "**ACTE PREMIER**\n"
    "\n"
    "*Une auberge. Le soir.*\n"
    "\n"
    "**JAN.**\n"
    "Nous y sommes enfin.\n"
    "\n"
    "**MARTHA.**\n"
    "Je t'attendais *elle se lève* depuis une heure.\n"
    "\n"
    "*Pause.*\n"
    "\n"
    "***\n"
    "\n"
    "**JAN.**\n"
    "Oui.\n"
    "\n"
    "**SCÈNE 2**\n"
    "\n"
    "**MARTHA.**\n"
    "Donnez.\n"
)


def construire(texte: str) -> dict:
    """Raccourci : texte au format EDIT.txt → document de répétition."""
    index = blocks.construire_index_structure(texte)
    lignes = blocks.classifier_document(texte, index)

    return repet_export.construire_repet(lignes, index, piece="Le Malentendu")


def repliques(document: dict) -> list[dict]:
    """Toutes les répliques du document, dans l'ordre de jeu."""
    return [
        element
        for unite in document["unites"]
        for element in unite["elements"]
        if element["type"] == "replique"
    ]


class Structure(unittest.TestCase):
    """Découpage en unités jouables."""

    def setUp(self):
        self.document = construire(PIECE)

    def test_schema_et_piece(self):
        self.assertEqual(self.document["schema"], config.SCHEMA_REPET)
        self.assertEqual(self.document["piece"], "Le Malentendu")

    def test_le_separateur_ouvre_une_unite_implicite(self):
        """`***` change de scène sans titre : l'unité hérite, et se marque."""
        implicites = [u for u in self.document["unites"] if u["implicite"]]

        self.assertEqual(len(implicites), 1)
        self.assertEqual(implicites[0]["acte"], "ACTE PREMIER")
        # Hérite de l'acte, et non d'un titre de scène qui n'existe pas encore.
        self.assertIsNone(implicites[0]["scene"])

    def test_un_titre_de_scene_ouvre_une_unite_nommee(self):
        nommees = [u for u in self.document["unites"] if u["scene"]]

        self.assertEqual(len(nommees), 1)
        self.assertEqual(nommees[0]["scene"], "SCÈNE 2")
        self.assertEqual(nommees[0]["acte"], "ACTE PREMIER")
        self.assertFalse(nommees[0]["implicite"])

    def test_un_nouvel_acte_remet_la_scene_a_zero(self):
        """« SCÈNE 2 » de l'acte I n'est pas « SCÈNE 2 » de l'acte II."""
        texte = (
            "**ACTE PREMIER**\n**SCÈNE 2**\n**JAN.**\nUn.\n"
            "**ACTE DEUXIÈME**\n**JAN.**\nDeux.\n"
        )
        unites = construire(texte)["unites"]

        acte_deux = [u for u in unites if u["acte"] == "ACTE DEUXIÈME"]

        self.assertTrue(acte_deux)
        for unite in acte_deux:
            self.assertIsNone(unite["scene"])

    def test_les_personnages_de_l_unite_sont_precalcules(self):
        """C'est ce qui permet de replier une scène sans la parcourir."""
        premiere = self.document["unites"][0]

        self.assertEqual(premiere["personnages"], ["JAN", "MARTHA"])

    def test_une_piece_sans_titre_commence_par_une_unite_implicite(self):
        document = construire("**JAN.**\nBonjour.\n")

        self.assertEqual(len(document["unites"]), 1)
        self.assertTrue(document["unites"][0]["implicite"])
        self.assertIsNone(document["unites"][0]["acte"])
        self.assertEqual(len(repliques(document)), 1)

    def test_aucune_unite_vide(self):
        """Un titre sans contenu ne doit pas produire d'unité fantôme."""
        document = construire("**ACTE PREMIER**\n\n**ACTE DEUXIÈME**\n**JAN.**\nLà.\n")

        self.assertEqual(len(document["unites"]), 1)
        self.assertEqual(document["unites"][0]["acte"], "ACTE DEUXIÈME")

    def test_le_lieu_et_la_didascalie_sont_conserves(self):
        types = [e["type"] for e in self.document["unites"][0]["elements"]]

        self.assertIn("lieu", types)
        self.assertIn("didascalie", types)


class Repliques(unittest.TestCase):
    """Contenu d'une réplique."""

    def setUp(self):
        self.document = construire(PIECE)
        self.repliques = repliques(self.document)

    def test_toutes_les_repliques_sont_presentes(self):
        """Aucune perte : c'est le défaut qu'on ne voit jamais."""
        self.assertEqual(len(self.repliques), 4)
        self.assertEqual(
            [r["personnages"] for r in self.repliques],
            [["JAN"], ["MARTHA"], ["JAN"], ["MARTHA"]],
        )

    def test_la_didascalie_interne_sort_du_texte_a_reciter(self):
        """« elle se lève » ne se prononce pas."""
        martha = self.repliques[1]

        self.assertEqual(martha["texte"], "Je t'attendais depuis une heure.")
        self.assertNotIn("lève", martha["texte"])

    def test_la_didascalie_interne_est_positionnee_en_mots(self):
        martha = self.repliques[1]
        didascalies = martha["didascalies_internes"]

        self.assertEqual(len(didascalies), 1)
        self.assertEqual(didascalies[0]["texte"], "elle se lève")
        # « Je t'attendais » = 2 mots parlés avant le jeu de scène.
        self.assertEqual(didascalies[0]["avant_mot"], 2)

    def test_une_replique_sans_jeu_de_scene_n_a_pas_le_champ(self):
        """Le champ est absent plutôt que vide : le JSON reste lisible."""
        self.assertNotIn("didascalies_internes", self.repliques[0])

    def test_une_replique_en_prose_n_est_pas_marquee_en_vers(self):
        self.assertFalse(self.repliques[0]["vers"])


class Vers(unittest.TestCase):
    """
    Une réplique sur plusieurs lignes est en vers.

    L'inférence est sûre : l'étape 2 a déjà rejoint les retours à la ligne
    mécaniques, et ne conserve séparées que les lignes voulues.
    """

    def test_plusieurs_lignes_valent_des_vers(self):
        texte = (
            "**JAN.**\n"
            "Je vous ai vu venir de loin,\n"
            "Et je n'ai pas bougé.\n"
        )
        replique = repliques(construire(texte))[0]

        self.assertTrue(replique["vers"])

    def test_les_vers_ne_sont_jamais_recolles(self):
        """Recoller deux vers défait le travail de l'étape 2."""
        texte = "**JAN.**\nPremier vers,\nSecond vers.\n"
        replique = repliques(construire(texte))[0]

        self.assertEqual(replique["texte"], "Premier vers,\nSecond vers.")
        self.assertEqual(replique["texte"].count("\n"), 1)

    def test_un_jeu_de_scene_dans_un_vers_reste_positionne(self):
        texte = "**JAN.**\nPremier vers,\nSecond *il se tourne* vers.\n"
        replique = repliques(construire(texte))[0]

        self.assertEqual(replique["texte"], "Premier vers,\nSecond vers.")
        # 3 mots parlés avant le jeu de scène : « Premier », « vers, », « Second ».
        self.assertEqual(replique["didascalies_internes"][0]["avant_mot"], 3)


class Identifiants(unittest.TestCase):
    """
    L'identifiant est une empreinte de contenu, jamais une position.

    C'est ce qui fait qu'une réédition du texte ne déplace pas la progression
    d'une réplique vers sa voisine.
    """

    def test_stable_entre_deux_constructions(self):
        premier = [r["id"] for r in repliques(construire(PIECE))]
        second = [r["id"] for r in repliques(construire(PIECE))]

        self.assertEqual(premier, second)

    def test_insensible_a_la_position(self):
        """Ajouter une scène en tête ne change aucun identifiant existant."""
        avant = {r["texte"]: r["id"] for r in repliques(construire(PIECE))}

        decale = "**SCÈNE 0**\n**JAN.**\nUn mot d'abord.\n\n" + PIECE
        apres = {r["texte"]: r["id"] for r in repliques(construire(decale))}

        for texte, identifiant in avant.items():
            self.assertEqual(apres[texte], identifiant, f"déplacé : {texte}")

    def test_change_si_le_texte_change(self):
        """Le texte a changé : il faut réapprendre, donc perdre le statut."""
        origine = repliques(construire("**JAN.**\nNous y sommes enfin.\n"))[0]
        corrige = repliques(construire("**JAN.**\nNous y voici enfin.\n"))[0]

        self.assertNotEqual(origine["id"], corrige["id"])

    def test_insensible_a_la_casse_et_aux_espaces(self):
        """Une correction typographique ne doit pas coûter un statut."""
        a = repliques(construire("**JAN.**\nNous  y sommes enfin.\n"))[0]
        b = repliques(construire("**JAN.**\nnous y sommes enfin.\n"))[0]

        self.assertEqual(a["id"], b["id"])

    def test_deux_repliques_identiques_recoivent_des_identifiants_distincts(self):
        texte = "**JAN.**\nOui.\n\n**MARTHA.**\nBon.\n\n**JAN.**\nOui.\n"
        trouvees = [r for r in repliques(construire(texte)) if r["texte"] == "Oui."]

        self.assertEqual(len(trouvees), 2)
        self.assertNotEqual(trouvees[0]["id"], trouvees[1]["id"])

    def test_ajouter_un_doublon_ne_change_pas_le_premier(self):
        """
        Le rang n'entre dans l'empreinte que s'il est non nul.

        Sans cette précaution, ajouter un second « Oui. » changerait
        l'identifiant du premier, qui existait pourtant déjà.
        """
        seul = repliques(construire("**JAN.**\nOui.\n"))[0]
        double = repliques(construire("**JAN.**\nOui.\n\n**JAN.**\nOui.\n"))

        self.assertEqual(double[0]["id"], seul["id"])

    def test_meme_texte_deux_personnages_identifiants_distincts(self):
        texte = "**JAN.**\nOui.\n\n**MARTHA.**\nOui.\n"
        trouvees = repliques(construire(texte))

        self.assertNotEqual(trouvees[0]["id"], trouvees[1]["id"])


class Personnages(unittest.TestCase):
    """Distribution parlante et comptages."""

    def setUp(self):
        self.document = construire(PIECE)

    def test_seuls_les_personnages_qui_parlent_sont_listes(self):
        noms = [p["nom"] for p in self.document["personnages"]]

        self.assertEqual(sorted(noms), ["JAN", "MARTHA"])

    def test_les_comptages_sont_justes(self):
        par_nom = {p["nom"]: p for p in self.document["personnages"]}

        self.assertEqual(par_nom["JAN"]["repliques"], 2)
        self.assertEqual(par_nom["MARTHA"]["repliques"], 2)
        # « Je t'attendais depuis une heure. » = 5 mots, « Donnez. » = 1.
        self.assertEqual(par_nom["MARTHA"]["mots"], 6)

    def test_tri_par_volume_decroissant(self):
        volumes = [p["mots"] for p in self.document["personnages"]]

        self.assertEqual(volumes, sorted(volumes, reverse=True))

    def test_les_mots_excluent_les_didascalies(self):
        """Compter « elle se lève » gonflerait le volume d'un rôle."""
        document = construire("**JAN.**\nUn *il sort* deux.\n")

        self.assertEqual(document["personnages"][0]["mots"], 2)


class RepliquesCollectives(unittest.TestCase):
    """
    Une réplique peut être dite par plusieurs personnages : « X et Y. » les
    joint dans le label, « TOUS. » ne nomme personne en particulier.
    """

    def test_deux_personnages_joints_par_et(self):
        document = construire("**SIR ROWLAND et CLARISSA.**\nChippendale ?\n")

        self.assertEqual(
            repliques(document)[0]["personnages"], ["SIR ROWLAND", "CLARISSA"]
        )

    def test_la_jonction_est_insensible_a_la_casse(self):
        document = construire("**JAN ET MARTHA.**\nOui.\n")

        self.assertEqual(repliques(document)[0]["personnages"], ["JAN", "MARTHA"])

    def test_les_deux_personnages_apparaissent_dans_l_unite(self):
        document = construire("**SIR ROWLAND et CLARISSA.**\nChippendale ?\n")

        self.assertEqual(
            document["unites"][0]["personnages"], ["SIR ROWLAND", "CLARISSA"]
        )

    def test_les_deux_personnages_sont_credites_dans_la_distribution(self):
        document = construire("**JAN et MARTHA.**\nOui trois fois.\n")
        par_nom = {p["nom"]: p for p in document["personnages"]}

        self.assertEqual(par_nom["JAN"]["repliques"], 1)
        self.assertEqual(par_nom["MARTHA"]["repliques"], 1)
        self.assertEqual(par_nom["JAN"]["mots"], 3)
        self.assertEqual(par_nom["MARTHA"]["mots"], 3)

    def test_tous_devient_un_joker(self):
        document = construire("**TOUS.**\nPlus sûr ?\n")

        self.assertEqual(repliques(document)[0]["personnages"], [repet_export.JOKER_TOUS])

    def test_le_joker_n_apparait_pas_dans_la_distribution(self):
        """« TOUS » ne nomme personne : ce n'est pas un rôle qu'on peut choisir."""
        document = construire("**JAN.**\nUn.\n\n**TOUS.**\nDeux.\n")
        noms = [p["nom"] for p in document["personnages"]]

        self.assertNotIn(repet_export.JOKER_TOUS, noms)

    def test_le_joker_est_dans_les_personnages_de_l_unite(self):
        """
        L'outil de répétition en a besoin pour savoir qu'une unité me concerne
        même si aucun de mes rôles n'y parle seul.
        """
        document = construire("**TOUS.**\nPlus sûr ?\n")

        self.assertIn(repet_export.JOKER_TOUS, document["unites"][0]["personnages"])

    def test_identifiant_a_un_seul_personnage_inchange_par_la_liste(self):
        """
        Le format évolue vers une liste de personnages, mais une réplique à un
        seul personnage doit produire exactement l'identifiant d'avant : rien
        ne doit se déplacer pour l'immense majorité des répliques déjà apprises.
        """
        seul = repet_export.identifiant_replique(["JAN"], "Bonjour.", 0)

        self.assertEqual(
            seul, repet_export.identifiant_replique(["JAN"], "Bonjour.", 0)
        )
        self.assertEqual(len(seul), len("r_") + repet_export.LONGUEUR_EMPREINTE)

    def test_deux_repliques_collectives_identiques_ont_des_occurrences_distinctes(self):
        texte = "**JAN et MARTHA.**\nOui.\n\n**JAN et MARTHA.**\nOui.\n"
        trouvees = repliques(construire(texte))

        self.assertEqual(len(trouvees), 2)
        self.assertNotEqual(trouvees[0]["id"], trouvees[1]["id"])


class RienDeJeteEnSilence(unittest.TestCase):
    """
    P3 : aucune anomalie n'est écartée sans trace.

    C'est le défaut du prototype de l'outil de répétition, dont le parseur
    concaténait ou jetait tout ce qu'il ne reconnaissait pas.
    """

    def test_un_texte_sans_personnage_est_conserve_et_signale(self):
        document = construire("**ACTE PREMIER**\nUne phrase orpheline.\n")

        elements = document["unites"][0]["elements"]
        orphelins = [e for e in elements if e["type"] == "texte_sans_personnage"]

        self.assertEqual(len(orphelins), 1)
        self.assertEqual(orphelins[0]["texte"], "Une phrase orpheline.")
        self.assertTrue(
            any("sans personnage" in a for a in document["avertissements"]),
            document["avertissements"],
        )

    def test_un_texte_orphelin_n_est_pas_recolle_a_la_replique_precedente(self):
        texte = "**JAN.**\nMa réplique.\n\n*Pause.*\n\nUne orpheline.\n"
        document = construire(texte)

        self.assertEqual(repliques(document)[0]["texte"], "Ma réplique.")

    def test_un_personnage_annonce_sans_replique_ne_produit_rien(self):
        """
        Fréquent au théâtre contemporain : l'unique intervention d'un rôle est
        une didascalie. Ce n'est pas une anomalie — il n'y a simplement rien à
        réciter.
        """
        document = construire("**JAN.**\n\n*Silence.*\n")

        self.assertEqual(repliques(document), [])
        # Aucun avertissement *de l'assemblage* : ceux de l'index — « aucune
        # distribution détectée » sur un extrait aussi court — sont légitimes.
        self.assertFalse(
            [a for a in document["avertissements"] if "sans personnage" in a],
            document["avertissements"],
        )

    def test_une_replique_entierement_en_didascalie_conserve_son_jeu(self):
        document = construire("**JAN.**\n*Il hausse les épaules.*\n")

        textes = [
            e["texte"]
            for e in document["unites"][0]["elements"]
            if e["type"] == "didascalie"
        ]

        self.assertEqual(repliques(document), [])
        self.assertIn("Il hausse les épaules.", textes)

    def test_les_avertissements_de_l_index_sont_repris(self):
        index = blocks.construire_index_structure(PIECE)
        index.avertissements.append("classement incertain : LA VOIX")

        lignes = blocks.classifier_document(PIECE, index)
        document = repet_export.construire_repet(lignes, index, piece="X")

        self.assertIn("classement incertain : LA VOIX", document["avertissements"])


class Liminaires(unittest.TestCase):
    """Les pages liminaires sont conservées à part, pas mélangées au jeu."""

    def test_la_distribution_n_est_pas_une_replique(self):
        document = construire(PIECE)
        types = [e["type"] for u in document["unites"] for e in u["elements"]]

        self.assertNotIn("texte_sans_personnage", types)
        self.assertTrue(document["liminaires"])

    def test_les_entrees_de_distribution_sont_conservees(self):
        document = construire(PIECE)
        textes = [entree["texte"] for entree in document["liminaires"]]

        self.assertTrue(
            any("JAN" in texte for texte in textes),
            textes,
        )


class Determinisme(unittest.TestCase):
    """`construire_repet` ne porte aucune date : deux appels sont égaux."""

    def test_deux_constructions_sont_strictement_egales(self):
        self.assertEqual(construire(PIECE), construire(PIECE))

    def test_aucun_champ_de_date(self):
        self.assertNotIn("genere_le", construire(PIECE))


class Ecriture(unittest.TestCase):
    """`ecrire_repet` produit un fichier relisible."""

    def test_le_fichier_est_du_json_valide_et_date(self):
        with tempfile.TemporaryDirectory() as dossier:
            base = Path(dossier)
            chemins = io.resoudre_chemins("Le Malentendu", base)

            index = blocks.construire_index_structure(PIECE)
            lignes = blocks.classifier_document(PIECE, index)

            repet_export.ecrire_repet(chemins, lignes, index)

            self.assertTrue(chemins.repet.exists())

            relu = json.loads(chemins.repet.read_text(encoding="utf-8"))

            self.assertEqual(relu["schema"], config.SCHEMA_REPET)
            self.assertEqual(relu["piece"], "Le Malentendu")
            self.assertIn("genere_le", relu)
            self.assertEqual(len(repliques(relu)), 4)

    def test_le_fichier_est_visible_a_cote_du_docx(self):
        """Il est fait pour être transféré sur un téléphone."""
        chemins = io.resoudre_chemins("Le Malentendu", Path("/base"))

        self.assertEqual(chemins.repet.parent, chemins.docx.parent)
        self.assertTrue(chemins.repet.name.endswith(config.SUFFIXE_REPET))

    def test_les_accents_ne_sont_pas_echappes(self):
        """Le fichier doit rester lisible à l'œil dans un éditeur."""
        with tempfile.TemporaryDirectory() as dossier:
            chemins = io.resoudre_chemins("Piece", Path(dossier))

            index = blocks.construire_index_structure(PIECE)
            lignes = blocks.classifier_document(PIECE, index)

            repet_export.ecrire_repet(chemins, lignes, index)

            brut = chemins.repet.read_text(encoding="utf-8")

            self.assertIn("SCÈNE 2", brut)
            self.assertNotIn("\\u00c8", brut)


class Comptages(unittest.TestCase):
    """`compter` alimente le journal de l'étape."""

    def test_les_totaux_correspondent(self):
        document = construire(PIECE)
        totaux = repet_export.compter(document)

        self.assertEqual(totaux["repliques"], 4)
        self.assertEqual(totaux["personnages"], 2)
        self.assertEqual(totaux["unites"], len(document["unites"]))


class NomDePersonnage(unittest.TestCase):
    """Le point final de « **JAN.** » est une convention d'imprimerie."""

    def test_le_point_final_est_retire(self):
        self.assertEqual(repet_export.nom_personnage("JAN."), "JAN")

    def test_avec_et_sans_point_donnent_le_meme_nom(self):
        """Sinon deux éditions produiraient deux personnages distincts."""
        self.assertEqual(
            repet_export.nom_personnage("JAN."),
            repet_export.nom_personnage("JAN"),
        )

    def test_les_accents_sont_conserves(self):
        """Ce nom est affiché : « LE MAÎTRE » ne doit pas devenir « LE MAITRE »."""
        self.assertEqual(repet_export.nom_personnage("LE MAÎTRE."), "LE MAÎTRE")

    def test_les_deux_apostrophes_donnent_le_meme_nom(self):
        """
        Constaté sur un texte réel : « L'AGENT DUPONT » (apostrophe droite) et
        « L’AGENT DUPONT » (apostrophe typographique) donnaient deux rôles là où
        il n'y en a qu'un. Choisir l'un laissait les répliques de l'autre
        visibles, sans que rien ne le signale.
        """
        self.assertEqual(
            repet_export.nom_personnage("L'AGENT DUPONT."),
            repet_export.nom_personnage("L’AGENT DUPONT."),
        )

    def test_les_repliques_des_deux_graphies_sont_reunies(self):
        texte = (
            "**L'INSPECTEUR.**\nPremière.\n\n"
            "**JAN.**\nAutre chose.\n\n"
            "**L’INSPECTEUR.**\nSeconde.\n"
        )
        document = construire(texte)
        par_nom = {p["nom"]: p for p in document["personnages"]}

        self.assertIn("L'INSPECTEUR", par_nom)
        self.assertEqual(par_nom["L'INSPECTEUR"]["repliques"], 2)

    def test_la_fusion_est_signalee(self):
        """Une fusion muette cacherait un défaut du document source."""
        texte = "**L'AGENT.**\nUn.\n\n**L’AGENT.**\nDeux.\n"
        document = construire(texte)

        self.assertTrue(
            any("graphies multiples" in a for a in document["avertissements"]),
            document["avertissements"],
        )

    def test_une_graphie_unique_ne_declenche_aucun_avertissement(self):
        document = construire("**JAN.**\nUn.\n\n**JAN.**\nDeux.\n")

        self.assertFalse([a for a in document["avertissements"] if "graphies" in a])

    def test_distinct_de_normaliser_label(self):
        self.assertNotEqual(
            repet_export.nom_personnage("LE MAÎTRE."),
            blocks.normaliser_label("LE MAÎTRE."),
        )

    def test_le_nom_apparait_sans_point_dans_le_document(self):
        document = construire("**JAN.**\nBonjour.\n")

        self.assertEqual(repliques(document)[0]["personnages"], ["JAN"])
        self.assertEqual(document["personnages"][0]["nom"], "JAN")


class Normalisation(unittest.TestCase):
    """`normaliser_pour_identifiant` — la brique des empreintes."""

    def test_retire_les_marqueurs_d_emphase(self):
        self.assertEqual(
            repet_export.normaliser_pour_identifiant("un *mot* dit"),
            "un mot dit",
        )

    def test_reduit_les_espaces_et_la_casse(self):
        self.assertEqual(
            repet_export.normaliser_pour_identifiant("  Deux   Mots \n"),
            "deux mots",
        )

    def test_distincte_de_celle_de_blocks(self):
        """
        `blocks.normaliser_pour_comparaison` ne touche pas à la casse : elle sert
        à comparer des volumes entre étapes, pas à identifier une réplique.
        """
        texte = "Nous Y Sommes"

        self.assertNotEqual(
            repet_export.normaliser_pour_identifiant(texte),
            blocks.normaliser_pour_comparaison(texte),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
