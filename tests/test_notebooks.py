"""
Tests des notebooks Colab.

Un notebook cassé ne se découvre normalement qu'à l'exécution, dans Colab,
après le montage du Drive et l'installation des dépendances — c'est-à-dire au
pire moment. Ces tests déplacent la détection ici.

Trois familles de contrôles :

- **validité formelle** : JSON correct, `nbformat` attendu, code Python
  syntaxiquement valide ;
- **finesse** : aucune logique métier dans les cellules, conformément à la
  séparation stricte entre le paquet et l'interface ;
- **cohérence avec le code** : chaque `module.fonction()` appelé dans un
  notebook existe réellement dans le paquet. C'est le contrôle le plus utile :
  renommer une fonction sans mettre à jour les notebooks est une erreur facile,
  et invisible jusqu'à l'exécution.
"""

from __future__ import annotations

import ast
import importlib
import json
import re
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DOSSIER_NOTEBOOKS = RACINE / "notebooks"

NOTEBOOKS_ATTENDUS = (
    "01_OCR.ipynb",
    "02_Edition.ipynb",
    "03_Verification.ipynb",
    "04_DOCX.ipynb",
)

# Modules du paquet susceptibles d'être appelés depuis un notebook, associés à
# leur chemin d'import.
MODULES_APPELABLES = {
    "ocr": "theatre_editor.ocr",
    "edition": "theatre_editor.edition",
    "liminaires": "theatre_editor.liminaires",
    "validation": "theatre_editor.validation",
    "docx_export": "theatre_editor.docx_export",
    "config": "theatre_editor.config",
    "io": "theatre_editor.utils.io",
    "blocks": "theatre_editor.utils.blocks",
    "api": "theatre_editor.utils.api",
}

# Signes d'une logique métier qui n'aurait rien à faire dans un notebook.
MOTIFS_LOGIQUE_METIER = (
    "responses.create",
    "appeler_modele(",
    "OpenAI(",
    "get_pixmap",
)


def charger(nom: str) -> dict:
    """Charge un notebook."""
    return json.loads((DOSSIER_NOTEBOOKS / nom).read_text(encoding="utf-8"))


def source_des_cellules(notebook: dict, type_cellule: str = "code") -> list[str]:
    """
    Retourne le code source de chaque cellule d'un type donné.

    **La concaténation se fait sans séparateur**, exactement comme Jupyter.
    C'est essentiel : une version antérieure de cette fonction joignait avec
    `"\\n"`, ce qui **réinsérait les sauts de ligne manquants** et reconstruisait
    du Python valide à partir de notebooks cassés. Les tests validaient alors
    l'intention du générateur, non le fichier réellement produit — et les quatre
    notebooks étaient inexécutables sans qu'aucun test ne le signale.

    Un test doit lire l'artefact comme son consommateur le lit.
    """
    return [
        "".join(cellule["source"])
        for cellule in notebook["cells"]
        if cellule["cell_type"] == type_cellule
    ]


def neutraliser_magies(source: str) -> str:
    """
    Remplace les lignes magiques `!pip …` par un commentaire.

    Elles sont valides dans Jupyter mais ne sont pas du Python : les laisser
    ferait échouer l'analyse syntaxique.
    """
    return "\n".join(
        f"pass  # {ligne}" if ligne.strip().startswith(("!", "%")) else ligne
        for ligne in source.split("\n")
    )


def _sans_marqueur(ligne: str) -> str:
    """Retire le `#` d'ouverture d'une ligne commentée."""
    nue = ligne.lstrip()

    return nue[2:] if nue.startswith("# ") else nue[1:]


def _est_bloc_de_code(lignes: list[str]) -> bool:
    """
    Détermine si un bloc de commentaires contigus est du code désactivé.

    Deux conditions, et les deux sont nécessaires. Le bloc doit être du Python
    analysable — ce qui écarte la prose française — **et** comporter un signe
    d'instruction. Sans cette seconde condition, un commentaire d'un seul mot
    comme « # Exemple » serait analysé comme une expression Python valide.
    """
    candidat = "\n".join(_sans_marqueur(ligne) for ligne in lignes)

    if not any(signe in candidat for signe in ("=", "(", "import ")):
        return False

    try:
        ast.parse(candidat)
    except SyntaxError:
        return False

    return True


def decommenter(source: str) -> str:
    """
    Réactive les exemples de code volontairement commentés.

    Plusieurs cellules proposent des exemples à décommenter. On veut vérifier
    qu'ils sont corrects : l'utilisateur les décommentera, et découvrir alors
    qu'ils sont fautifs serait pénible.

    Le traitement porte sur des **blocs contigus**, non sur des lignes isolées.
    Ligne à ligne, le corps indenté d'un `if` commenté serait réactivé sans son
    `if`, ce qui produirait un bloc orphelin — c'est exactement le défaut de la
    première version de cette fonction.
    """
    resultat: list[str] = []
    bloc: list[str] = []

    def vider() -> None:
        if not bloc:
            return

        if _est_bloc_de_code(bloc):
            resultat.extend(_sans_marqueur(ligne) for ligne in bloc)
        else:
            resultat.extend(bloc)

        bloc.clear()

    for ligne in source.split("\n"):
        if ligne.lstrip().startswith("#"):
            bloc.append(ligne)
        else:
            vider()
            resultat.append(ligne)

    vider()

    return "\n".join(resultat)


class TestPresence(unittest.TestCase):
    def test_les_quatre_notebooks_existent(self):
        presents = sorted(p.name for p in DOSSIER_NOTEBOOKS.glob("*.ipynb"))

        self.assertEqual(presents, sorted(NOTEBOOKS_ATTENDUS))

    def test_generateur_present(self):
        """
        Les notebooks sont produits par un script : le format Jupyter est un
        JSON verbeux où une virgule manquante rend le fichier illisible.
        """
        self.assertTrue((RACINE / "outils" / "generer_notebooks.py").is_file())


class TestValiditeFormelle(unittest.TestCase):
    def test_json_valide_et_nbformat_attendu(self):
        for nom in NOTEBOOKS_ATTENDUS:
            with self.subTest(notebook=nom):
                notebook = charger(nom)

                self.assertEqual(notebook["nbformat"], 4)
                self.assertIn("cells", notebook)
                self.assertGreater(len(notebook["cells"]), 5)

    def test_metadonnees_colab(self):
        for nom in NOTEBOOKS_ATTENDUS:
            with self.subTest(notebook=nom):
                metadonnees = charger(nom)["metadata"]

                self.assertEqual(metadonnees["kernelspec"]["name"], "python3")
                self.assertEqual(metadonnees["colab"]["name"], nom)

    def test_chaque_ligne_porte_son_saut_de_ligne(self):
        """
        Contrôle direct de la convention `nbformat`, au plus près du format.

        Jupyter concatène les éléments de `source` **sans séparateur**. Chaque
        ligne doit donc contenir son propre `\\n`, sauf la dernière. Sans cela,
        tout le contenu se retrouve sur une seule ligne — ce qui produit une
        `SyntaxError` dans une cellule de code, et un texte illisible dans une
        cellule Markdown.
        """
        for nom in NOTEBOOKS_ATTENDUS:
            for index, cellule in enumerate(charger(nom)["cells"]):
                lignes = cellule["source"]

                if len(lignes) < 2:
                    continue

                for position, ligne in enumerate(lignes[:-1]):
                    with self.subTest(notebook=nom, cellule=index, ligne=position):
                        self.assertTrue(
                            ligne.endswith("\n"),
                            f"ligne sans saut de ligne : {ligne!r}",
                        )

                with self.subTest(notebook=nom, cellule=index, ligne="dernière"):
                    self.assertFalse(lignes[-1].endswith("\n"))

    def test_texte_reconstitue_identique_au_source(self):
        """
        La concaténation sans séparateur doit restituer un texte cohérent : des
        lignes distinctes, et non un bloc collé.
        """
        for nom in NOTEBOOKS_ATTENDUS:
            for index, source in enumerate(source_des_cellules(charger(nom))):
                if "\n" not in source and len(source) < 60:
                    continue

                with self.subTest(notebook=nom, cellule=index):
                    self.assertIn(
                        "\n",
                        source,
                        "cellule multiligne reconstituée sur une seule ligne",
                    )

    def test_code_syntaxiquement_valide(self):
        for nom in NOTEBOOKS_ATTENDUS:
            for index, source in enumerate(source_des_cellules(charger(nom))):
                with self.subTest(notebook=nom, cellule=index):
                    try:
                        ast.parse(neutraliser_magies(source))
                    except SyntaxError as erreur:
                        self.fail(f"{nom}, cellule {index} : {erreur}")

    def test_exemples_commentes_syntaxiquement_valides(self):
        """
        Les exemples à décommenter doivent fonctionner : l'utilisateur les
        décommentera, et découvrir alors qu'ils sont fautifs serait pénible.
        """
        for nom in NOTEBOOKS_ATTENDUS:
            for index, source in enumerate(source_des_cellules(charger(nom))):
                with self.subTest(notebook=nom, cellule=index):
                    try:
                        ast.parse(decommenter(neutraliser_magies(source)))
                    except SyntaxError as erreur:
                        self.fail(f"{nom}, cellule {index} décommentée : {erreur}")

    def test_aucune_sortie_enregistree(self):
        """
        Des sorties enregistrées alourdissent le dépôt et peuvent contenir des
        extraits de texte sous droits.
        """
        for nom in NOTEBOOKS_ATTENDUS:
            for index, cellule in enumerate(charger(nom)["cells"]):
                if cellule["cell_type"] != "code":
                    continue

                with self.subTest(notebook=nom, cellule=index):
                    self.assertEqual(cellule["outputs"], [])
                    self.assertIsNone(cellule["execution_count"])


class TestFinesseDesNotebooks(unittest.TestCase):
    """La séparation stricte entre logique métier et interface."""

    def test_aucune_logique_metier(self):
        for nom in NOTEBOOKS_ATTENDUS:
            source_complete = "\n".join(source_des_cellules(charger(nom)))

            for motif in MOTIFS_LOGIQUE_METIER:
                with self.subTest(notebook=nom, motif=motif):
                    self.assertNotIn(motif, source_complete)

    def test_aucune_definition_de_fonction(self):
        """Une fonction définie dans un notebook est de la logique déplacée."""
        for nom in NOTEBOOKS_ATTENDUS:
            for index, source in enumerate(source_des_cellules(charger(nom))):
                arbre = ast.parse(neutraliser_magies(source))

                with self.subTest(notebook=nom, cellule=index):
                    self.assertFalse(
                        [n for n in arbre.body if isinstance(n, ast.FunctionDef)]
                    )

    def test_aucune_cle_api_en_dur(self):
        for nom in NOTEBOOKS_ATTENDUS:
            source_complete = "\n".join(source_des_cellules(charger(nom)))

            with self.subTest(notebook=nom):
                self.assertNotIn("sk-", source_complete)

    def test_chaque_notebook_appelle_son_etape(self):
        attendus = {
            "01_OCR.ipynb": "ocr.executer(",
            "02_Edition.ipynb": "edition.executer(",
            "03_Verification.ipynb": "validation.executer(",
            "04_DOCX.ipynb": "docx_export.executer(",
        }

        for nom, appel in attendus.items():
            with self.subTest(notebook=nom):
                self.assertIn(appel, "\n".join(source_des_cellules(charger(nom))))

    def test_docx_ne_demande_pas_de_cle_api(self):
        """L'étape 4 n'appelle aucune API : exiger une clé serait trompeur."""
        source = "\n".join(source_des_cellules(charger("04_DOCX.ipynb")))

        self.assertNotIn("charger_cle_api", source)

    def test_liminaires_lancee_avec_l_edition(self):
        """
        La passe des liminaires appelle un modèle. Elle appartient donc au
        notebook 02, et non au 04 : l'étape DOCX est annoncée gratuite,
        déterministe et rejouable à volonté, ce qu'un appel d'API démentirait.
        """
        edition = "\n".join(source_des_cellules(charger("02_Edition.ipynb")))
        export = "\n".join(source_des_cellules(charger("04_DOCX.ipynb")))

        self.assertIn("liminaires.executer(", edition)
        self.assertNotIn("liminaires.executer(", export)

    def test_sections_numerotees_sans_trou_ni_doublon(self):
        """
        Les titres sont numérotés à la main dans le générateur. Insérer une
        section sans renuméroter les suivantes produit un notebook où deux
        sections portent le même numéro — sans qu'aucun autre test s'en
        aperçoive, l'utilisateur devant s'y repérer.
        """
        for nom in NOTEBOOKS_ATTENDUS:
            numeros = [
                int(correspondance.group(1))
                for source in source_des_cellules(charger(nom), "markdown")
                for correspondance in re.finditer(r"(?m)^## (\d+)\.", source)
            ]

            with self.subTest(notebook=nom):
                self.assertEqual(numeros, list(range(1, len(numeros) + 1)))


class TestCoherenceAvecLeCode(unittest.TestCase):
    """
    Chaque `module.attribut` cité dans un notebook doit exister.

    C'est le contrôle le plus utile de ce fichier : renommer une fonction sans
    mettre à jour les notebooks est une erreur facile, et qui ne se manifeste
    qu'à l'exécution dans Colab.
    """

    @staticmethod
    def _references(nom_notebook: str) -> set[tuple[str, str]]:
        """
        Relève les accès `module.attribut` d'un notebook, via son AST.

        L'analyse syntaxique et non une expression régulière : une regex
        capturait « config.py » dans un commentaire, et aurait tout aussi bien
        capturé une mention dans une chaîne de caractères. L'AST ne voit que du
        code réel.
        """
        source = decommenter(
            neutraliser_magies("\n".join(source_des_cellules(charger(nom_notebook))))
        )

        trouvees: set[tuple[str, str]] = set()

        for noeud in ast.walk(ast.parse(source)):
            if not isinstance(noeud, ast.Attribute):
                continue

            if isinstance(noeud.value, ast.Name) and noeud.value.id in MODULES_APPELABLES:
                trouvees.add((noeud.value.id, noeud.attr))

        return trouvees

    def test_attributs_references_existent(self):
        modules = {
            alias: importlib.import_module(chemin)
            for alias, chemin in MODULES_APPELABLES.items()
        }

        for nom in NOTEBOOKS_ATTENDUS:
            for alias, attribut in self._references(nom):
                with self.subTest(notebook=nom, reference=f"{alias}.{attribut}"):
                    self.assertTrue(
                        hasattr(modules[alias], attribut),
                        f"{MODULES_APPELABLES[alias]}.{attribut} n'existe pas",
                    )

    def test_constantes_de_configuration_citees_existent(self):
        """Une surcharge portant sur une constante inexistante serait sans effet."""
        from theatre_editor import config

        for nom in NOTEBOOKS_ATTENDUS:
            for alias, attribut in self._references(nom):
                if alias != "config" or not attribut.isupper():
                    continue

                with self.subTest(notebook=nom, constante=attribut):
                    self.assertTrue(hasattr(config, attribut))

    def test_le_controle_trouve_bien_des_references(self):
        """
        Garde-fou : un extracteur défaillant rendrait les deux tests précédents
        vides, donc verts sans rien vérifier.
        """
        for nom in NOTEBOOKS_ATTENDUS:
            with self.subTest(notebook=nom):
                self.assertGreater(len(self._references(nom)), 3)


class TestReproductibilite(unittest.TestCase):
    def test_generateur_idempotent(self):
        """
        Relancer le générateur ne doit produire aucune modification, sans quoi
        chaque exécution polluerait le dépôt d'un diff inutile.
        """
        import subprocess
        import sys

        avant = {
            nom: (DOSSIER_NOTEBOOKS / nom).read_bytes() for nom in NOTEBOOKS_ATTENDUS
        }

        subprocess.run(
            [sys.executable, str(RACINE / "outils" / "generer_notebooks.py")],
            check=True,
            capture_output=True,
            cwd=RACINE,
        )

        for nom in NOTEBOOKS_ATTENDUS:
            with self.subTest(notebook=nom):
                self.assertEqual((DOSSIER_NOTEBOOKS / nom).read_bytes(), avant[nom])


if __name__ == "__main__":
    unittest.main(verbosity=2)
