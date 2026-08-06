"""
Tests de `parser` et `analyze`.

Exécution, depuis `outil_coupes/` :

    python -m unittest discover -s tests -t .

`unittest` de la bibliothèque standard, volontairement : ces tests tournent
sans aucune dépendance installée, comme le reste du projet (voir
`../outil_edition/tests/test_blocks.py`).
"""
from __future__ import annotations

import csv
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import analyze
from parser import JOKER_TOUS, charger_repet, compter_mots, libelle_unite


def _document() -> dict:
    """Petit REPET.json synthétique couvrant les cas notables :

    - deux unités, la seconde implicite (héritant de l'acte, sans scène) ;
    - un personnage largement dominant (ALICE) et deux rôles creux (BOB, CAROL) ;
    - une ligne collective (« TOUS. » -> JOKER_TOUS), à exclure de la présence ;
    - une ligne de texte sans personnage annoncé, conservée mais signalée.
    """
    return {
        "schema": "repetition/2",
        "piece": "Pièce de test",
        "outil": "test",
        "genere_le": "2026-01-01T00:00:00",
        "avertissements": ["classement incertain : « X »"],
        "liminaires": [],
        "personnages": [
            {"nom": "ALICE", "repliques": 1, "mots": 100},
            {"nom": "BOB", "repliques": 1, "mots": 1},
            {"nom": "CAROL", "repliques": 1, "mots": 1},
        ],
        "unites": [
            {
                "id": "u001",
                "acte": "ACTE PREMIER",
                "scene": "SCÈNE 1",
                "implicite": False,
                "personnages": ["ALICE", "BOB"],
                "elements": [
                    {"type": "lieu", "texte": "Une chambre."},
                    {
                        "type": "replique", "id": "r_1", "personnages": ["ALICE"],
                        "texte": " ".join(["mot"] * 100), "vers": False,
                    },
                    {
                        "type": "replique", "id": "r_2", "personnages": ["BOB"],
                        "texte": "Salut", "vers": False,
                    },
                    {"type": "texte_sans_personnage", "texte": "orphelin"},
                ],
            },
            {
                "id": "u002",
                "acte": "ACTE PREMIER",
                "scene": None,
                "implicite": True,
                "personnages": ["CAROL", JOKER_TOUS],
                "elements": [
                    {
                        "type": "replique", "id": "r_3", "personnages": ["CAROL"],
                        "texte": "Salut", "vers": False,
                    },
                ],
            },
        ],
    }


class ChargerRepetTests(unittest.TestCase):
    def test_charge_un_document_valide(self):
        with TemporaryDirectory() as tmp:
            chemin = Path(tmp) / "Pièce_REPET.json"
            chemin.write_text(json.dumps(_document()), encoding="utf-8")
            doc = charger_repet(str(chemin))
        self.assertEqual(doc["piece"], "Pièce de test")

    def test_refuse_un_schema_inattendu(self):
        with TemporaryDirectory() as tmp:
            chemin = Path(tmp) / "LIMINAIRES.json"
            chemin.write_text(json.dumps({"schema": "liminaires/1"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                charger_repet(str(chemin))


class CompterMotsTests(unittest.TestCase):
    def test_compte_les_accents_et_apostrophes(self):
        self.assertEqual(compter_mots("Qu'est-ce qu'il a dit à l'âne ?"), 7)

    def test_ignore_la_ponctuation_seule(self):
        self.assertEqual(compter_mots("... ! ?"), 0)


class LibelleUniteTests(unittest.TestCase):
    def test_avec_acte_et_scene(self):
        unite = {"id": "u001", "acte": "ACTE PREMIER", "scene": "SCÈNE 1"}
        self.assertEqual(libelle_unite(unite), "ACTE PREMIER - SCÈNE 1 [u001]")

    def test_sans_titre(self):
        unite = {"id": "u002", "acte": None, "scene": None}
        self.assertEqual(libelle_unite(unite), "Unité sans titre [u002]")

    def test_unicite_garantie_par_lid_meme_titre_repete(self):
        a = libelle_unite({"id": "u001", "acte": "ACTE I", "scene": None})
        b = libelle_unite({"id": "u002", "acte": "ACTE I", "scene": None})
        self.assertNotEqual(a, b)


class CmdDetectTests(unittest.TestCase):
    def test_signale_les_unites_implicites_et_les_avertissements(self):
        with TemporaryDirectory() as tmp:
            chemin = Path(tmp) / "Pièce_REPET.json"
            chemin.write_text(json.dumps(_document()), encoding="utf-8")

            sortie = io.StringIO()
            with redirect_stdout(sortie):
                analyze.cmd_detect(str(chemin))

        texte = sortie.getvalue()
        self.assertIn("Unités jouables : 2  (dont 1 sans titre", texte)
        self.assertIn("Personnages     : 3", texte)
        self.assertIn("classement incertain : « X »", texte)
        self.assertIn("ligne(s) de texte sans personnage annoncé", texte)


class CmdComputeTests(unittest.TestCase):
    def _executer(self, tmp, cast_path=None, target=None):
        chemin = Path(tmp) / "Pièce_REPET.json"
        chemin.write_text(json.dumps(_document()), encoding="utf-8")

        sortie = io.StringIO()
        with redirect_stdout(sortie):
            analyze.cmd_compute(str(chemin), cast_path, target)

        # cmd_compute écrit toujours la matrice dans outil_coupes/sorties/ : on
        # la supprime après chaque test pour ne pas polluer ce dossier de travail.
        csv_path = (
            Path(analyze.__file__).resolve().parent / "sorties" / (chemin.stem + "_presence.csv")
        )
        self.addCleanup(csv_path.unlink, missing_ok=True)

        return chemin, sortie.getvalue()

    def test_flags_role_hypertrophie_et_roles_creux(self):
        with TemporaryDirectory() as tmp:
            _, texte = self._executer(tmp)

        lignes = {ligne.split()[0]: ligne for ligne in texte.splitlines() if ligne[:1].isalpha()}
        self.assertIn("hypertrophié", lignes["ALICE"])
        self.assertIn("creux", lignes["BOB"])
        self.assertIn("creux", lignes["CAROL"])

    def test_exclut_le_joker_tous_de_la_presence(self):
        with TemporaryDirectory() as tmp:
            chemin, texte = self._executer(tmp)
            # Le CSV est écrit dans outil_coupes/sorties/ (voir _executer), jamais
            # à côté du REPET source qui vit dans le dossier Drive partagé.
            csv_path = (
                Path(analyze.__file__).resolve().parent
                / "sorties" / (chemin.stem + "_presence.csv")
            )
            with open(csv_path, encoding="utf-8") as f:
                lignes = list(csv.reader(f))

        en_tete = lignes[0]
        self.assertEqual(en_tete, ["Unite", "ALICE", "BOB", "CAROL"])

        u001 = next(l for l in lignes if l[0].startswith("ACTE PREMIER - SCÈNE 1"))
        self.assertEqual(u001[1:], ["X", "X", ""])

        u002 = next(l for l in lignes if l[0].startswith("ACTE PREMIER [u002]"))
        self.assertEqual(u002[1:], ["", "", "X"])

        self.assertIn("1 unité(s) contiennent une réplique collective", texte)

    def test_agregation_par_comedien_signale_les_non_mappes(self):
        with TemporaryDirectory() as tmp:
            cast_path = Path(tmp) / "cast.json"
            cast_path.write_text(
                json.dumps({"Comédien A": ["ALICE"], "Comédien B": ["BOB"]}), encoding="utf-8"
            )
            _, texte = self._executer(tmp, cast_path=str(cast_path))

        self.assertIn("RÉPARTITION PAR COMÉDIEN", texte)
        self.assertIn("Comédien A", texte)
        self.assertIn("non mappé] CAROL", texte)

    def test_cible_classe_les_unites_par_poids_decroissant(self):
        with TemporaryDirectory() as tmp:
            _, texte = self._executer(tmp, target=1)

        position_u001 = texte.index("ACTE PREMIER - SCÈNE 1")
        position_u002 = texte.index("ACTE PREMIER [u002]")
        self.assertLess(position_u001, position_u002)
        self.assertIn("À couper", texte)


if __name__ == "__main__":
    unittest.main()
