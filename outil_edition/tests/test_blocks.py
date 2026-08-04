"""
Tests de `theatre_editor.utils.blocks`.

Exécution, depuis la racine du projet :

    python -m unittest discover -s tests -t .

`unittest` de la bibliothèque standard est utilisé volontairement : ces tests
doivent pouvoir tourner sur une machine nue, sans clé API, sans Google Drive
monté et sans aucune dépendance installée. C'est ce qui permet de valider la
logique la plus délicate du projet avant le premier appel API facturé.
"""

from __future__ import annotations

import unittest

from theatre_editor import config
from theatre_editor.utils.blocks import (
    Confiance,
    Run,
    TypeLigne,
    assembler,
    classifier_document,
    construire_index_structure,
    contenu_gras,
    contenu_italique,
    decouper_en_pages,
    decouper_en_runs,
    dedoubler_replique_en_ligne,
    est_jeton_numerotation,
    est_ligne_de_replique,
    est_separateur,
    fenetre_debut,
    fenetre_fin,
    former_blocs,
    nettoyer_enveloppe,
    normaliser_label,
    normaliser_pour_comptage,
    rapport_classification,
    recenser_personnages,
    style_numerotation,
    valeur_numerotation,
    verifier_sortie,
)


# ============================================================
# 1. DÉCOUPAGE EN PAGES ET EN BLOCS
# ============================================================


class TestDecoupagePages(unittest.TestCase):
    """Les trois stratégies de découpage, par ordre de priorité."""

    def test_decoupe_sur_separateur_de_page(self):
        texte = "[PAGE 1]\nAlpha\n\n<<<PAGE_BREAK>>>\n\n[PAGE 2]\nBeta"

        pages = decouper_en_pages(texte)

        self.assertEqual(len(pages), 2)
        self.assertTrue(pages[0].startswith("[PAGE 1]"))
        self.assertIn("Beta", pages[1])

    def test_repli_sur_marqueurs_de_page(self):
        """Sans séparateur, les marqueurs [PAGE X] restent exploitables."""
        texte = "[PAGE 1]\nAlpha\n[PAGE 2]\nBeta\n[PAGE 3]\nGamma"

        pages = decouper_en_pages(texte)

        self.assertEqual(len(pages), 3)
        self.assertIn("Gamma", pages[2])

    def test_texte_sans_marqueur_forme_une_page(self):
        pages = decouper_en_pages("Un texte sans le moindre marqueur.")

        self.assertEqual(len(pages), 1)

    def test_pages_vides_ignorees(self):
        texte = "[PAGE 1]\nAlpha\n\n<<<PAGE_BREAK>>>\n\n\n\n<<<PAGE_BREAK>>>\n\nBeta"

        self.assertEqual(len(decouper_en_pages(texte)), 2)

    def test_decoupage_est_deterministe(self):
        """La reprise après interruption dépend de cette propriété."""
        texte = "[PAGE 1]\nA\n\n<<<PAGE_BREAK>>>\n\n[PAGE 2]\nB"

        self.assertEqual(decouper_en_pages(texte), decouper_en_pages(texte))


class TestFormerBlocs(unittest.TestCase):
    def test_regroupe_et_numerote(self):
        pages = [f"page {i}" for i in range(1, 8)]

        blocs = former_blocs(pages, pages_par_bloc=3)

        self.assertEqual(len(blocs), 3)
        self.assertEqual((blocs[0].numero, blocs[0].page_debut, blocs[0].page_fin), (1, 1, 3))
        self.assertEqual((blocs[1].numero, blocs[1].page_debut, blocs[1].page_fin), (2, 4, 6))
        # Le dernier bloc est incomplet : 7 pages pour des blocs de 3.
        self.assertEqual((blocs[2].numero, blocs[2].page_debut, blocs[2].page_fin), (3, 7, 7))

    def test_contenu_joint_par_le_separateur(self):
        blocs = former_blocs(["A", "B"], pages_par_bloc=2)

        self.assertEqual(blocs[0].contenu, f"A{config.SEPARATEUR_PAGE}B")

    def test_aucune_page_donne_aucun_bloc(self):
        self.assertEqual(former_blocs([], pages_par_bloc=4), [])

    def test_taille_invalide_leve_une_erreur(self):
        """Une taille nulle produirait une boucle infinie."""
        with self.assertRaises(ValueError):
            former_blocs(["A"], pages_par_bloc=0)


# ============================================================
# 2. FENÊTRAGE POUR LA PASSE DE RACCORD
# ============================================================


class TestFenetrage(unittest.TestCase):
    def setUp(self):
        self.texte = "\n".join(f"ligne {i}" for i in range(1, 11))

    def test_fenetre_fin_isole_les_dernieres_lignes(self):
        prefixe, extrait = fenetre_fin(self.texte, 3)

        self.assertEqual(extrait.split("\n"), ["ligne 8", "ligne 9", "ligne 10"])
        self.assertTrue(prefixe.startswith("ligne 1"))

    def test_fenetre_debut_isole_les_premieres_lignes(self):
        extrait, suffixe = fenetre_debut(self.texte, 3)

        self.assertEqual(extrait.split("\n"), ["ligne 1", "ligne 2", "ligne 3"])
        self.assertTrue(suffixe.startswith("ligne 4"))

    def test_recollage_restitue_le_texte(self):
        """Propriété essentielle : le raccord ne doit rien perdre."""
        prefixe, extrait = fenetre_fin(self.texte, 4)
        self.assertEqual("\n".join(p for p in (prefixe, extrait) if p), self.texte)

        extrait, suffixe = fenetre_debut(self.texte, 4)
        self.assertEqual("\n".join(p for p in (extrait, suffixe) if p), self.texte)

    def test_fenetre_plus_grande_que_le_texte(self):
        prefixe, extrait = fenetre_fin("une ligne", 50)

        self.assertEqual(prefixe, "")
        self.assertEqual(extrait, "une ligne")


class TestAssembler(unittest.TestCase):
    def test_joint_par_ligne_vide_et_termine_par_un_saut(self):
        resultat = assembler(["Bloc A", "Bloc B"])

        self.assertEqual(resultat, "Bloc A\n\nBloc B\n")

    def test_ignore_les_blocs_vides(self):
        self.assertEqual(assembler(["A", "", "   ", "B"]), "A\n\nB\n")

    def test_liste_vide(self):
        self.assertEqual(assembler([]), "")


# ============================================================
# 3. NETTOYAGE ET CONTRÔLES DE SORTIE
# ============================================================


class TestNettoyageEnveloppe(unittest.TestCase):
    def test_retire_un_bloc_de_code(self):
        self.assertEqual(nettoyer_enveloppe("```markdown\nTexte\n```"), "Texte")

    def test_retire_les_delimiteurs_de_source(self):
        brut = f"{config.DELIM_SOURCE_DEBUT}\nTexte\n{config.DELIM_SOURCE_FIN}"

        self.assertEqual(nettoyer_enveloppe(brut), "Texte")

    def test_texte_propre_inchange(self):
        self.assertEqual(nettoyer_enveloppe("**JAN.**\nMort ?"), "**JAN.**\nMort ?")


class TestVerifierSortie(unittest.TestCase):
    def test_sortie_fidele_sans_avertissement(self):
        source = "[PAGE 1]\nBonjour Jean, comment allez-vous donc aujourd'hui ?"
        sortie = "Bonjour Jean, comment allez-vous donc aujourd'hui ?"

        self.assertEqual(verifier_sortie(source, sortie), [])

    def test_sortie_vide_signalee(self):
        self.assertEqual(verifier_sortie("du texte", "   "), ["sortie vide"])

    def test_troncature_detectee(self):
        source = "a" * 1000
        sortie = "a" * 300

        avertissements = verifier_sortie(source, sortie)

        self.assertTrue(any("trop courte" in a for a in avertissements))

    def test_marqueur_residuel_detecte(self):
        avertissements = verifier_sortie("texte", "texte\n<<<PAGE_BREAK>>>\nsuite")

        self.assertTrue(any("PAGE_BREAK" in a for a in avertissements))

    def test_bavardage_du_modele_detecte(self):
        avertissements = verifier_sortie("texte", "Voici le texte corrigé :\ntexte")

        self.assertTrue(avertissements)

    def test_replique_avec_je_ne_peux_pas_n_est_pas_signalee(self):
        """Régression : « je ne peux pas » est une réplique banale, pas un
        refus du modèle. La signaler marquait le bloc suspect, jusqu'à le
        faire disparaître d'EDIT.txt à l'assemblage."""
        source = "JAN Je ne peux pas te le dire maintenant."
        sortie = "**JAN.**\nJe ne peux pas te le dire maintenant."

        self.assertEqual(verifier_sortie(source, sortie), [])

    def test_asterisque_orpheline_detectee(self):
        """Une astérisque impaire casserait la convention, donc l'étape 4."""
        avertissements = verifier_sortie("texte", "**JAN.*\nMort ?")

        self.assertTrue(any("impair" in a for a in avertissements))

    def test_separateur_de_scene_ne_casse_pas_la_parite(self):
        """Régression : `***` porte trois astérisques (impair) mais est un
        séparateur légitime. Le compter marquait le bloc suspect et l'excluait
        d'EDIT.txt — bug révélé par un vrai appel d'édition sur *ADN*."""
        source = (
            "MARK\nIl faut qu'on vous parle.\nLÉA\nOh, merde.\n"
            "Un bois. Lou, John Tate et Danny.\nLOU\nC'est la merde."
        )
        sortie = (
            "**MARK.**\nIl faut qu'on vous parle.\n\n**LÉA.**\nOh, merde.\n\n"
            "***\n\n*Un bois. Lou, John Tate et Danny.*\n\n"
            "**LOU.**\nC'est la merde."
        )

        self.assertEqual(verifier_sortie(source, sortie), [])

    def test_asterisque_orpheline_detectee_malgre_un_separateur(self):
        """Exempter le séparateur ne doit pas masquer une vraie orpheline. Le
        bug original le faisait : `***` (3) + `**JAN.*` (3) donnait un total
        pair, dissimulant le balisage non refermé."""
        avertissements = verifier_sortie("JAN Mort ?", "***\n\n**JAN.*\nMort ?")

        self.assertTrue(any("impair" in a for a in avertissements))

    def test_le_marqueur_de_page_ne_compte_pas_dans_le_ratio(self):
        """Supprimer [PAGE X] est légitime et ne doit pas faire chuter le ratio."""
        source = "[PAGE 1]\n" + "mot " * 200
        sortie = "mot " * 200

        self.assertEqual(verifier_sortie(source, sortie), [])


class TestNormalisation(unittest.TestCase):
    def test_normaliser_label_unifie_les_variantes(self):
        for variante in ("**Acte premier.**", "ACTE PREMIER", "Acte  Premier :"):
            with self.subTest(variante=variante):
                self.assertEqual(normaliser_label(variante), "ACTE PREMIER")

    def test_accents_retires(self):
        self.assertEqual(normaliser_label("**Scène 3**"), "SCENE 3")

    def test_normaliser_pour_comptage_neutralise_les_marqueurs(self):
        resultat = normaliser_pour_comptage("[PAGE 3]\nAlpha\n\n<<<PAGE_BREAK>>>\n\nBeta")

        self.assertEqual(resultat, "Alpha Beta")


# ============================================================
# 4. FORME DES LIGNES
# ============================================================


class TestFormeDesLignes(unittest.TestCase):
    def test_separateur_reconnu(self):
        self.assertTrue(est_separateur("***"))
        self.assertTrue(est_separateur("  ****  "))
        self.assertFalse(est_separateur("**JAN.**"))

    def test_gras_reconnu(self):
        self.assertEqual(contenu_gras("**JAN.**"), "JAN.")
        self.assertIsNone(contenu_gras("*Pause.*"))

    def test_italique_reconnu(self):
        self.assertEqual(contenu_italique("*Pause.*"), "Pause.")

    def test_le_gras_n_est_pas_pris_pour_de_l_italique(self):
        """Piège classique : `**X**` satisfait aussi `^\\*.*\\*$`."""
        self.assertIsNone(contenu_italique("**JAN.**"))

    def test_separateur_n_est_ni_gras_ni_italique(self):
        self.assertIsNone(contenu_gras("***"))
        self.assertIsNone(contenu_italique("***"))
        # Cinq astérisques : forme qui satisferait le motif de gras.
        self.assertIsNone(contenu_gras("*****"))

    def test_ligne_de_replique(self):
        self.assertTrue(est_ligne_de_replique("Mort ?"))
        self.assertFalse(est_ligne_de_replique("**JAN.**"))
        self.assertFalse(est_ligne_de_replique("*Pause.*"))
        self.assertFalse(est_ligne_de_replique("***"))
        self.assertFalse(est_ligne_de_replique("   "))


# ============================================================
# 5. NUMÉROTATION
# ============================================================


class TestNumerotation(unittest.TestCase):
    def test_styles_reconnus(self):
        self.assertEqual(style_numerotation("UN"), "ecrit")
        self.assertEqual(style_numerotation("III"), "romain")
        self.assertEqual(style_numerotation("7"), "arabe")
        self.assertIsNone(style_numerotation("JAN"))

    def test_est_jeton_numerotation(self):
        self.assertTrue(est_jeton_numerotation("DEUX"))
        self.assertFalse(est_jeton_numerotation("LE MESSAGER"))

    def test_valeurs(self):
        self.assertEqual(valeur_numerotation("4"), 4)
        self.assertEqual(valeur_numerotation("TROIS"), 3)
        self.assertEqual(valeur_numerotation("XIV"), 14)
        # Notation soustractive.
        self.assertEqual(valeur_numerotation("IX"), 9)
        self.assertIsNone(valeur_numerotation("JAN"))


class TestNumeroAvecTitre(unittest.TestCase):
    """
    « I. L'évasion. » — un numéro suivi d'un titre sur la même ligne, convention
    de scène numérotée courante au théâtre moderne (Koltès, entre autres).

    Le cas typique : `Roberto Zucco` numérote ses quinze scènes ainsi, sans le
    mot « Acte » ni « Scène ». Sans cette reconnaissance, chaque en-tête
    devenait un faux personnage d'une réplique — silencieusement, aucune scène
    ne se formait, et la pièce entière s'affichait comme une unité unique.
    """

    def test_romain_avec_titre_est_reconnu(self):
        self.assertEqual(style_numerotation("I. L'EVASION"), "romain")
        self.assertTrue(est_jeton_numerotation("I. L'EVASION"))

    def test_arabe_avec_titre_est_reconnu(self):
        self.assertEqual(style_numerotation("3 - LE DUEL"), "arabe")

    def test_la_valeur_est_celle_du_numero_seul(self):
        self.assertEqual(valeur_numerotation("XIV. L'ARRESTATION"), 14)
        self.assertEqual(valeur_numerotation("3 - LE DUEL"), 3)

    def test_un_nom_de_personnage_nest_pas_confondu(self):
        """
        « PREMIER GARDIEN » ne doit jamais devenir un titre numéroté : c'est un
        rôle récurrent du répertoire classique, pas une scène numérotée en
        toutes lettres. D'où la restriction de `MOTIF_NUMERO_AVEC_TITRE` aux
        seuls chiffres romains et arabes, qui ne collisionnent pas avec un nom.
        """
        self.assertIsNone(style_numerotation("PREMIER GARDIEN"))
        self.assertFalse(est_jeton_numerotation("PREMIER GARDIEN"))
        self.assertIsNone(style_numerotation("SECOND GARDIEN"))

    def test_un_numero_seul_reste_inchange(self):
        """Le comportement déjà couvert par TestNumerotation ne doit pas bouger."""
        self.assertEqual(style_numerotation("III"), "romain")
        self.assertEqual(valeur_numerotation("III"), 3)

    def test_un_titre_colle_sans_separateur_n_est_pas_reconnu(self):
        """Sans ponctuation après le numéro, l'ambiguïté est trop grande."""
        self.assertIsNone(style_numerotation("I EVASION"))

    def test_classe_comme_titre_de_bout_en_bout(self):
        """
        Contrôle de bout en bout, comme pour un numéro seul : le classement
        réel sur un texte complet, pas seulement la fonction isolée.
        """
        texte = (
            "**I. L'évasion.**\n"
            "Le chemin de ronde.\n"
            "\n"
            "**PREMIER GARDIEN.**\n"
            "Tu as entendu quelque chose ?\n"
            "\n"
            "**II. Meurtre de la mère.**\n"
            "Dans la cuisine.\n"
            "\n"
            "**PREMIER GARDIEN.**\n"
            "Encore.\n"
        )
        index = construire_index_structure(texte)
        lignes = classifier_document(texte, index)

        titres = [l.texte for l in lignes if l.type is TypeLigne.TITRE_ACTE]
        personnages = {l.texte for l in lignes if l.type is TypeLigne.PERSONNAGE}

        self.assertEqual(titres, ["I. L'évasion.", "II. Meurtre de la mère."])
        self.assertEqual(personnages, {"PREMIER GARDIEN."})


# ============================================================
# 6. RECENSEMENT DE LA DISTRIBUTION
# ============================================================


class TestRecenserPersonnages(unittest.TestCase):
    def test_distribution_relevee(self):
        texte = (
            "**PERSONNAGES**\n"
            "JAN, le frère\n"
            "MARIA, sa femme\n"
            "LE VIEUX DOMESTIQUE\n"
            "\n\n"
            "**ACTE PREMIER**\n"
        )

        noms = recenser_personnages(texte)

        self.assertEqual(noms, {"JAN", "MARIA", "LE VIEUX DOMESTIQUE"})

    def test_absence_de_distribution_est_normale(self):
        self.assertEqual(recenser_personnages("**JAN.**\nMort ?"), set())

    def test_arret_sur_un_titre(self):
        texte = "**DISTRIBUTION**\nJAN\n**ACTE PREMIER**\nMARIA\n"

        self.assertEqual(recenser_personnages(texte), {"JAN"})

    def test_prose_non_confondue_avec_un_nom(self):
        texte = (
            "**PERSONNAGES**\n"
            "JAN\n"
            "La scène se déroule dans une auberge de Bohême.\n"
        )

        self.assertEqual(recenser_personnages(texte), {"JAN"})


# ============================================================
# 7. CLASSIFICATION — LE CŒUR DU MODULE
# ============================================================


class TestClassificationLexicale(unittest.TestCase):
    """Règles 1 et 2 : le lexique tranche sans ambiguïté."""

    def test_acte_et_scene_distingues(self):
        texte = (
            "**ACTE PREMIER**\n\n**SCÈNE 1**\n\n**JAN.**\nMort ?\n\n"
            "**MARIA.**\nOui.\n\n**SCÈNE 2**\n\n**JAN.**\nBon.\n"
        )

        index = construire_index_structure(texte)

        self.assertIs(index.type_de("ACTE PREMIER"), TypeLigne.TITRE_ACTE)
        self.assertIs(index.type_de("SCENE 1"), TypeLigne.TITRE_SCENE)
        self.assertIs(index.type_de("JAN"), TypeLigne.PERSONNAGE)

    def test_ordinal_avant_le_substantif(self):
        """« PREMIÈRE PARTIE » : le lexique est testé sur chaque mot."""
        index = construire_index_structure("**PREMIÈRE PARTIE**\n\n**JAN.**\nMort ?\n")

        self.assertIs(index.type_de("PREMIERE PARTIE"), TypeLigne.TITRE_ACTE)

    def test_prologue_est_un_acte(self):
        index = construire_index_structure("**PROLOGUE**\n\n**JAN.**\nMort ?\n")

        self.assertIs(index.type_de("PROLOGUE"), TypeLigne.TITRE_ACTE)


class TestClassificationPersonnages(unittest.TestCase):
    """Règles 4 à 6 : identifier les rôles."""

    def test_personnage_recurrent(self):
        texte = "**JAN.**\nA.\n\n**JAN.**\nB.\n\n**JAN.**\nC.\n"

        index = construire_index_structure(texte)

        classement = index.classements["JAN"]
        self.assertIs(classement.type, TypeLigne.PERSONNAGE)
        self.assertEqual(classement.occurrences, 3)

    def test_role_a_replique_unique(self):
        """
        Régression : un seuil d'occurrences seul classerait LE MESSAGER comme
        un titre, et lui infligerait un saut de page.
        """
        texte = (
            "**JAN.**\nA.\n\n**JAN.**\nB.\n\n"
            "**LE MESSAGER.**\nUn pli pour vous.\n\n"
            "**JAN.**\nC.\n"
        )

        index = construire_index_structure(texte)

        classement = index.classements["LE MESSAGER"]
        self.assertIs(classement.type, TypeLigne.PERSONNAGE)
        self.assertEqual(classement.occurrences, 1)
        self.assertIs(classement.confiance, Confiance.PROBABLE)

    def test_entete_de_distribution_n_est_pas_un_role(self):
        """
        Régression. « **PERSONNAGES** » est en gras et suivi d'une ligne ayant
        la forme d'une réplique (« JAN, le frère ») : la règle 5 en faisait un
        personnage, ce qui faussait le décompte des rôles.

        Le classer en titre d'acte serait pire : `a_acte_lexical` deviendrait
        vrai et basculerait tous les titres numérotés en scènes.
        """
        texte = (
            "**PERSONNAGES**\n"
            "JAN, le frère\n"
            "\n\n"
            "**UN.**\n\n"
            "**JAN.**\nA.\n"
        )

        index = construire_index_structure(texte)

        self.assertIs(index.type_de("PERSONNAGES"), TypeLigne.DISTRIBUTION)
        self.assertEqual(index.compter(TypeLigne.PERSONNAGE), 1)
        # L'en-tête n'a pas contaminé l'inférence de hiérarchie.
        self.assertIs(index.type_de("UN"), TypeLigne.TITRE_ACTE)

    def test_distribution_prime_sur_les_statistiques(self):
        texte = (
            "**PERSONNAGES**\n"
            "LA VOIX\n"
            "\n\n"
            "**JAN.**\nA.\n\n"
            "**LA VOIX**\n\n*Elle se tait.*\n"
        )

        index = construire_index_structure(texte)

        classement = index.classements["LA VOIX"]
        self.assertIs(classement.type, TypeLigne.PERSONNAGE)
        self.assertIs(classement.confiance, Confiance.CERTAINE)
        self.assertIn("distribution", classement.motif)


class TestInferenceHierarchie(unittest.TestCase):
    """Passe C : le niveau d'un titre purement numéroté."""

    def test_titres_numerotes_seuls_sont_des_actes(self):
        """
        Cas du prototype : une pièce en « UN / DEUX / TROIS », dont les
        changements de scène sont marqués par des `***`.
        """
        texte = (
            "**UN.**\n\n*Une rue. Mark et Jan.*\n\n**JAN.**\nMort ?\n\n"
            "***\n\n**DEUX.**\n\n**MARK.**\nOui.\n\n"
            "**TROIS.**\n\n**JAN.**\nComment ?\n"
        )

        index = construire_index_structure(texte)

        self.assertIs(index.type_de("UN"), TypeLigne.TITRE_ACTE)
        self.assertIs(index.type_de("DEUX"), TypeLigne.TITRE_ACTE)
        self.assertIs(index.type_de("TROIS"), TypeLigne.TITRE_ACTE)
        self.assertIs(index.classements["UN"].confiance, Confiance.DEDUITE)

    def test_titres_numerotes_sous_des_actes_lexicaux_sont_des_scenes(self):
        texte = (
            "**ACTE PREMIER**\n\n**1**\n\n**JAN.**\nA.\n\n"
            "**2**\n\n**JAN.**\nB.\n"
        )

        index = construire_index_structure(texte)

        self.assertIs(index.type_de("ACTE PREMIER"), TypeLigne.TITRE_ACTE)
        self.assertIs(index.type_de("1"), TypeLigne.TITRE_SCENE)
        self.assertIs(index.type_de("2"), TypeLigne.TITRE_SCENE)

    def test_deux_styles_de_numerotation_donnent_deux_niveaux(self):
        """Romain au premier niveau, arabe au second."""
        texte = (
            "**I**\n\n**1**\n\n**JAN.**\nA.\n\n"
            "**2**\n\n**JAN.**\nB.\n\n"
            "**II**\n\n**3**\n\n**JAN.**\nC.\n"
        )

        index = construire_index_structure(texte)

        self.assertIs(index.type_de("I"), TypeLigne.TITRE_ACTE)
        self.assertIs(index.type_de("II"), TypeLigne.TITRE_ACTE)
        self.assertIs(index.type_de("1"), TypeLigne.TITRE_SCENE)
        self.assertIs(index.type_de("3"), TypeLigne.TITRE_SCENE)


class TestSurcharges(unittest.TestCase):
    """Règle 0 : la surcharge manuelle prime sur toute heuristique."""

    def test_personnage_force(self):
        texte = "**UN.**\n\n**JAN.**\nMort ?\n"

        index = construire_index_structure(
            texte, personnages_forces=frozenset({"UN"})
        )

        self.assertIs(index.type_de("UN"), TypeLigne.PERSONNAGE)

    def test_scene_forcee_contre_le_lexique(self):
        """Une surcharge doit pouvoir contredire même le lexique."""
        index = construire_index_structure(
            "**ACTE PREMIER**\n\n**JAN.**\nA.\n",
            titres_scene_forces=frozenset({"ACTE PREMIER"}),
        )

        self.assertIs(index.type_de("ACTE PREMIER"), TypeLigne.TITRE_SCENE)


class TestAvertissements(unittest.TestCase):
    def test_classement_incertain_signale(self):
        """Un label sans aucun signal exploitable doit être signalé."""
        texte = "**ACTE PREMIER**\n\n**JAN.**\nA.\n\n**JAN.**\nB.\n\n**LA VOIX**\n\n*Silence.*\n"

        index = construire_index_structure(texte)

        self.assertEqual([c.affichage for c in index.incertains], ["LA VOIX"])
        self.assertTrue(any("incertain" in a for a in index.avertissements))

    def test_sans_signal_le_defaut_est_personnage_donc_sans_saut_de_page(self):
        """
        Régression. « LA VOIX », rôle dont l'unique intervention est une
        didascalie, était classé comme acte et recevait un saut de page —
        l'erreur la plus voyante possible pour le cas où l'on sait le moins.

        Le défaut est désormais « personnage » : si c'était en réalité un
        titre, il reste centré et gras, donc la dégradation est invisible.
        """
        texte = "**UN.**\n\n**JAN.**\nA.\n\n**LA VOIX**\n\n*Silence.*\n"

        index = construire_index_structure(texte)

        classement = index.classements["LA VOIX"]
        self.assertIs(classement.type, TypeLigne.PERSONNAGE)
        self.assertIs(classement.confiance, Confiance.INCERTAINE)

        # Seul « UN. » déclenche un saut de page.
        lignes = classifier_document(texte, index)
        actes = [l.texte for l in lignes if l.type is TypeLigne.TITRE_ACTE]
        self.assertEqual(actes, ["UN."])

    def test_label_inconnu_traite_comme_personnage(self):
        """
        Le défaut le moins risqué : une erreur sur un personnage est
        invisible, une erreur sur un acte produit une page blanche.
        """
        index = construire_index_structure("**JAN.**\nA.\n")

        self.assertIs(index.type_de("INCONNU ABSENT"), TypeLigne.PERSONNAGE)

    def test_absence_de_personnage_signalee(self):
        index = construire_index_structure("**ACTE PREMIER**\n")

        self.assertTrue(any("aucun personnage" in a for a in index.avertissements))


# ============================================================
# 8. CLASSIFICATION DES LIGNES DU DOCUMENT
# ============================================================


class TestClassifierDocument(unittest.TestCase):
    def setUp(self):
        self.texte = (
            "**ACTE PREMIER**\n"
            "\n"
            "*Une rue. Mark et Jan.*\n"
            "\n"
            "**JAN.**\n"
            "Mort ?\n"
            "\n"
            "*Pause.*\n"
            "\n"
            "***\n"
        )
        self.index = construire_index_structure(self.texte)
        self.lignes = classifier_document(self.texte, self.index)

    def _type_de_la_ligne(self, fragment: str) -> TypeLigne:
        for ligne in self.lignes:
            if fragment in ligne.brut:
                return ligne.type
        raise AssertionError(f"ligne introuvable : {fragment}")

    def test_lieu_distingue_de_la_didascalie(self):
        """Un italique après un titre est un lieu ; ailleurs, une didascalie."""
        self.assertIs(self._type_de_la_ligne("Une rue"), TypeLigne.LIEU)
        self.assertIs(self._type_de_la_ligne("Pause"), TypeLigne.DIDASCALIE)

    def test_types_des_autres_lignes(self):
        self.assertIs(self._type_de_la_ligne("ACTE PREMIER"), TypeLigne.TITRE_ACTE)
        self.assertIs(self._type_de_la_ligne("JAN"), TypeLigne.PERSONNAGE)
        self.assertIs(self._type_de_la_ligne("Mort ?"), TypeLigne.TEXTE)
        self.assertIs(self._type_de_la_ligne("***"), TypeLigne.SEPARATEUR)

    def test_marqueurs_retires_du_contenu(self):
        """
        Les astérisques de structure ne doivent pas atteindre le DOCX.

        Le séparateur est exclu : son contenu `***` n'est pas du texte à
        rendre, c'est un signal que `docx_export` interprète lui-même.
        """
        for ligne in self.lignes:
            if ligne.type is TypeLigne.SEPARATEUR:
                continue

            with self.subTest(ligne=ligne.brut):
                self.assertNotIn("*", ligne.texte)

    def test_toutes_les_lignes_conservees(self):
        """
        Aucune ligne ne doit disparaître : le DOCX doit tout restituer.

        Le compte peut en revanche **augmenter** si une ligne portait un nom de
        personnage et sa réplique ensemble : elle est alors dédoublée. Ce texte
        d'essai n'en contient pas.
        """
        self.assertEqual(len(self.lignes), len(self.texte.split("\n")))


class TestRepliqueEnLigne(unittest.TestCase):
    """
    Nom de personnage et réplique sur la même ligne.

    C'est la disposition de beaucoup d'éditions imprimées — « LÉA. Tu penses à
    quoi ? » — et le modèle d'édition la reproduit parfois malgré la consigne.
    Sans traitement, aucun personnage n'était reconnu et les astérisques se
    retrouvaient **visibles dans le DOCX**.
    """

    TEXTE = (
        "**LÉA.** Tu penses à quoi ?\n"
        "*Pas de réponse.*\n"
        "**PHIL.** Rien.\n"
        "**LÉA.** Encore ?\n"
    )

    def setUp(self):
        self.index = construire_index_structure(self.TEXTE)
        self.lignes = classifier_document(self.TEXTE, self.index)

    def test_dedoublement(self):
        resultat = dedoubler_replique_en_ligne("**LÉA.** Tu penses à quoi ?")

        self.assertEqual(resultat.nom, "LÉA.")
        self.assertIsNone(resultat.didascalie)
        self.assertEqual(resultat.replique, "Tu penses à quoi ?")

    def test_tiret_d_appel_retire(self):
        """
        Certains éditeurs séparent le nom de sa réplique par un tiret cadratin :
        « PREMIER GARDIEN. – Qu'est-ce… ». C'est une ponctuation de mise en page,
        non du texte de l'auteur : le conserver le ferait apparaître en tête de
        chaque réplique du document.
        """
        for tiret in ("–", "—", "-", "−"):
            with self.subTest(tiret=tiret):
                resultat = dedoubler_replique_en_ligne(
                    f"**PREMIER GARDIEN.** {tiret} Qu'est-ce qu'un type ferait ?"
                )

                self.assertEqual(resultat.nom, "PREMIER GARDIEN.")
                self.assertEqual(
                    resultat.replique, "Qu'est-ce qu'un type ferait ?"
                )

    def test_didascalie_dans_l_appel(self):
        """
        Disposition fréquente chez Brecht : « LES DIEUX, souriant. Bien sûr. »

        La didascalie est extraite séparément, car le style du nom est en gras
        et ne doit pas s'appliquer à elle.
        """
        resultat = dedoubler_replique_en_ligne("**LES DIEUX, souriant.** Bien sûr.")

        self.assertEqual(resultat.nom, "LES DIEUX")
        self.assertEqual(resultat.didascalie, "souriant.")
        self.assertEqual(resultat.replique, "Bien sûr.")

    def test_didascalie_longue_dans_l_appel(self):
        resultat = dedoubler_replique_en_ligne(
            "**WANG, revenant vers les Dieux.** Monsieur Tcheng est là."
        )

        self.assertEqual(resultat.nom, "WANG")
        self.assertEqual(resultat.didascalie, "revenant vers les Dieux.")

    def test_trois_paragraphes_pour_une_didascalie_d_appel(self):
        texte = "**LES DIEUX, souriant.** Bien sûr.\n"
        index = construire_index_structure(texte)

        types = [
            l.type
            for l in classifier_document(texte, index)
            if l.type is not TypeLigne.VIDE
        ]

        self.assertEqual(
            types,
            [TypeLigne.PERSONNAGE, TypeLigne.DIDASCALIE, TypeLigne.TEXTE],
        )

    def test_replique_vide_apres_retrait_du_tiret(self):
        """Un tiret seul ne constitue pas une réplique."""
        self.assertIsNone(dedoubler_replique_en_ligne("**JAN.** –"))


    def test_personnages_reconnus(self):
        self.assertEqual(self.index.compter(TypeLigne.PERSONNAGE), 2)

    def test_paragraphes_separes(self):
        types = [l.type for l in self.lignes if l.type is not TypeLigne.VIDE]

        self.assertEqual(
            types,
            [
                TypeLigne.PERSONNAGE,
                TypeLigne.TEXTE,
                TypeLigne.DIDASCALIE,
                TypeLigne.PERSONNAGE,
                TypeLigne.TEXTE,
                TypeLigne.PERSONNAGE,
                TypeLigne.TEXTE,
            ],
        )

    def test_aucune_asterisque_residuelle(self):
        for ligne in self.lignes:
            with self.subTest(ligne=ligne.brut):
                self.assertNotIn("*", ligne.texte)

    def test_emphase_simple_n_est_pas_dedoublee(self):
        """
        Garde-fou. Sans l'exigence de capitales, une emphase en tête de réplique
        fabriquerait un personnage inexistant.
        """
        for essai in (
            "**Attention** dit-il.",
            "**Mot** en gras au début.",
            "**Ça** compte.",
        ):
            with self.subTest(essai=essai):
                self.assertIsNone(dedoubler_replique_en_ligne(essai))

    def test_nom_seul_sur_sa_ligne_non_affecte(self):
        """La forme canonique ne doit pas être happée par ce traitement."""
        self.assertIsNone(dedoubler_replique_en_ligne("**JAN.**"))

    def test_separateur_non_affecte(self):
        self.assertIsNone(dedoubler_replique_en_ligne("***"))


class TestGraphieUniforme(unittest.TestCase):
    """
    Un même personnage doit s'écrire partout de la même façon.

    Selon la disposition de la ligne d'origine, le même rôle peut ressortir
    « WANG. » ou « WANG » — la seconde forme provenant d'un appel à didascalie,
    dont la virgule a été retirée. Rendre chaque occurrence telle quelle
    produirait un document irrégulier, ce qui est un défaut d'édition.
    """

    TEXTE = (
        "**WANG.** Attendez.\n"
        "**WANG.** Même si elle n'est pas préparée ?\n"
        "**WANG, revenant vers les Dieux.** Monsieur Tcheng est là.\n"
    )

    def test_forme_dominante_retenue(self):
        index = construire_index_structure(self.TEXTE)
        lignes = classifier_document(self.TEXTE, index)

        noms = {l.texte for l in lignes if l.type is TypeLigne.PERSONNAGE}

        self.assertEqual(noms, {"WANG."})

    def test_forme_dominante_est_la_plus_frequente(self):
        """Ce n'est pas la première rencontrée, mais bien la plus fréquente."""
        texte = (
            "**WANG, souriant.** Un.\n"
            "**WANG.** Deux.\n"
            "**WANG.** Trois.\n"
        )

        index = construire_index_structure(texte)

        self.assertEqual(index.affichage_de("WANG"), "WANG.")

    def test_titres_aussi_uniformises(self):
        texte = "**ACTE PREMIER**\n\n**JAN.**\nA.\n\n**Acte premier**\n\n**JAN.**\nB.\n"

        index = construire_index_structure(texte)
        lignes = classifier_document(texte, index)

        titres = {l.texte for l in lignes if l.type is TypeLigne.TITRE_ACTE}

        self.assertEqual(len(titres), 1)

    def test_label_inconnu_conserve_sa_graphie(self):
        index = construire_index_structure("**JAN.**\nA.\n")

        self.assertIsNone(index.affichage_de("ABSENT"))

class TestLieuApresSeparateur(unittest.TestCase):
    """
    Beaucoup de pièces contemporaines font suivre un `***` de la description du
    nouveau lieu, sans titre de scène intermédiaire.
    """

    def test_italique_apres_separateur_est_un_lieu(self):
        texte = (
            "**LÉA.** Rien.\n"
            "***\n"
            "*Un champ. Léa et Phil, Phil mange une glace.*\n"
            "**LÉA.** Encore ?\n"
        )

        index = construire_index_structure(texte)
        lignes = classifier_document(texte, index)

        lieux = [l.texte for l in lignes if l.type is TypeLigne.LIEU]

        self.assertEqual(lieux, ["Un champ. Léa et Phil, Phil mange une glace."])

    def test_italique_en_cours_de_scene_reste_une_didascalie(self):
        texte = "**LÉA.** Tu penses à quoi ?\n*Pas de réponse.*\n"

        index = construire_index_structure(texte)
        lignes = classifier_document(texte, index)

        self.assertEqual(
            [l.texte for l in lignes if l.type is TypeLigne.DIDASCALIE],
            ["Pas de réponse."],
        )

    def test_les_types_couvrent_les_styles_configures(self):
        """
        Contrat avec docx_export : chaque type stylé correspond à une clé de
        DEFINITIONS_STYLES. Un style oublié doit échouer ici, pas en production.
        """
        types_styles = {
            TypeLigne.TITRE_OEUVRE,
            TypeLigne.TITRE_SECONDAIRE,
            TypeLigne.EPIGRAPHE,
            TypeLigne.ATTRIBUTION,
            TypeLigne.NOTE,
            TypeLigne.PROLOGUE,
            TypeLigne.TITRE_ACTE,
            TypeLigne.TITRE_SCENE,
            TypeLigne.DISTRIBUTION,
            TypeLigne.ENTREE_DISTRIBUTION,
            TypeLigne.LIEU,
            TypeLigne.PERSONNAGE,
            TypeLigne.DIDASCALIE,
            TypeLigne.DIDASCALIE_LONGUE,
            TypeLigne.TEXTE,
        }

        self.assertEqual(
            {t.value for t in types_styles},
            set(config.DEFINITIONS_STYLES),
        )


# ============================================================
# 9. EMPHASES INTERNES
# ============================================================


class TestDecouperEnRuns(unittest.TestCase):
    def test_didascalie_intercalee(self):
        runs = decouper_en_runs("Je t'attendais *elle se lève* depuis une heure.")

        self.assertEqual(
            runs,
            [
                Run("Je t'attendais "),
                Run("elle se lève", italique=True),
                Run(" depuis une heure."),
            ],
        )

    def test_gras_interne(self):
        runs = decouper_en_runs("Un mot **capital** ici.")

        self.assertEqual(runs[1], Run("capital", gras=True))

    def test_gras_prioritaire_sur_italique(self):
        """Si l'italique passait d'abord, `**mot**` donnerait un run vide."""
        runs = decouper_en_runs("**mot**")

        self.assertEqual(runs, [Run("mot", gras=True)])

    def test_ligne_sans_emphase(self):
        self.assertEqual(decouper_en_runs("Texte simple."), [Run("Texte simple.")])

    def test_texte_conserve_intact(self):
        """Propriété de non-perte : concaténer les runs restitue le texte."""
        ligne = "Début *milieu* et **fin** ici."

        self.assertEqual(
            "".join(r.texte for r in decouper_en_runs(ligne)),
            ligne.replace("*", ""),
        )

    def test_ligne_vide(self):
        self.assertEqual(decouper_en_runs(""), [])


# ============================================================
# 10. RAPPORT D'INSPECTION
# ============================================================


class TestRapportClassification(unittest.TestCase):
    def test_rapport_lisible_et_complet(self):
        texte = (
            "**ACTE PREMIER**\n\n**SCÈNE 1**\n\n"
            "**JAN.**\nA.\n\n**JAN.**\nB.\n"
        )

        rapport = rapport_classification(construire_index_structure(texte))

        self.assertIn("ACTE PREMIER", rapport)
        self.assertIn("SCÈNE 1", rapport)
        self.assertIn("JAN.", rapport)
        self.assertIn("Actes : 1", rapport)
        self.assertIn("Scènes : 1", rapport)
        self.assertIn("Personnages : 1", rapport)

    def test_incertain_marque_visuellement(self):
        texte = "**ACTE PREMIER**\n\n**JAN.**\nA.\n\n**JAN.**\nB.\n\n**LA VOIX**\n\n*Silence.*\n"

        rapport = rapport_classification(construire_index_structure(texte))

        self.assertIn("⚠", rapport)


# ============================================================
# 11. SCÉNARIO COMPLET
# ============================================================


class TestScenarioRealiste(unittest.TestCase):
    """
    Une pièce miniature mais structurellement complète, traversant tout le
    module : distribution, actes lexicaux, scènes, rôle à réplique unique,
    lieu, didascalies, emphase interne et séparateur.
    """

    PIECE = (
        "**PERSONNAGES**\n"
        "JAN, le frère\n"
        "MARIA, sa femme\n"
        "LE MESSAGER\n"
        "\n"
        "\n"
        "**ACTE PREMIER**\n"
        "\n"
        "*Une auberge. Le soir.*\n"
        "\n"
        "**JAN.**\n"
        "Nous y sommes enfin.\n"
        "\n"
        "**MARIA.**\n"
        "Je t'attendais *elle se lève* depuis une heure.\n"
        "\n"
        "*Pause.*\n"
        "\n"
        "***\n"
        "\n"
        "**SCÈNE 2**\n"
        "\n"
        "**LE MESSAGER.**\n"
        "Un pli pour vous.\n"
        "\n"
        "**JAN.**\n"
        "Donnez.\n"
    )

    def setUp(self):
        self.index = construire_index_structure(self.PIECE)
        self.lignes = classifier_document(self.PIECE, self.index)

    def test_structure_correctement_identifiee(self):
        self.assertEqual(self.index.compter(TypeLigne.TITRE_ACTE), 1)
        self.assertEqual(self.index.compter(TypeLigne.TITRE_SCENE), 1)
        self.assertEqual(self.index.compter(TypeLigne.PERSONNAGE), 3)

    def test_aucun_classement_incertain(self):
        """Sur une pièce bien formée, l'heuristique ne doit pas hésiter."""
        self.assertEqual(self.index.incertains, [])

    def test_un_seul_saut_de_page(self):
        """
        La conséquence visible de la classification : un seul acte, donc une
        seule page neuve. Une scène prise pour un acte se verrait ici.
        """
        actes = [l for l in self.lignes if l.type is TypeLigne.TITRE_ACTE]

        self.assertEqual([l.texte for l in actes], ["ACTE PREMIER"])

    def test_emphase_interne_preservee(self):
        replique = next(l for l in self.lignes if "attendais" in l.texte)
        runs = decouper_en_runs(replique.texte)

        self.assertIn(Run("elle se lève", italique=True), runs)

    def test_distribution_utilisee(self):
        for nom in ("JAN", "MARIA", "LE MESSAGER"):
            with self.subTest(nom=nom):
                self.assertIs(
                    self.index.classements[nom].confiance, Confiance.CERTAINE
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
