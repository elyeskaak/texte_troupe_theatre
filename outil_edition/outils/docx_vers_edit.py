"""
Convertit un DOCX déjà mis en forme en `EDIT.txt`, sans IA et sans OCR.

**À quoi cela sert.** Le pipeline part d'un scan PDF. Mais certaines pièces
existent déjà comme documents propres — une édition faite à la main pour la
troupe, un texte reçu au format Word. Les faire passer par l'OCR serait absurde :
on paierait pour transcrire un texte déjà numérique, et on risquerait de le
dégrader.

Cet utilitaire les fait entrer par l'étape 4. Il écrit `temp/<Livre>/EDIT.txt`,
après quoi la commande habituelle produit le DOCX **et** le `REPET.json` :

    python outils/docx_vers_edit.py "exemples/Ma pièce.docx"
    python -m theatre_editor.main --etape docx --dossier exemples

**Pourquoi ce n'est pas de l'heuristique.** Le module ne devine rien : il lit la
mise en forme que le document porte explicitement. `Heading 1` est un acte,
`Heading 2` une scène, un paragraphe en gras un nom de personnage. Ces trois
informations sont dans le fichier, posées par celui qui l'a écrit. Là où
`outil_coupes/parser.py` devinait à partir de la casse et de la longueur, on se
contente ici de traduire une structure déclarée.

Deux ajustements sont néanmoins nécessaires, et tous deux sont expliqués au point
où ils se produisent : le préfixe redondant des titres de scène (§ `_titre_scene`)
et les pages liminaires (§ `_separer_liminaires`).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from theatre_editor import config  # noqa: E402
from theatre_editor.utils import blocks, io  # noqa: E402

# Part du texte en gras au-delà de laquelle un paragraphe est tenu pour un nom de
# personnage. Les noms observés sont à 0,8 ou 1,0 — un correcteur ayant parfois
# laissé un caractère hors du gras — et les répliques à 0,0.
SEUIL_GRAS = 0.6

# Préfixe redondant d'un titre de scène : « Acte II - Séquence 3 » → « Séquence 3 ».
MOTIF_PREFIXE_ACTE = re.compile(
    r"^\s*acte\s+[ivxlcdm\d]+\s*[-–—:]\s*",
    re.IGNORECASE,
)


@dataclass
class Rapport:
    """Ce que la conversion a fait, pour que rien ne se produise en silence."""

    actes: int = 0
    scenes: int = 0
    personnages: set[str] = field(default_factory=set)
    repliques: int = 0
    liminaires_ecartes: list[str] = field(default_factory=list)
    prefixes_retires: int = 0
    avertissements: list[str] = field(default_factory=list)
    # Paragraphes de dialogue qui en suivaient un autre : à relire dans la source.
    continuations: list[tuple[str, str, str]] = field(default_factory=list)

    def texte_des_continuations(self) -> str:
        """Liste relisible des cas douteux, à confronter au texte d'origine."""
        lignes = [
            "PARAGRAPHES DE DIALOGUE CONSÉCUTIFS",
            "=" * 72,
            "",
            "Chacun de ces paragraphes suit un autre paragraphe de dialogue, sans",
            "nom de personnage entre les deux. Deux lectures sont possibles, et le",
            "document ne permet pas de trancher :",
            "",
            "  – le même personnage poursuit sur un nouveau paragraphe ;",
            "  – un nom de personnage manque dans le document source.",
            "",
            "Les deux paragraphes ont été réunis en une seule réplique, attribuée au",
            "personnage précédent. Si l'un de ces cas est en réalité un nom manquant,",
            "corrigez le DOCX et relancez la conversion.",
            "",
        ]

        for scene, avant, apres in self.continuations:
            lignes += [
                "-" * 72,
                f"{scene}",
                f"  avant : …{avant}",
                f"  suite : {apres}",
            ]

        return "\n".join(lignes) + "\n"

    def afficher(self) -> None:
        print(f"   actes                {self.actes}")
        print(f"   scènes               {self.scenes}")
        print(f"   personnages          {len(self.personnages)}")
        print(f"   répliques            {self.repliques}")

        if self.prefixes_retires:
            print(f"   préfixes retirés     {self.prefixes_retires} (voir _titre_scene)")

        if self.continuations:
            print(f"   paragraphes réunis   {len(self.continuations)} — À RELIRE")

        if self.liminaires_ecartes:
            print(f"   liminaires écartés   {len(self.liminaires_ecartes)}")
            for ligne in self.liminaires_ecartes:
                print(f"      – {ligne[:66]}")

        for avertissement in self.avertissements:
            print(f"   [ALERTE]  {avertissement}")


@dataclass(frozen=True)
class Paragraphe:
    """Un paragraphe du DOCX, réduit à ce qui porte du sens."""

    texte: str
    style: str
    part_gras: float

    @property
    def titre_acte(self) -> bool:
        return self.style.startswith("Heading 1")

    @property
    def titre_scene(self) -> bool:
        return self.style.startswith("Heading 2")

    @property
    def personnage(self) -> bool:
        return not self.titre_acte and not self.titre_scene and self.part_gras >= SEUIL_GRAS


def lire_paragraphes(chemin: Path) -> list[Paragraphe]:
    """Extrait les paragraphes non vides d'un DOCX."""
    try:
        import docx
    except ImportError as erreur:  # pragma: no cover - dépend de l'environnement
        raise RuntimeError(
            "python-docx est introuvable.\nInstallez-le :  pip install -U python-docx"
        ) from erreur

    document = docx.Document(str(chemin))
    resultat: list[Paragraphe] = []

    for paragraphe in document.paragraphs:
        texte = paragraphe.text.strip()

        if not texte:
            continue

        runs = paragraphe.runs
        total = sum(len(run.text) for run in runs) or 1
        gras = sum(len(run.text) for run in runs if run.bold) / total

        resultat.append(
            Paragraphe(texte=texte, style=paragraphe.style.name, part_gras=gras)
        )

    return resultat


def _separer_liminaires(
    paragraphes: list[Paragraphe],
) -> tuple[list[Paragraphe], list[Paragraphe]]:
    """
    Sépare les pages liminaires du corps de la pièce.

    Le corps commence au **premier titre reconnu comme un acte** par le lexique de
    `config.LEXIQUE_ACTE` — le même lexique que l'étape 4, et non un critère
    inventé ici.

    Écarter les liminaires n'est pas de la commodité. « LA TOILE D'ARAIGNÉE
    (Spider's web) » n'appartient à aucun lexique, n'est pas un jeton de
    numérotation, et ne figure dans aucune distribution : la règle 7 de §9.1 en
    ferait un **personnage** par défaut, et la ligne suivante — « Auteur : Agatha
    Christie » — deviendrait sa réplique. Le titre de l'œuvre se retrouverait donc
    dans le sélecteur de rôles, disant le nom de son auteur.

    Le vrai remède serait l'étape 2 bis, qui annote les liminaires par IA. Mais
    elle suppose un `EDIT.txt` déjà produit, et son objet est de départager des
    lignes ambiguës — alors qu'ici la frontière est explicite. On les écarte donc,
    en les **annonçant** : le nom du livre porte déjà le titre de la pièce.
    """
    for rang, paragraphe in enumerate(paragraphes):
        if paragraphe.titre_acte and blocks._correspond_lexique(
            blocks.normaliser_label(paragraphe.texte), config.LEXIQUE_ACTE
        ):
            return paragraphes[:rang], paragraphes[rang:]

    # Aucun titre d'acte : toute la pièce est le corps. Mieux vaut un document
    # sans acte qu'un document vidé de son texte.
    return [], paragraphes


def _titre_scene(texte: str, rapport: Rapport) -> str:
    """
    Retire le préfixe d'acte d'un titre de scène.

    « Acte II - Séquence 3 » devient « Séquence 3 », et ce retrait est
    **indispensable**, pas cosmétique. `blocks._correspond_lexique` teste *chaque
    mot* du label — le français plaçant l'ordinal avant ou après. Le titre complet
    contient donc à la fois « ACTE » et « SÉQUENCE », et la règle 1 de §9.1
    (lexique d'acte) l'emporte sur la règle 2 : les 44 séquences seraient classées
    comme des actes, avec un saut de page chacune, et la pièce n'aurait plus une
    seule scène.

    L'information n'est pas perdue : l'acte reste porté par le `Heading 1` qui
    englobe la séquence.
    """
    reduit = MOTIF_PREFIXE_ACTE.sub("", texte).strip()

    if reduit != texte:
        rapport.prefixes_retires += 1

    return reduit or texte


def _nom_de_personnage(texte: str) -> str:
    """
    Met un nom de personnage à la convention `**NOM.**`.

    Le point final est la convention d'imprimerie retenue par §8 : il annonce la
    réplique. Il n'est ajouté que s'il manque, pour ne pas produire « HUGO.. ».
    """
    nu = texte.strip()

    return nu if blocks.MOTIF_PONCTUATION_FINALE.search(nu) else f"{nu}."


def convertir(paragraphes: list[Paragraphe]) -> tuple[str, Rapport]:
    """
    Traduit des paragraphes en texte au format `EDIT.txt`.

    Fonction **pure** : ni disque, ni DOCX. C'est ce qui la rend testable sans
    fabriquer de fichier.
    """
    rapport = Rapport()
    liminaires, corps = _separer_liminaires(paragraphes)

    rapport.liminaires_ecartes = [p.texte for p in liminaires]

    lignes: list[str] = []
    # Nom du personnage dont la réplique est ouverte, et rang de sa ligne dans
    # `lignes` — pour pouvoir y raccorder un paragraphe de continuation.
    personnage_ouvert: str | None = None
    rang_replique: int | None = None
    # Acte et scène sont suivis séparément, et les messages citent les deux :
    # le préfixe « Acte III - » est retiré des titres de scène (voir
    # `_titre_scene`), si bien que « Séquence 4 » existe une fois par acte. Le
    # citer seul renverrait à quatre endroits du document.
    acte_courant = "(avant tout acte)"
    scene_courante = "(avant toute scène)"

    def ou() -> str:
        return f"{acte_courant} / {scene_courante}"

    def poser(ligne: str) -> int:
        # Une ligne vide sépare chaque élément : la convention de §8 s'appuie
        # dessus pour la lisibilité, et l'étape 4 les ignore de toute façon.
        if lignes:
            lignes.append("")

        lignes.append(ligne)

        return len(lignes) - 1

    def fermer(motif: str) -> None:
        nonlocal personnage_ouvert, rang_replique

        if personnage_ouvert is not None and rang_replique is None:
            # La scène est nommée dans le message : sans elle, l'avertissement
            # oblige à parcourir un document de 2 500 paragraphes pour retrouver
            # le passage. Il devient alors plus simple de l'ignorer.
            rapport.avertissements.append(
                f"« {personnage_ouvert} » annoncé sans réplique "
                f"dans {ou()} {motif}"
            )

        personnage_ouvert = None
        rang_replique = None

    for paragraphe in corps:
        if paragraphe.titre_acte:
            fermer(f"avant « {paragraphe.texte[:40]} »")
            acte_courant = paragraphe.texte
            scene_courante = "(sans titre de scène)"
            rapport.actes += 1
            poser(f"**{paragraphe.texte}**")
            continue

        if paragraphe.titre_scene:
            fermer(f"avant « {paragraphe.texte[:40]} »")
            rapport.scenes += 1
            scene_courante = _titre_scene(paragraphe.texte, rapport)
            poser(f"**{scene_courante}**")
            continue

        if paragraphe.personnage:
            fermer(f"— suivi de « {paragraphe.texte[:30]} »")

            nom = _nom_de_personnage(paragraphe.texte)
            personnage_ouvert = nom
            rapport.personnages.add(nom)
            poser(f"**{nom}**")
            continue

        # --- paragraphe de dialogue ---------------------------------
        if personnage_ouvert is None:
            # Aucun personnage ouvert : la ligne est conservée, jamais jetée, et
            # signalée. `repet_export` la marquera « texte_sans_personnage ».
            rapport.avertissements.append(
                f"texte sans personnage annoncé dans {ou()} : "
                f"« {paragraphe.texte[:50]} »"
            )
            poser(paragraphe.texte)
            continue

        if rang_replique is None:
            rapport.repliques += 1
            rang_replique = poser(paragraphe.texte)
            continue

        # Second paragraphe de dialogue pour le même personnage. Deux lectures
        # sont possibles et le document ne permet pas de trancher : soit il
        # poursuit son propos sur un nouveau paragraphe, soit un nom manque dans
        # la source.
        #
        # On **réunit sur la même ligne**, plutôt que d'ajouter une ligne. Ce
        # n'est pas un détail : la convention de §8 réserve les lignes séparées
        # aux vers, et `repet_export` en déduit `vers: true`. Deux paragraphes de
        # prose empilés seraient donc présentés comme un passage versifié, que
        # l'outil de répétition refuserait de recomposer. Réunir donne de la
        # prose, ce qu'ils sont.
        #
        # Le cas est consigné dans un rapport à relire : c'est un doute sur la
        # source, pas une décision à cacher.
        rapport.continuations.append(
            (ou(), lignes[rang_replique][-50:], paragraphe.texte[:50])
        )
        lignes[rang_replique] = f"{lignes[rang_replique]} {paragraphe.texte}"

    fermer("en fin de pièce")

    return "\n".join(lignes) + "\n", rapport


def convertir_fichier(chemin_docx: Path, dossier: Path | None = None) -> Path:
    """
    Convertit un DOCX et écrit `temp/<Livre>/EDIT.txt`.

    Le nom du livre est dérivé du nom du fichier, exactement comme l'étape 1 le
    dérive du PDF : tous les chemins en découlent ensuite mécaniquement.
    """
    nom_livre = chemin_docx.stem
    base = dossier if dossier is not None else chemin_docx.parent
    chemins = io.resoudre_chemins(nom_livre, base)

    # ---------------------------------------------------------------
    # Garde-fou : l'étape 4 écrit son document à `<base>/<livre>.docx`.
    # Converti sur place, ce chemin est **le fichier source lui-même** : la
    # commande suivante écraserait le document d'origine par sa propre
    # régénération, et le texte de travail de la troupe serait perdu.
    #
    # Le refus est préférable à l'avertissement. Le message arriverait avant la
    # commande destructrice, donc plusieurs minutes avant le dégât, et aurait
    # défilé.
    # ---------------------------------------------------------------
    if chemins.docx.resolve() == chemin_docx.resolve():
        raise SystemExit(
            f"Refus : l'étape 4 écrirait son DOCX sur le fichier source.\n"
            f"  source  {chemin_docx}\n"
            f"  sortie  {chemins.docx}\n\n"
            f"Convertissez vers un autre dossier, par exemple :\n"
            f'  python outils/docx_vers_edit.py "{chemin_docx}" '
            f"--dossier ../pieces"
        )

    print(f"Conversion : {chemin_docx.name}")

    texte, rapport = convertir(lire_paragraphes(chemin_docx))

    chemins.dossier_travail.mkdir(parents=True, exist_ok=True)
    io.ecrire_texte_atomique(chemins.edit, texte)

    rapport.afficher()
    print(f"   écrit                {chemins.edit}")

    if rapport.continuations:
        # Un rapport de 49 entrées ne tient pas dans une console : il va dans un
        # fichier, à côté de l'EDIT.txt qu'il commente.
        chemin_rapport = chemins.dossier_travail / "CONVERSION.txt"
        io.ecrire_texte_atomique(chemin_rapport, rapport.texte_des_continuations())
        print(f"   à relire             {chemin_rapport}")
    print()
    print("Étape suivante :")
    print(f'   python -m theatre_editor.main --etape docx --dossier "{base}"')

    return chemins.edit


def _preparer_console() -> None:
    """
    Rend la console capable d'écrire du français.

    La console Windows par défaut est en cp1252, qui ne sait pas écrire les
    guillemets typographiques d'un texte de théâtre. Sans cela, l'utilitaire
    s'interrompt sur un `UnicodeEncodeError` **après** avoir écrit son fichier :
    le travail est fait, mais l'utilisateur voit une trace d'erreur et croit à un
    échec. Le reste du projet tourne dans Colab, en UTF-8, et n'a jamais rencontré
    ce cas.

    Appelée depuis `main()` et **jamais à l'import**. Reconfigurer `sys.stdout`
    au chargement du module en ferait un effet de bord global, subi par tout
    test qui importe ce fichier — y compris ceux qui capturent la sortie
    console pour vérifier un message. Un import ne doit rien changer au
    programme qui l'effectue.
    """
    for flux in (sys.stdout, sys.stderr):
        if hasattr(flux, "reconfigure"):
            flux.reconfigure(encoding="utf-8", errors="replace")


def main(arguments: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(
        description=(
            "Convertit un DOCX déjà mis en forme en EDIT.txt, pour le faire entrer "
            "dans le pipeline à l'étape 4 — sans OCR, sans IA, sans coût."
        )
    )
    analyseur.add_argument("docx", type=Path, help="le document à convertir")
    analyseur.add_argument(
        "--dossier",
        type=Path,
        default=None,
        help="dossier de travail (celui du DOCX par défaut)",
    )

    _preparer_console()

    options = analyseur.parse_args(arguments)

    if not options.docx.is_file():
        print(f"introuvable : {options.docx}", file=sys.stderr)
        return 1

    convertir_fichier(options.docx, options.dossier)

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
