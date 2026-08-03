"""
Tests des prompts et de leur concordance avec `config.py`.

Trois prompts contiennent des chaînes que le code analyse ensuite : les
délimiteurs de la passe de raccord, la mention « aucun problème », les
catégories de constats. Les modifier dans le prompt sans les modifier dans
`config.py` casserait le pipeline **sans lever la moindre erreur** — le parseur
ne trouverait simplement plus ce qu'il cherche, et rendrait un texte vide ou
non découpé.

C'est exactement le genre de rupture que des prompts externalisés rendent
possible : le bénéfice de pouvoir les éditer sans toucher au Python a pour
contrepartie ce risque. Ces tests le neutralisent.
"""

from __future__ import annotations

import unittest

from theatre_editor import config
from theatre_editor.utils import io

PROMPTS_ATTENDUS = (
    "prompt_ocr",
    "prompt_edition",
    "prompt_raccord",
    "prompt_validation",
    "prompt_liminaires",
)


class TestPresenceDesPrompts(unittest.TestCase):
    def test_les_quatre_prompts_existent(self):
        self.assertEqual(io.lister_prompts(), sorted(PROMPTS_ATTENDUS))

    def test_chargement_et_contenu_substantiel(self):
        for nom in PROMPTS_ATTENDUS:
            with self.subTest(prompt=nom):
                contenu = io.charger_prompt(nom)
                self.assertGreater(len(contenu), 400)
                # `charger_prompt` applique un strip.
                self.assertEqual(contenu, contenu.strip())

    def test_prompt_absent_leve_une_erreur_utile(self):
        with self.assertRaises(FileNotFoundError) as contexte:
            io.charger_prompt("prompt_inexistant")

        message = str(contexte.exception)
        # L'erreur doit énumérer les prompts réels, la cause la plus probable
        # étant une faute de frappe sur le nom.
        self.assertIn("prompt_edition", message)

    def test_le_readme_n_est_pas_un_prompt(self):
        """
        Tout ce qu'un fichier de prompt contient part au modèle. Le README doit
        donc rester hors de la liste des prompts chargeables.
        """
        self.assertNotIn("README", io.lister_prompts())


class TestContratRaccord(unittest.TestCase):
    """Le parseur de `edition.py` dépend de ces quatre délimiteurs."""

    def setUp(self):
        self.prompt = io.charger_prompt("prompt_raccord")

    def test_les_quatre_delimiteurs_sont_imposes(self):
        for delimiteur in (
            config.DELIM_RACCORD_GAUCHE,
            config.DELIM_RACCORD_GAUCHE_FIN,
            config.DELIM_RACCORD_DROIT,
            config.DELIM_RACCORD_DROIT_FIN,
        ):
            with self.subTest(delimiteur=delimiteur):
                self.assertIn(delimiteur, self.prompt)

    def test_idempotence_exigee(self):
        """
        Le prompt doit exiger de rendre les extraits inchangés lorsqu'aucune
        correction n'est nécessaire. Cette propriété rend un raccord rejouable :
        une coupure entre l'écriture des .txt et celle du .json fait refaire la
        jonction sur un texte déjà raccordé, ce qui doit être sans effet.
        """
        self.assertIn("aucune correction n'est nécessaire", self.prompt)

    def test_portee_limitee_a_la_jonction(self):
        self.assertIn("éloignée de la jonction", self.prompt)

    def test_placement_de_la_ressoudure_impose(self):
        """
        Sans cette règle, un mot ressoudé mais laissé à cheval sur les deux
        extraits reste coupé en deux dans l'édition finale : les extraits sont
        réassemblés avec un saut de ligne, et chaque ligne devient un
        paragraphe. Défaut observé sur une exécution réelle.
        """
        self.assertIn("PLACEMENT D'UNE RESSOUDURE", self.prompt)
        self.assertIn("entièrement dans l'un des deux extraits", self.prompt)
        self.assertIn("jamais à cheval", self.prompt)


class TestContratValidation(unittest.TestCase):
    def setUp(self):
        self.prompt = io.charger_prompt("prompt_validation")

    def test_mention_aucun_probleme_imposee(self):
        """
        Sans cette mention exacte, « bloc vérifié, rien à signaler » serait
        indiscernable de « bloc non vérifié ».
        """
        self.assertIn(config.MENTION_AUCUN_PROBLEME, self.prompt)

    def test_toutes_les_categories_sont_declarees(self):
        for categorie in config.CATEGORIES_VALIDATION:
            with self.subTest(categorie=categorie):
                self.assertIn(f"[{categorie}]", self.prompt)

    def test_aucune_categorie_non_declaree(self):
        """
        L'inverse du test précédent : une catégorie présente dans le prompt mais
        absente de `config.py` ne serait jamais reconnue par le code.
        """
        import re

        trouvees = set(re.findall(r"^\[([A-Z ]+)\]$", self.prompt, re.MULTILINE))
        declarees = set(config.CATEGORIES_VALIDATION)

        self.assertEqual(trouvees - declarees, set())

    def test_interdiction_de_modifier_le_texte(self):
        self.assertIn("Tu ne modifies jamais le texte", self.prompt)

    def test_faux_positifs_desamorces(self):
        """
        Le point le plus important de ce prompt. Entre OCR.txt et EDIT.txt, les
        différences légitimes sont bien plus nombreuses que les pertes réelles.
        Sans cette liste, chaque bloc remonterait des dizaines de faux positifs.
        """
        for legitime in (
            "[PAGE X]",
            "<<<PAGE_BREAK>>>",
            "numéro de page imprimé isolé",
            "correction d'une faute d'orthographe",
            "astérisques",
        ):
            with self.subTest(difference=legitime):
                self.assertIn(legitime, self.prompt)

    def test_doute_resolu_en_faveur_du_silence(self):
        self.assertIn("considère\nqu'elle est volontaire", self.prompt)


class TestContratOcr(unittest.TestCase):
    def setUp(self):
        self.prompt = io.charger_prompt("prompt_ocr")

    def test_mention_page_sans_texte_imposee(self):
        """Sans elle, une page blanche serait indiscernable d'un échec d'appel."""
        self.assertIn(config.MENTION_PAGE_SANS_TEXTE, self.prompt)

    def test_marqueurs_de_page_interdits(self):
        """
        Les marqueurs sont ajoutés par le code à l'assemblage, jamais par le
        modèle : c'est ce qui rend leur format déterministe.
        """
        self.assertIn("n'écris jamais [PAGE X] ni <<<PAGE_BREAK>>>", self.prompt)

    def test_aucune_correction_autorisee(self):
        """
        Fondement de l'étape 3 : si l'OCR corrigeait déjà, il n'existerait plus
        de référence permettant de détecter ce que l'étape 2 aurait perdu.
        """
        self.assertIn("Tu transcris. Tu ne corriges pas.", self.prompt)
        self.assertIn("corriger une faute d'orthographe, même évidente", self.prompt)

    def test_aucune_mise_en_forme(self):
        """
        Un OCR produisant déjà du `**JAN.**` rendrait illisible la comparaison
        de l'étape 3. La convention typographique appartient à l'étape 2.
        """
        self.assertIn("aucun astérisque", self.prompt)

    def test_disposition_preservee(self):
        self.assertIn("Une ligne imprimée devient une ligne de ta transcription.", self.prompt)

    def test_marque_illisible_commune_aux_deux_prompts(self):
        """
        `prompt_ocr` et `prompt_edition` doivent employer la même marque, sinon
        les passages illisibles échapperaient à tout dénombrement.
        """
        for nom in ("prompt_ocr", "prompt_edition"):
            with self.subTest(prompt=nom):
                self.assertIn(config.MARQUE_ILLISIBLE, io.charger_prompt(nom))


class TestContratEdition(unittest.TestCase):
    def setUp(self):
        self.prompt = io.charger_prompt("prompt_edition")

    def test_suppression_des_marqueurs_exigee(self):
        self.assertIn("les marqueurs [PAGE X]", self.prompt)
        self.assertIn("les marqueurs <<<PAGE_BREAK>>>", self.prompt)

    def test_convention_typographique_complete(self):
        """
        Les cinq formes que `blocks.classifier_document()` sait reconnaître
        doivent toutes être prescrites, sinon l'étape 4 ne les verra jamais.
        """
        for exemple in ("**UN.**", "*Une rue. Mark et Jan.*", "**JAN.**", "*Pause.*"):
            with self.subTest(exemple=exemple):
                self.assertIn(exemple, self.prompt)

        # Le séparateur de scène, seul sur sa ligne.
        self.assertRegex(self.prompt, r"(?m)^\*\*\*$")

    def test_fidelite_prioritaire(self):
        self.assertIn(
            "La fidélité au texte fourni est prioritaire", self.prompt
        )

    def test_aucun_commentaire_en_sortie(self):
        self.assertIn("aucune balise de code", self.prompt)


class TestQualiteFormelle(unittest.TestCase):
    """Contrôles applicables à tous les prompts."""

    def test_aucune_fin_de_ligne_windows(self):
        """
        Un \\r résiduel se retrouverait dans les instructions envoyées au
        modèle. `io.lire_texte()` normalise, ce test vérifie que la
        normalisation opère bien.
        """
        for nom in PROMPTS_ATTENDUS:
            with self.subTest(prompt=nom):
                self.assertNotIn("\r", io.charger_prompt(nom))

    def test_aucun_bloc_de_code_markdown(self):
        """
        Une clôture ``` dans un prompt inciterait le modèle à répondre dans un
        bloc de code — précisément ce que `nettoyer_enveloppe()` doit ensuite
        défaire, et ce que `MOTIFS_INTERDITS` signale comme anomalie.
        """
        for nom in PROMPTS_ATTENDUS:
            with self.subTest(prompt=nom):
                self.assertNotIn("```", io.charger_prompt(nom))

    def test_mise_en_cache(self):
        """`charger_prompt` est mis en cache : un prompt est relu des centaines
        de fois au cours d'un livre."""
        premier = io.charger_prompt("prompt_edition")
        second = io.charger_prompt("prompt_edition")

        self.assertIs(premier, second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
