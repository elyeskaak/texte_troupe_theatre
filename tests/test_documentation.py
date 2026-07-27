"""
Tests de la documentation.

Un tutoriel qui mentionne une constante renommée, un secret inexistant ou une
section de notebook disparue est **pire qu'une absence de tutoriel** : il envoie
son lecteur dans le mur avec assurance. Et rien, dans une chaîne d'outils
ordinaire, ne signale cette dérive.

Ces tests ancrent donc la documentation au code : chaque `config.CONSTANTE`
citée doit exister, chaque section de notebook référencée doit être présente,
chaque lien relatif doit résoudre.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from theatre_editor import config

RACINE = Path(__file__).resolve().parent.parent

DOCUMENTS = (
    "README.md",
    "TUTORIEL.md",
    "ARCHITECTURE.md",
    "archive/README.md",
    "theatre_editor/prompts/README.md",
)

MOTIF_CONSTANTE = re.compile(r"config\.([A-Z][A-Z0-9_]*)")
MOTIF_LIEN = re.compile(r"\]\(([^)]+)\)")


def lire(nom: str) -> str:
    return (RACINE / nom).read_text(encoding="utf-8")


class TestPresence(unittest.TestCase):
    def test_documents_presents(self):
        for nom in DOCUMENTS:
            with self.subTest(document=nom):
                self.assertTrue((RACINE / nom).is_file())

    def test_readme_renvoie_au_tutoriel(self):
        self.assertIn("TUTORIEL.md", lire("README.md"))


class TestConstantesCitees(unittest.TestCase):
    """Une constante renommée doit faire échouer la documentation qui la cite."""

    def test_constantes_existent(self):
        for nom in DOCUMENTS:
            for constante in sorted(set(MOTIF_CONSTANTE.findall(lire(nom)))):
                with self.subTest(document=nom, constante=constante):
                    self.assertTrue(
                        hasattr(config, constante),
                        f"config.{constante} n'existe pas",
                    )

    def test_le_controle_trouve_bien_des_constantes(self):
        """
        Garde-fou : une expression régulière défaillante rendrait le test
        précédent vide, donc vert sans rien vérifier.
        """
        trouvees = set(MOTIF_CONSTANTE.findall(lire("TUTORIEL.md")))

        self.assertGreaterEqual(len(trouvees), 3)


class TestValeursCitees(unittest.TestCase):
    """Les valeurs données en exemple doivent être celles du code."""

    def test_dossier_de_travail(self):
        self.assertIn(config.DOSSIER_DRIVE.name, lire("TUTORIEL.md"))

    def test_taille_des_blocs(self):
        """Le tutoriel explique la réédition d'un bloc avec cette valeur."""
        self.assertEqual(config.PAGES_PAR_BLOC, 8)
        self.assertIn("blocs de 8", lire("TUTORIEL.md"))

    def test_police(self):
        self.assertIn(config.POLICE_TEXTE, lire("TUTORIEL.md"))

    def test_suffixes_de_fichiers(self):
        tuto = lire("TUTORIEL.md")

        for suffixe in (config.SUFFIXE_OCR, config.SUFFIXE_EDIT, config.SUFFIXE_REPORT):
            with self.subTest(suffixe=suffixe):
                self.assertIn(suffixe, tuto)

    def test_nom_du_secret_de_cle_api(self):
        self.assertIn(config.NOM_CLE_API, lire("TUTORIEL.md"))

    def test_secret_github_coherent_avec_les_notebooks(self):
        """
        Le nom du secret est défini par le générateur de notebooks : le tutoriel
        doit citer le même.
        """
        generateur = lire("outils/generer_notebooks.py")
        nom = re.search(r'NOM_SECRET_JETON = "([^"]+)"', generateur).group(1)

        self.assertIn(nom, lire("TUTORIEL.md"))

    def test_depot_coherent_avec_les_notebooks(self):
        generateur = lire("outils/generer_notebooks.py")
        compte = re.search(r'DEPOT_COMPTE = "([^"]+)"', generateur).group(1)
        depot = re.search(r'DEPOT_NOM = "([^"]+)"', generateur).group(1)

        tuto = lire("TUTORIEL.md")

        self.assertIn(compte, tuto)
        self.assertIn(depot, tuto)

    def test_conventions_typographiques_exactes(self):
        """
        Le tutoriel explique comment corriger EDIT.txt à la main : les exemples
        doivent correspondre à ce que `blocks` sait relire.
        """
        from theatre_editor.utils import blocks

        tuto = lire("TUTORIEL.md")
        index = blocks.construire_index_structure(
            "**ACTE PREMIER**\n*Une auberge. Le soir.*\n**JAN.**\n"
            "Nous y sommes enfin.\n***\n"
        )

        self.assertIn("**ACTE PREMIER**", tuto)
        self.assertIn("**JAN.**", tuto)
        self.assertIs(
            index.type_de("ACTE PREMIER"), blocks.TypeLigne.TITRE_ACTE
        )
        self.assertIs(index.type_de("JAN"), blocks.TypeLigne.PERSONNAGE)


class TestSectionsDeNotebook(unittest.TestCase):
    """
    Le tutoriel guide cellule par cellule : une section renumérotée le rendrait
    trompeur, et c'est précisément ce qui est arrivé pendant son écriture.
    """

    @staticmethod
    def sections(nom_notebook: str) -> set[int]:
        notebook = json.loads(lire(f"notebooks/{nom_notebook}"))

        return {
            int(correspondance.group(1))
            for cellule in notebook["cells"]
            if cellule["cell_type"] == "markdown"
            for ligne in cellule["source"]
            if (correspondance := re.match(r"^##\s+(\d+)\.", ligne))
        }

    def test_sections_citees_existent(self):
        reelles = self.sections("01_OCR.ipynb")
        tuto = lire("TUTORIEL.md")

        citees = {int(n) for n in re.findall(r"### Section (\d+)", tuto)}
        citees |= {int(n) for n in re.findall(r"sections? (\d+)", tuto)}

        self.assertTrue(citees, "aucune section citée : le motif est-il correct ?")
        self.assertEqual(citees - reelles, set())

    def test_sections_numerotees_sans_trou(self):
        """Une renumérotation manquée laisserait un trou ou un doublon."""
        for notebook in (
            "01_OCR.ipynb",
            "02_Edition.ipynb",
            "03_Verification.ipynb",
            "04_DOCX.ipynb",
        ):
            with self.subTest(notebook=notebook):
                sections = sorted(self.sections(notebook))

                self.assertEqual(sections, list(range(1, len(sections) + 1)))


class TestCoherenceDuDiscours(unittest.TestCase):
    """
    Le contenu doit correspondre à ses titres, et à la réalité du dépôt.

    Ces contrôles viennent d'un bug réel : en basculant la documentation du
    dépôt privé vers le dépôt public, le titre « Créer la clé OpenAI » s'est
    retrouvé au-dessus des instructions du jeton GitHub. Le remplacement avait
    porté sur l'en-tête, pas sur le corps — et rien ne le signalait.
    """

    def test_le_depot_n_est_plus_presente_comme_prive(self):
        for nom in ("TUTORIEL.md", "README.md"):
            with self.subTest(document=nom):
                texte = lire(nom)

                self.assertNotIn("Le dépôt est **privé**", texte)
                self.assertNotIn("dépôt étant privé", texte)

    def test_section_de_la_cle_openai_parle_bien_d_openai(self):
        tuto = lire("TUTORIEL.md")

        debut = tuto.index("## 3. Créer la clé OpenAI")
        fin = tuto.index("## 4.")
        section = tuto[debut:fin]

        self.assertIn("platform.openai.com", section)
        self.assertIn("sk-", section)
        # Les étapes de création d'un jeton GitHub n'ont rien à faire ici.
        self.assertNotIn("Generate new token", section)
        self.assertNotIn("github_pat_", section)

    def test_checklist_coherente_avec_les_sections(self):
        """Une checklist qui renvoie à une section disparue égare son lecteur."""
        tuto = lire("TUTORIEL.md")

        titres = set(re.findall(r"^##\s+(\d+)\.", tuto, re.M))
        renvois = set(re.findall(r"\(§(\d+)\)", tuto))

        self.assertTrue(renvois)
        self.assertEqual(renvois - titres, set())

    def test_jeton_github_presente_comme_optionnel(self):
        """
        Il reste mentionné — la cellule le gère — mais ne doit plus figurer
        comme une étape obligatoire.
        """
        tuto = lire("TUTORIEL.md")

        self.assertIn("aucun jeton GitHub n'est nécessaire", tuto)


class TestLiens(unittest.TestCase):
    def test_liens_relatifs_resolvent(self):
        for nom in DOCUMENTS:
            base = (RACINE / nom).parent

            for lien in MOTIF_LIEN.findall(lire(nom)):
                if lien.startswith(("http", "#")):
                    continue

                cible = base / lien.split("#")[0]

                with self.subTest(document=nom, lien=lien):
                    self.assertTrue(cible.exists(), f"cible absente : {cible}")

    def test_ancres_internes_de_architecture(self):
        texte = lire("ARCHITECTURE.md")

        def slug(titre: str) -> str:
            nettoye = re.sub(r"[^\w\sÀ-ɏ-]", "", titre.strip().lower())
            return nettoye.replace(" ", "-")

        ancres = {slug(m) for m in re.findall(r"^#{2,4}\s+(.+)$", texte, re.M)}
        liens = [l for l in re.findall(r"\]\(#([^)]+)\)", texte)]

        self.assertTrue(liens)
        self.assertEqual([l for l in liens if l not in ancres], [])


class TestDepannage(unittest.TestCase):
    """
    Le tableau de dépannage doit citer des messages que le code produit
    réellement, sinon il est inutilisable au moment où on en a besoin.
    """

    def test_messages_d_erreur_reels(self):
        """
        Les messages produits par les notebooks sont cherchés dans le **notebook
        généré**, non dans le générateur : celui-ci ne contient que des gabarits
        où le nom du secret est encore une variable non interpolée.
        """
        tuto = lire("TUTORIEL.md")

        sources = {
            "Récupération du code impossible": "notebooks/01_OCR.ipynb",
            "Clé API introuvable": "theatre_editor/utils/io.py",
            "Dossier de travail introuvable": "theatre_editor/utils/io.py",
            "découpage incohérent": "theatre_editor/validation.py",
        }

        for message, fichier in sources.items():
            with self.subTest(message=message):
                self.assertIn(message, tuto, "message absent du tutoriel")
                self.assertIn(message, lire(fichier), f"message absent de {fichier}")

    def test_repli_du_modele_ocr_documente(self):
        """
        La réserve sur la vision de MODEL_OCR doit être accompagnée de son
        repli, faute de quoi le lecteur reste bloqué.
        """
        tuto = lire("TUTORIEL.md")

        self.assertIn("gpt-4o", tuto)
        self.assertIn("MODEL_OCR", tuto)


if __name__ == "__main__":
    unittest.main(verbosity=2)
