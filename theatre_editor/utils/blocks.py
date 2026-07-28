"""
Logique texte pure du pipeline : découpage, classification, contrôles.

Ce module est **pur** au sens strict, et cette pureté est une garantie
architecturale, pas un hasard :

- aucune lecture ni écriture de fichier ;
- aucun appel réseau ;
- aucune lecture d'horloge ;
- aucun import hors bibliothèque standard et `config`.

C'est ce qui rend intégralement testable, sans clé API ni Google Drive monté,
la logique la plus délicate du projet : la classification d'une ligne en gras
en titre d'acte, titre de scène ou nom de personnage (ARCHITECTURE.md §9.1).

Le point conceptuel central de ce module : **le type d'une ligne en gras n'est
pas une propriété de la ligne, c'est une propriété du document entier.**
`**UN.**` est un acte dans une pièce découpée en parties numérotées, et une
scène dans une pièce qui possède déjà des `ACTE I`. D'où la séparation en deux
temps : `construire_index_structure()` parcourt le document une fois et décide,
puis `classifier_document()` applique ces décisions ligne à ligne.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum

from theatre_editor import config


# ============================================================
# 1. TYPES
# ============================================================


class TypeLigne(str, Enum):
    """
    Nature d'une ligne du fichier EDIT.txt.

    Les six premières valeurs correspondent **exactement** aux clés de
    `config.DEFINITIONS_STYLES` : `docx_export` peut donc convertir un type en
    style sans table de correspondance intermédiaire, et un style oublié
    devient une erreur immédiate plutôt qu'un texte au style par défaut.
    """

    TITRE_ACTE = "titre_acte"
    TITRE_SCENE = "titre_scene"
    DISTRIBUTION = "distribution"
    ENTREE_DISTRIBUTION = "entree_distribution"
    LIEU = "lieu"
    PERSONNAGE = "personnage"
    DIDASCALIE = "didascalie"
    TEXTE = "texte"

    # Types sans style propre.
    SEPARATEUR = "separateur"
    VIDE = "vide"


class Confiance(str, Enum):
    """
    Degré de certitude d'un classement, du plus sûr au plus fragile.

    Exposé à l'utilisateur dans la table d'inspection : c'est ce qui permet de
    ne relire que les quelques labels réellement douteux, au lieu de vérifier
    toute une distribution.
    """

    CERTAINE = "certaine"
    PROBABLE = "probable"
    DEDUITE = "deduite"
    INCERTAINE = "incertaine"


@dataclass(frozen=True)
class Bloc:
    """Groupe de pages consécutives traité en un seul appel API."""

    numero: int
    page_debut: int
    page_fin: int
    contenu: str


@dataclass(frozen=True)
class Run:
    """Fragment homogène de texte à l'intérieur d'un paragraphe."""

    texte: str
    gras: bool = False
    italique: bool = False


@dataclass(frozen=True)
class ClassementLabel:
    """Décision de classification pour un label en gras, et sa justification."""

    label: str
    affichage: str
    type: TypeLigne
    confiance: Confiance
    motif: str
    occurrences: int
    suivi_replique: int


@dataclass(frozen=True)
class LigneClassee:
    """Ligne du document, avec son type et son contenu débarrassé des marqueurs."""

    brut: str
    texte: str
    type: TypeLigne


@dataclass
class IndexStructure:
    """
    Résultat de l'analyse structurelle d'un document entier.

    Attributes:
        classements: label normalisé → décision de classification.
        avertissements: constats destinés au rapport et au journal.
    """

    classements: dict[str, ClassementLabel] = field(default_factory=dict)
    avertissements: list[str] = field(default_factory=list)
    # Indices des lignes appartenant à la liste des rôles, en tête d'ouvrage.
    # Elles reçoivent un style propre : lignes courtes, alignées à gauche, que
    # la justification du corps de texte étirerait d'un bord à l'autre.
    lignes_distribution: frozenset[int] = frozenset()

    def type_de(self, label_normalise: str) -> TypeLigne:
        """
        Retourne le type d'un label.

        Un label inconnu est traité comme un personnage. Ce choix n'est pas
        neutre : le seul classement dont l'erreur est *visible* est celui d'un
        acte, qui déclenche un saut de page. En cas d'inconnu, on préfère donc
        l'erreur invisible.
        """
        classement = self.classements.get(label_normalise)

        return classement.type if classement else TypeLigne.PERSONNAGE

    def affichage_de(self, label_normalise: str) -> str | None:
        """
        Graphie à retenir pour un label, dans tout le document.

        Un même personnage peut apparaître sous plusieurs graphies — « WANG. »
        et « WANG » — selon la disposition de la ligne d'origine. Les rendre
        toutes telles quelles produirait un document irrégulier : on retient
        donc partout la forme la plus fréquente.
        """
        classement = self.classements.get(label_normalise)

        return classement.affichage if classement else None

    def labels_de_type(self, type_ligne: TypeLigne) -> list[ClassementLabel]:
        """Liste les classements d'un type donné, triés par label."""
        return sorted(
            (c for c in self.classements.values() if c.type is type_ligne),
            key=lambda c: c.label,
        )

    @property
    def incertains(self) -> list[ClassementLabel]:
        """Classements à faire relire par un humain."""
        return [
            c
            for c in self.classements.values()
            if c.confiance is Confiance.INCERTAINE
        ]

    def compter(self, type_ligne: TypeLigne) -> int:
        """Nombre de labels distincts d'un type donné."""
        return sum(1 for c in self.classements.values() if c.type is type_ligne)


# ============================================================
# 2. EXPRESSIONS RÉGULIÈRES
# ------------------------------------------------------------
# Compilées une fois : elles sont appliquées des centaines de milliers de
# fois sur un livre entier.
# ============================================================

# Un séparateur de scène : trois astérisques ou plus, seuls sur la ligne.
# Testé AVANT le gras et l'italique, faute de quoi `*****` serait lu comme
# du gras entourant une astérisque.
MOTIF_SEPARATEUR = re.compile(r"^\*{3,}$")

# Une ligne entièrement en gras : **CONTENU**
MOTIF_LIGNE_GRAS = re.compile(r"^\*\*(?P<contenu>.+?)\*\*$")

# Une ligne entièrement en italique : *contenu*
# Le `[^*]` initial empêche de capturer une ligne en gras, dont la forme
# `**X**` satisfait sinon `^\*.*\*$`.
MOTIF_LIGNE_ITALIQUE = re.compile(r"^\*(?P<contenu>[^*].*?)\*$")

# Nom de personnage suivi de sa réplique **sur la même ligne** :
#
#     **LÉA.** Tu penses à quoi ?
#
# C'est ainsi que beaucoup d'éditions imprimées présentent le dialogue, et le
# modèle d'édition reproduit parfois cette disposition malgré la consigne de
# placer le nom seul sur sa ligne.
#
# Sans traitement, la ligne entière est classée comme du texte : aucun
# personnage n'est reconnu, et les astérisques se retrouvent **visibles dans le
# DOCX**. Ce motif permet de dédoubler la ligne (§ `dedoubler_replique_en_ligne`).
MOTIF_REPLIQUE_EN_LIGNE = re.compile(
    r"^\*\*(?P<label>[^*\n]+)\*\*\s+(?P<suite>\S.*)$"
)

# Bornes d'un nom de personnage plausible en tête de réplique.
MIN_LETTRES_REPRISE = 2
MAX_LONGUEUR_REPRISE = 40

# Tiret d'appel séparant le nom de sa réplique chez certains éditeurs :
#
#     PREMIER GARDIEN. – Qu'est-ce qu'un type ferait sur le toit ?
#
# C'est un signe de ponctuation propre à la mise en page, non du texte de
# l'auteur : le conserver le ferait apparaître en tête de chaque réplique.
MOTIF_TIRET_D_APPEL = re.compile(r"^[–—−-]\s*")

# Emphase à l'intérieur d'une ligne. Le gras est la première alternative :
# sur `**mot**`, une alternance qui commencerait par l'italique capturerait
# une chaîne vide entre les deux premières astérisques.
MOTIF_RUN = re.compile(r"\*\*(?P<gras>[^*]+)\*\*|\*(?P<ital>[^*]+)\*")

# Marqueur de page inséré par l'étape 1.
MOTIF_MARQUEUR_PAGE = re.compile(r"^\s*\[PAGE\s+\d+\]\s*$", re.MULTILINE | re.IGNORECASE)
MOTIF_MARQUEUR_PAGE_INLINE = re.compile(r"\[PAGE\s+\d+\]", re.IGNORECASE)
MOTIF_SEPARATEUR_PAGE = re.compile(r"\s*<<<PAGE_BREAK>>>\s*", re.IGNORECASE)

# Découpage devant un marqueur de page, sans le consommer.
MOTIF_AVANT_PAGE = re.compile(r"(?=^\s*\[PAGE\s+\d+\]\s*$)", re.MULTILINE | re.IGNORECASE)

# Styles de numérotation.
MOTIF_ROMAIN = re.compile(r"^[IVXLCDM]+$")
MOTIF_ARABE = re.compile(r"^\d+$")

# Ponctuation finale retirée lors de la normalisation d'un label.
MOTIF_PONCTUATION_FINALE = re.compile(r"[.:;,!?\s]+$")

# Valeur numérique des nombres écrits, pour la détection de remise à zéro.
_VALEURS_ECRITES: dict[str, int] = {
    "UN": 1, "UNE": 1, "PREMIER": 1, "PREMIERE": 1,
    "DEUX": 2, "SECOND": 2, "SECONDE": 2, "DEUXIEME": 2,
    "TROIS": 3, "TROISIEME": 3,
    "QUATRE": 4, "QUATRIEME": 4,
    "CINQ": 5, "CINQUIEME": 5,
    "SIX": 6, "SIXIEME": 6,
    "SEPT": 7, "SEPTIEME": 7,
    "HUIT": 8, "HUITIEME": 8,
    "NEUF": 9, "NEUVIEME": 9,
    "DIX": 10, "DIXIEME": 10,
    "ONZE": 11, "ONZIEME": 11,
    "DOUZE": 12, "DOUZIEME": 12,
    "TREIZE": 13, "TREIZIEME": 13,
    "QUATORZE": 14, "QUATORZIEME": 14,
    "QUINZE": 15, "QUINZIEME": 15,
    "SEIZE": 16, "SEIZIEME": 16,
    "VINGT": 20, "TRENTE": 30,
}

_VALEURS_ROMAINES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}

# Styles de numérotation considérés comme relevant du premier niveau.
_STYLES_NIVEAU_SUPERIEUR = frozenset({"romain", "ecrit"})


# ============================================================
# 3. NORMALISATION
# ============================================================


def sans_accents(texte: str) -> str:
    """Retire les diacritiques (« SCÈNE » → « SCENE »)."""
    decompose = unicodedata.normalize("NFD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c))


def normaliser_label(texte: str) -> str:
    """
    Réduit un label à sa forme canonique de comparaison.

    « **Acte premier.** », « ACTE PREMIER » et « Acte  Premier : » donnent tous
    « ACTE PREMIER ». Sans cette normalisation, un lexique devrait énumérer
    toutes les variantes de casse, d'accentuation et de ponctuation finale.
    """
    resultat = texte.strip().strip("*").strip()
    resultat = sans_accents(resultat).upper()
    resultat = MOTIF_PONCTUATION_FINALE.sub("", resultat)

    return re.sub(r"\s+", " ", resultat).strip()


def normaliser_pour_comptage(texte: str) -> str:
    """
    Prépare un texte pour une comparaison de volume entre entrée et sortie.

    Neutralise les marqueurs techniques et les différences d'espacement, qui
    n'ont rien à voir avec une perte de contenu. C'est ce qui rend
    `RATIO_MINIMAL_LONGUEUR` interprétable : une édition fidèle doit se situer
    autour de 1,00, non de 0,80.
    """
    resultat = MOTIF_SEPARATEUR_PAGE.sub(" ", texte)
    resultat = MOTIF_MARQUEUR_PAGE_INLINE.sub(" ", resultat)

    return re.sub(r"\s+", " ", resultat).strip()


def normaliser_pour_comparaison(texte: str) -> str:
    """
    Prépare un texte pour une comparaison **entre étapes** (OCR ↔ EDIT).

    Diffère de `normaliser_pour_comptage()` sur un point décisif : les
    astérisques sont retirées. L'étape 2 ajoute légitimement `**` autour de
    chaque nom de personnage et `*` autour de chaque didascalie ; sur un livre
    comportant deux mille répliques, cela représente près de dix mille
    caractères. Sans cette neutralisation, `EDIT.txt` paraîtrait plus long que
    `OCR.txt` alors même qu'il en aurait perdu des passages.
    """
    return re.sub(r"\s+", " ", normaliser_pour_comptage(texte).replace("*", "")).strip()


# ============================================================
# 4. DÉCOUPAGE EN PAGES ET EN BLOCS
# ============================================================


def decouper_en_pages(texte: str) -> list[str]:
    """
    Découpe un fichier OCR en pages.

    Trois stratégies, par ordre de fiabilité décroissante :

    1. le séparateur `<<<PAGE_BREAK>>>`, écrit par l'étape 1 ;
    2. à défaut, les marqueurs `[PAGE X]`, qui restent exploitables si le
       fichier a été recomposé à la main ;
    3. à défaut, le texte entier comme page unique.

    Le découpage est **déterministe** : c'est ce qui garantit que le bloc 12
    d'hier correspond exactement au bloc 12 recalculé aujourd'hui, condition
    de correction de la reprise après interruption.
    """
    if MOTIF_SEPARATEUR_PAGE.search(texte):
        pages = MOTIF_SEPARATEUR_PAGE.split(texte)
    elif MOTIF_MARQUEUR_PAGE.search(texte):
        pages = MOTIF_AVANT_PAGE.split(texte)
    else:
        pages = [texte]

    return [page.strip() for page in pages if page and page.strip()]


def former_blocs(pages: list[str], pages_par_bloc: int | None = None) -> list[Bloc]:
    """
    Regroupe les pages en blocs, sans modifier leur contenu.

    Args:
        pages: pages issues de `decouper_en_pages()`.
        pages_par_bloc: `config.PAGES_PAR_BLOC` par défaut.

    Raises:
        ValueError: si `pages_par_bloc` est nul ou négatif, ce qui produirait
            une boucle infinie.
    """
    taille = pages_par_bloc if pages_par_bloc is not None else config.PAGES_PAR_BLOC

    if taille < 1:
        raise ValueError(f"pages_par_bloc doit valoir au moins 1, reçu {taille}.")

    blocs: list[Bloc] = []

    for debut in range(0, len(pages), taille):
        fin = min(debut + taille, len(pages))

        blocs.append(
            Bloc(
                numero=len(blocs) + 1,
                page_debut=debut + 1,
                page_fin=fin,
                contenu=config.SEPARATEUR_PAGE.join(pages[debut:fin]),
            )
        )

    return blocs


def fenetre_fin(texte: str, nombre_lignes: int) -> tuple[str, str]:
    """
    Isole les dernières lignes d'un texte.

    Returns:
        `(prefixe, extrait)`, tel que leur recollage restitue le texte
        d'origine. Le préfixe est vide si le texte est plus court que la
        fenêtre demandée.
    """
    lignes = texte.split("\n")

    if len(lignes) <= nombre_lignes:
        return "", texte

    return "\n".join(lignes[:-nombre_lignes]), "\n".join(lignes[-nombre_lignes:])


def fenetre_debut(texte: str, nombre_lignes: int) -> tuple[str, str]:
    """
    Isole les premières lignes d'un texte.

    Returns:
        `(extrait, suffixe)`, tel que leur recollage restitue le texte
        d'origine.
    """
    lignes = texte.split("\n")

    if len(lignes) <= nombre_lignes:
        return texte, ""

    return "\n".join(lignes[:nombre_lignes]), "\n".join(lignes[nombre_lignes:])


def assembler(textes: list[str]) -> str:
    """Assemble des blocs en un document, séparés par une ligne vide."""
    morceaux = [texte.strip() for texte in textes if texte and texte.strip()]

    return "\n\n".join(morceaux).strip() + "\n" if morceaux else ""


# ============================================================
# 5. NETTOYAGE ET CONTRÔLES DE SORTIE
# ============================================================


def nettoyer_enveloppe(texte: str) -> str:
    """
    Retire les enveloppes techniques manifestes d'une réponse de modèle.

    Ne touche jamais au contenu littéraire : uniquement les blocs de code dont
    un modèle entoure parfois sa réponse, et les délimiteurs de source qu'il
    peut recopier.
    """
    resultat = texte.strip()

    if resultat.startswith("```"):
        lignes = resultat.splitlines()

        # La première ligne porte l'ouverture, éventuellement suivie d'un
        # nom de langage (```markdown).
        lignes = lignes[1:]

        if lignes and lignes[-1].strip() == "```":
            lignes = lignes[:-1]

        resultat = "\n".join(lignes).strip()

    for delimiteur in (config.DELIM_SOURCE_DEBUT, config.DELIM_SOURCE_FIN):
        resultat = resultat.replace(delimiteur, "")

    return resultat.strip()


# Emphase Markdown ajoutée par un modèle : `**gras**`, ou une ligne entièrement
# en `*italique*`.
#
# Le motif est **précis à dessein**. Une version antérieure signalait la moindre
# astérisque, ce qui produisait un faux positif sur toute page dont le texte
# imprimé en contient une — un séparateur `*  *  *`, un appel de note. La page
# était alors marquée suspecte et retranscrite à chaque exécution, donc repayée
# sans fin, puisqu'une astérisque imprimée ne disparaîtra jamais.
#
# Ce qu'il s'agit de détecter, c'est l'application de la convention
# typographique de l'étape 2, non la présence d'un caractère.
MOTIF_EMPHASE_MARKDOWN = re.compile(
    r"\*\*[^*\n]+\*\*"  # **gras**
    r"|^\*[^*\n]+\*$",  # ligne entièrement en italique
    re.MULTILINE,
)

# Caractères trahissant un encodage perdu ou une extraction défaillante.
CARACTERES_SUSPECTS = frozenset("�\x00\x01\x02\x03\x04\x05\x06\x07\x0b\x0c")

# Voyelles accentuées et cédille du français.
LETTRES_ACCENTUEES = frozenset("àâäéèêëîïôöùûüÿçÀÂÄÉÈÊËÎÏÔÖÙÛÜŸÇ")

MOTIF_LIGNES_VIDES_EXCESSIVES = re.compile(r"\n{3,}")


def normaliser_couche_texte(texte: str) -> str:
    """
    Nettoie une couche texte extraite d'un PDF.

    Trois corrections déterministes et sans perte :

    - les **ligatures** typographiques (`ﬁ`, `ﬂ`, `ﬀ`…) sont défaites. Elles sont
      fréquentes dans une couche texte et casseraient la recherche de mots comme
      la comparaison de l'étape 3 ;
    - les espaces en fin de ligne sont retirés ;
    - les successions de trois lignes vides ou plus sont ramenées à deux, une
      extraction produisant souvent des blancs surnuméraires.

    Aucun caractère de l'auteur n'est modifié : on ne normalise pas en NFKC, qui
    transformerait par exemple les points de suspension « … » en trois points et
    altérerait donc la ponctuation.
    """
    resultat = texte

    for ligature, equivalent in config.LIGATURES.items():
        if ligature != equivalent:
            resultat = resultat.replace(ligature, equivalent)

    resultat = "\n".join(ligne.rstrip() for ligne in resultat.split("\n"))
    resultat = MOTIF_LIGNES_VIDES_EXCESSIVES.sub("\n\n", resultat)

    return resultat.strip()


def evaluer_couche_texte(texte: str) -> list[str]:
    """
    Juge si une couche texte extraite d'un PDF est exploitable.

    Le sens de la prudence est déterminant, et il n'est pas symétrique.
    Réutiliser à tort une mauvaise couche texte dégrade tout le livre — l'étape 2
    ayant pour consigne de ne pas réécrire l'auteur, une faute d'extraction
    devient définitive. Rasteriser à tort une bonne couche texte ne coûte que des
    jetons. Ces contrôles sont donc **sévères** : le doute renvoie à l'OCR Vision.

    Returns:
        Les raisons de refuser la couche texte. Liste vide : elle est utilisable.
    """
    if not texte or not texte.strip():
        return ["aucune couche texte"]

    nu = texte.strip()

    if len(nu) < config.MIN_CARACTERES_COUCHE_TEXTE:
        return [
            f"couche texte trop courte : {len(nu)} caractères "
            f"(minimum {config.MIN_CARACTERES_COUCHE_TEXTE})"
        ]

    raisons: list[str] = []

    non_blancs = [caractere for caractere in nu if not caractere.isspace()]

    if not non_blancs:
        return ["couche texte sans caractère exploitable"]

    lettres = [caractere for caractere in non_blancs if caractere.isalpha()]
    ratio_alphabetique = len(lettres) / len(non_blancs)

    if ratio_alphabetique < config.MIN_RATIO_ALPHABETIQUE:
        raisons.append(
            f"trop peu de lettres : {ratio_alphabetique:.0%} "
            f"(minimum {config.MIN_RATIO_ALPHABETIQUE:.0%})"
        )

    suspects = sum(1 for caractere in nu if caractere in CARACTERES_SUSPECTS)
    ratio_suspects = suspects / len(nu)

    if ratio_suspects > config.MAX_RATIO_CARACTERES_SUSPECTS:
        raisons.append(
            f"caractères de remplacement ou de contrôle : {ratio_suspects:.1%}"
        )

    if lettres:
        accents = sum(1 for caractere in lettres if caractere in LETTRES_ACCENTUEES)
        ratio_accents = accents / len(lettres)

        if ratio_accents < config.MIN_RATIO_ACCENTS:
            raisons.append(
                "aucun accent ou presque : l'OCR d'origine a probablement "
                f"dépouillé le texte ({ratio_accents:.2%})"
            )

    return raisons


def verifier_page_ocr(texte: str) -> list[str]:
    """
    Contrôle mécanique d'une page transcrite.

    Les critères diffèrent de ceux de `verifier_sortie()` : l'OCR doit produire
    du texte **nu**. Un marqueur de page ou une astérisque y sont donc des
    anomalies, alors que l'édition les produit légitimement. Il n'y a pas non
    plus de ratio de longueur à calculer, l'entrée étant une image.

    Returns:
        Liste d'avertissements, vide si la page paraît saine.
    """
    avertissements: list[str] = []

    for motif in config.MOTIFS_INTERDITS_OCR:
        if re.search(motif, texte, flags=re.MULTILINE):
            avertissements.append(f"motif indésirable détecté : {motif}")

    # La marque d'illisibilité est la seule emphase autorisée : on la retire
    # avant de chercher de la mise en forme ajoutée.
    sans_marque = texte.replace(config.MARQUE_ILLISIBLE, "")

    if MOTIF_EMPHASE_MARKDOWN.search(sans_marque):
        avertissements.append(
            "mise en forme ajoutée : la transcription doit être en texte nu"
        )

    return avertissements


def verifier_sortie(source: str, sortie: str) -> list[str]:
    """
    Contrôle mécanique d'une sortie de modèle.

    Trois filets indépendants du bon vouloir du modèle (ARCHITECTURE.md §9.4) :
    volume conservé, absence de motifs interdits, parité des astérisques.

    Returns:
        Liste d'avertissements. Une liste vide signifie qu'aucun problème
        évident n'a été détecté — ce qui ne prouve pas la fidélité, mais
        écarte les défaillances grossières.
    """
    avertissements: list[str] = []

    if not sortie or not sortie.strip():
        return ["sortie vide"]

    source_normalisee = normaliser_pour_comptage(source)
    sortie_normalisee = normaliser_pour_comptage(sortie)

    if source_normalisee:
        ratio = len(sortie_normalisee) / len(source_normalisee)

        if ratio < config.RATIO_MINIMAL_LONGUEUR:
            avertissements.append(
                f"sortie trop courte : ratio {ratio:.2f} "
                f"(seuil {config.RATIO_MINIMAL_LONGUEUR:.2f})"
            )

    for motif in config.MOTIFS_INTERDITS:
        if re.search(motif, sortie, flags=re.MULTILINE):
            avertissements.append(f"motif indésirable détecté : {motif}")

    # Une astérisque orpheline casse la convention typographique, et donc
    # l'étape 4 : mieux vaut la détecter ici que dans le DOCX.
    if sortie.count("*") % 2 != 0:
        avertissements.append("nombre impair d'astérisques")

    return avertissements


# ============================================================
# 5 bis. PASSE DE RACCORD
# ============================================================

# Réponse attendue du modèle de raccord. Le `.*?` central absorbe un éventuel
# retour à la ligne ou commentaire entre les deux blocs.
MOTIF_RACCORD = re.compile(
    re.escape(config.DELIM_RACCORD_GAUCHE)
    + r"(?P<gauche>.*?)"
    + re.escape(config.DELIM_RACCORD_GAUCHE_FIN)
    + r".*?"
    + re.escape(config.DELIM_RACCORD_DROIT)
    + r"(?P<droit>.*?)"
    + re.escape(config.DELIM_RACCORD_DROIT_FIN),
    re.DOTALL,
)


def extraire_blocs_raccord(texte: str) -> tuple[str, str]:
    """
    Extrait les deux extraits corrigés d'une réponse de raccord.

    Args:
        texte: réponse brute du modèle.

    Returns:
        `(extrait gauche, extrait droit)`, débarrassés de leurs délimiteurs.

    Raises:
        ValueError: si le format délimité n'est pas respecté. L'appelant doit
            alors conserver les extraits d'origine : mieux vaut une jonction non
            corrigée qu'une jonction corrompue.
    """
    correspondance = MOTIF_RACCORD.search(texte)

    if correspondance is None:
        raise ValueError(
            "format de raccord non respecté : délimiteurs "
            f"{config.DELIM_RACCORD_GAUCHE} / {config.DELIM_RACCORD_DROIT} "
            "introuvables dans la réponse"
        )

    return (
        correspondance.group("gauche").strip(),
        correspondance.group("droit").strip(),
    )


def verifier_raccord(avant: str, apres: str) -> list[str]:
    """
    Vérifie qu'un extrait raccordé n'a pas dérivé de son original.

    Garde-fou essentiel : la passe de raccord réécrit les fichiers **en place**.
    Un modèle qui résumerait, réécrirait ou ne rendrait qu'une partie de
    l'extrait détruirait donc du texte définitivement, sans possibilité de
    retour.

    Un raccord légitime ne fait que ressouder un mot, rétablir une ponctuation
    ou supprimer un doublon : la longueur bouge à peine. Hors des bornes
    configurées, la correction doit être refusée.

    Returns:
        Liste d'avertissements. Vide si la correction est acceptable.
    """
    avertissements: list[str] = []

    if not apres.strip():
        return ["extrait raccordé vide"]

    reference = len(avant.strip())

    if reference:
        ratio = len(apres.strip()) / reference

        if ratio < config.RATIO_MINIMAL_RACCORD:
            avertissements.append(
                f"extrait raccourci au raccord : ratio {ratio:.2f} "
                f"(minimum {config.RATIO_MINIMAL_RACCORD:.2f})"
            )
        elif ratio > config.RATIO_MAXIMAL_RACCORD:
            avertissements.append(
                f"extrait allongé au raccord : ratio {ratio:.2f} "
                f"(maximum {config.RATIO_MAXIMAL_RACCORD:.2f})"
            )

    return avertissements


def recoller_gauche(prefixe: str, extrait: str) -> str:
    """Reconstitue un bloc gauche à partir de son préfixe et de son extrait corrigé."""
    parties = [partie for partie in (prefixe.rstrip(), extrait.strip()) if partie]

    return "\n".join(parties).strip() + "\n"


def recoller_droite(extrait: str, suffixe: str) -> str:
    """Reconstitue un bloc droit à partir de son extrait corrigé et de son suffixe."""
    parties = [partie for partie in (extrait.strip(), suffixe.lstrip()) if partie]

    return "\n".join(parties).strip() + "\n"


# ============================================================
# 6. FORME DES LIGNES
# ============================================================


def est_separateur(ligne: str) -> bool:
    """Vrai si la ligne est un séparateur de scène (`***`)."""
    return bool(MOTIF_SEPARATEUR.match(ligne.strip()))


def contenu_gras(ligne: str) -> str | None:
    """Retourne le contenu d'une ligne entièrement en gras, sinon None."""
    if est_separateur(ligne):
        return None

    correspondance = MOTIF_LIGNE_GRAS.match(ligne.strip())

    return correspondance.group("contenu").strip() if correspondance else None


def contenu_italique(ligne: str) -> str | None:
    """Retourne le contenu d'une ligne entièrement en italique, sinon None."""
    if est_separateur(ligne):
        return None

    correspondance = MOTIF_LIGNE_ITALIQUE.match(ligne.strip())

    return correspondance.group("contenu").strip() if correspondance else None


@dataclass(frozen=True)
class RepliqueEnLigne:
    """Nom de personnage, didascalie éventuelle et réplique extraits d'une ligne."""

    nom: str
    didascalie: str | None
    replique: str


def _est_nom_de_personnage(label: str) -> bool:
    """
    Vrai si un label peut être un nom de personnage en tête de réplique.

    Exige que **toutes** les lettres soient en capitales. Sans cela, une simple
    emphase — `**Attention** dit-il.` — serait prise pour un rôle, ce qui
    fabriquerait des personnages inexistants.
    """
    lettres = [caractere for caractere in label if caractere.isalpha()]

    if len(lettres) < MIN_LETTRES_REPRISE or len(label) > MAX_LONGUEUR_REPRISE:
        return False

    return all(caractere.isupper() for caractere in lettres)


def dedoubler_replique_en_ligne(ligne: str) -> RepliqueEnLigne | None:
    """
    Sépare un nom de personnage de sa réplique lorsqu'ils partagent une ligne.

    Trois dispositions observées dans des éditions réelles sont reconnues :

    | Sur la page | Résultat |
    |---|---|
    | `LÉA. Tu penses à quoi ?` | nom, réplique |
    | `PREMIER GARDIEN. – Qu'est-ce…` | nom, réplique (tiret d'appel retiré) |
    | `LES DIEUX, souriant. Bien sûr.` | nom, didascalie, réplique |

    Le tiret cadratin qui suit le nom chez certains éditeurs est un **signe de
    ponctuation d'appel**, non du texte de l'auteur : le conserver le ferait
    apparaître en tête de chaque réplique du document final.

    La didascalie intercalée dans l'appel — fréquente chez Brecht — est extraite
    séparément, car le style du nom de personnage est en gras et ne doit pas
    s'appliquer à elle.

    Returns:
        Les trois parties, ou None si la ligne n'a pas cette forme.
    """
    correspondance = MOTIF_REPLIQUE_EN_LIGNE.match(ligne.strip())

    if correspondance is None:
        return None

    label = correspondance.group("label").strip()
    didascalie: str | None = None

    # `LES DIEUX, souriant.` — la partie qui suit la virgule est une didascalie.
    if "," in label:
        avant, apres = label.split(",", 1)

        if _est_nom_de_personnage(avant.strip()) and apres.strip():
            label = avant.strip()
            didascalie = apres.strip()

    if not _est_nom_de_personnage(label):
        return None

    replique = MOTIF_TIRET_D_APPEL.sub("", correspondance.group("suite").strip())

    if not replique:
        return None

    return RepliqueEnLigne(nom=label, didascalie=didascalie, replique=replique)


def est_ligne_de_replique(ligne: str) -> bool:
    """
    Vrai si la ligne ressemble à du texte parlé.

    Critère décisif de la règle 5 : un nom de personnage est suivi d'une
    réplique, alors qu'un titre est suivi d'un lieu en italique ou d'un autre
    label en gras.
    """
    nue = ligne.strip()

    if not nue or est_separateur(nue):
        return False

    return contenu_gras(nue) is None and contenu_italique(nue) is None


# ============================================================
# 7. NUMÉROTATION
# ============================================================


def style_numerotation(label: str) -> str | None:
    """
    Identifie le style de numérotation d'un label, s'il en est un.

    Returns:
        « romain », « arabe », « ecrit », ou None si le label n'est pas un pur
        jeton de numérotation.
    """
    if not label:
        return None

    if label in config.NOMBRES_ECRITS:
        return "ecrit"

    if MOTIF_ROMAIN.match(label):
        return "romain"

    if MOTIF_ARABE.match(label):
        return "arabe"

    return None


def est_jeton_numerotation(label: str) -> bool:
    """Vrai si le label n'est qu'un numéro (« UN », « II », « 3 »)."""
    return style_numerotation(label) is not None


def _valeur_romaine(label: str) -> int:
    """Convertit un nombre romain en entier (soustractions comprises)."""
    total = 0
    precedent = 0

    for caractere in reversed(label):
        valeur = _VALEURS_ROMAINES[caractere]
        total += -valeur if valeur < precedent else valeur
        precedent = max(precedent, valeur)

    return total


def valeur_numerotation(label: str) -> int | None:
    """Valeur entière d'un jeton de numérotation, ou None."""
    style = style_numerotation(label)

    if style == "arabe":
        return int(label)

    if style == "romain":
        return _valeur_romaine(label)

    if style == "ecrit":
        return _VALEURS_ECRITES.get(label)

    return None


# ============================================================
# 8. RECENSEMENT DE LA DISTRIBUTION
# ============================================================


def _ressemble_a_un_nom(segment: str) -> bool:
    """
    Vrai si un segment de ligne, dans une liste de rôles, peut être un nom.

    Le critère est **volontairement permissif**, et cela ne présente aucun
    risque. Les noms relevés ici ne servent qu'à *amorcer* la reconnaissance :
    la règle 4 ne les consulte que pour un label qui apparaît réellement en
    gras dans le texte. Un intrus dans cette liste — « La scène est à
    Messine. » — ne peut donc pas créer un personnage inexistant, il reste un
    amorçage inutilisé.

    Exiger une majorité de capitales, comme le faisait une version antérieure,
    écartait en revanche les distributions imprimées en **casse de titre** :
    « Roberto Zucco. », « Sa mère. », « La gamine. » — soit tout l'amorçage
    d'une édition comme celle de Koltès.
    """
    lettres = [caractere for caractere in segment if caractere.isalpha()]

    if len(lettres) < 2 or len(segment) > MAX_LONGUEUR_LABEL:
        return False

    # Un nom de rôle commence par une capitale, en capitales comme en casse de
    # titre. Cela écarte une ligne de prose reprise en cours de phrase.
    return segment[0].isupper()


def recenser_personnages(texte: str) -> set[str]:
    """
    Relève la distribution figurant en tête d'ouvrage.

    Beaucoup d'éditions ouvrent sur une liste de rôles (« PERSONNAGES »).
    Quand elle existe, c'est le signal le plus fiable dont on dispose : il
    identifie même les rôles qui n'ont qu'une seule réplique, que les critères
    statistiques classeraient à tort.

    Returns:
        Ensemble de labels normalisés. Vide si aucune distribution n'est
        trouvée, ce qui est un cas parfaitement normal.
    """
    noms, _ = recenser_distribution(texte)

    return noms


def recenser_distribution(texte: str) -> tuple[set[str], frozenset[int]]:
    """
    Relève la distribution et repère les lignes qu'elle occupe.

    Les indices servent à l'étape 4 : les entrées d'une liste de rôles reçoivent
    un style propre, aligné à gauche, qu'une justification du corps de texte
    étirerait d'un bord à l'autre de la page.

    Returns:
        `(noms normalisés, indices des lignes de la liste)`.
    """
    lignes = texte.split("\n")

    for index, ligne in enumerate(lignes):
        if normaliser_label(ligne) not in config.ETIQUETTES_DISTRIBUTION:
            continue

        # Une seule distribution par ouvrage : la première rencontrée.
        return _lire_distribution(lignes, index + 1)

    return set(), frozenset()


def _lire_distribution(
    lignes: list[str],
    depart: int,
) -> tuple[set[str], frozenset[int]]:
    """Lit les lignes suivant une étiquette de distribution."""
    noms: set[str] = set()
    indices: set[int] = set()
    vides_consecutives = 0

    fin = min(depart + config.MAX_LIGNES_DISTRIBUTION, len(lignes))

    for decalage, ligne in enumerate(lignes[depart:fin]):
        nue = ligne.strip()

        # Deux lignes vides d'affilée : la liste est terminée.
        if not nue:
            vides_consecutives += 1
            if vides_consecutives >= 2:
                break
            continue

        vides_consecutives = 0

        # Un séparateur ou un titre marque la fin de la distribution.
        if est_separateur(nue):
            break

        label_gras = contenu_gras(nue)
        if label_gras is not None:
            normalise = normaliser_label(label_gras)
            if _correspond_lexique(normalise, config.LEXIQUE_ACTE) or _correspond_lexique(
                normalise, config.LEXIQUE_SCENE
            ):
                break

        # Toute ligne du bloc appartient à la liste, et reçoit donc son style.
        # La position suffit à le décider : inutile de reconnaître un nom pour
        # savoir qu'une ligne fait partie de la distribution.
        indices.add(depart + decalage)

        # « JAN, jeune homme » → « JAN ». Le nom, lui, n'est retenu comme
        # amorçage que s'il en a l'allure.
        segment = re.split(r"[,:(–—-]", nue.strip("*"), maxsplit=1)[0].strip()

        if _ressemble_a_un_nom(segment):
            noms.add(normaliser_label(segment))

    return noms, frozenset(indices)


# ============================================================
# 9. CONSTRUCTION DE L'INDEX DE STRUCTURE
# ============================================================


def _correspond_lexique(label: str, lexique: frozenset[str]) -> bool:
    """
    Vrai si l'un des mots du label figure dans le lexique.

    On teste chaque mot, et non seulement le premier : le français place
    l'ordinal indifféremment avant ou après (« ACTE PREMIER », mais aussi
    « PREMIÈRE PARTIE »).
    """
    return any(mot in lexique for mot in label.split())


@dataclass
class _Observation:
    """Statistiques brutes relevées pour un label, avant toute décision."""

    affichage: str
    occurrences: int = 0
    suivi_replique: int = 0
    premier_index: int = 0
    # Formes rencontrées et leur fréquence. Un même personnage peut s'écrire
    # « WANG. » ou « WANG » selon qu'il portait une didascalie d'appel : le
    # document final doit retenir une seule forme, la plus fréquente.
    formes: dict[str, int] = field(default_factory=dict)

    def enregistrer_forme(self, forme: str) -> None:
        """Compte une graphie rencontrée pour ce label."""
        self.formes[forme] = self.formes.get(forme, 0) + 1

    @property
    def forme_dominante(self) -> str:
        """Graphie la plus fréquente, à retenir pour tout le document."""
        if not self.formes:
            return self.affichage

        return max(sorted(self.formes), key=lambda forme: self.formes[forme])


def _collecter_labels(texte: str) -> dict[str, _Observation]:
    """
    Relève tous les labels en gras du document et leurs statistiques.

    Une seule passe, en regardant pour chaque label la première ligne non vide
    qui le suit, afin de savoir s'il introduit une réplique.
    """
    lignes = texte.split("\n")
    observations: dict[str, _Observation] = {}

    for index, ligne in enumerate(lignes):
        contenu = contenu_gras(ligne)
        replique_immediate = False

        if contenu is None:
            # Le nom peut partager sa ligne avec la réplique : dans ce cas, la
            # réplique est là, sur la même ligne.
            dedouble = dedoubler_replique_en_ligne(ligne)

            if dedouble is None:
                continue

            contenu = dedouble.nom
            replique_immediate = True

        label = normaliser_label(contenu)

        if not label:
            continue

        observation = observations.setdefault(
            label, _Observation(affichage=contenu.strip(), premier_index=index)
        )
        observation.occurrences += 1
        observation.enregistrer_forme(contenu.strip())

        if replique_immediate or _suit_une_replique(lignes, index + 1):
            observation.suivi_replique += 1

    return observations


def _suit_une_replique(lignes: list[str], depart: int) -> bool:
    """Vrai si la première ligne non vide à partir de `depart` est une réplique."""
    for ligne in lignes[depart:]:
        if not ligne.strip():
            continue

        return est_ligne_de_replique(ligne)

    return False


def construire_index_structure(
    texte: str,
    *,
    personnages_forces: frozenset[str] | None = None,
    titres_acte_forces: frozenset[str] | None = None,
    titres_scene_forces: frozenset[str] | None = None,
    seuil_occurrences: int | None = None,
) -> IndexStructure:
    """
    Analyse un document et décide du type de chaque label en gras.

    Applique la règle de décision ordonnée de ARCHITECTURE.md §9.1, puis la
    passe d'inférence de hiérarchie pour les titres purement numérotés.

    L'ordre des règles est le cœur de la méthode : on mène avec les signaux
    non ambigus (surcharge, lexique, numérotation, distribution) et l'on ne
    recourt aux statistiques qu'ensuite. Un simple comptage d'occurrences
    placé en tête classerait « **LE MESSAGER.** », personnage à réplique
    unique, comme un titre — et lui infligerait un saut de page.

    Args:
        texte: contenu de EDIT.txt.
        personnages_forces: surcharges, `config` par défaut.
        titres_acte_forces: surcharges, `config` par défaut.
        titres_scene_forces: surcharges, `config` par défaut.
        seuil_occurrences: `config.SEUIL_OCCURRENCES_PERSONNAGE` par défaut.

    Returns:
        L'index, comprenant les classements et les avertissements à relayer.
    """
    forces_personnage = _defaut(personnages_forces, config.PERSONNAGES_FORCES)
    forces_acte = _defaut(titres_acte_forces, config.TITRES_ACTE_FORCES)
    forces_scene = _defaut(titres_scene_forces, config.TITRES_SCENE_FORCES)
    seuil = _defaut(seuil_occurrences, config.SEUIL_OCCURRENCES_PERSONNAGE)

    observations = _collecter_labels(texte)
    distribution, lignes_distribution = recenser_distribution(texte)

    index = IndexStructure(lignes_distribution=lignes_distribution)

    # Titres purement numérotés : ce sont des titres certains, mais dont le
    # niveau ne peut être décidé qu'au vu du document entier (passe C).
    a_resoudre: list[str] = []

    for label, observation in observations.items():
        decision = _appliquer_regles(
            label=label,
            observation=observation,
            distribution=distribution,
            forces_personnage=forces_personnage,
            forces_acte=forces_acte,
            forces_scene=forces_scene,
            seuil=seuil,
        )

        if decision is None:
            a_resoudre.append(label)
            continue

        index.classements[label] = decision

    _resoudre_niveaux(index, observations, a_resoudre)
    _ajouter_avertissements(index, distribution)

    return index


def _defaut(valeur, repli):
    """Retourne `valeur` si elle est fournie, sinon `repli`."""
    return repli if valeur is None else valeur


def _appliquer_regles(
    *,
    label: str,
    observation: _Observation,
    distribution: set[str],
    forces_personnage: frozenset[str],
    forces_acte: frozenset[str],
    forces_scene: frozenset[str],
    seuil: int,
) -> ClassementLabel | None:
    """
    Applique les règles 0 à 6 à un label.

    Returns:
        Le classement, ou None si le label relève de la passe C (règles 3 et 7).
    """

    def classer(type_ligne: TypeLigne, confiance: Confiance, motif: str) -> ClassementLabel:
        return ClassementLabel(
            label=label,
            affichage=observation.forme_dominante,
            type=type_ligne,
            confiance=confiance,
            motif=motif,
            occurrences=observation.occurrences,
            suivi_replique=observation.suivi_replique,
        )

    # Règle 0 — surcharges manuelles, prioritaires sur tout le reste.
    if label in forces_personnage:
        return classer(TypeLigne.PERSONNAGE, Confiance.CERTAINE, "surcharge manuelle")

    if label in forces_acte:
        return classer(TypeLigne.TITRE_ACTE, Confiance.CERTAINE, "surcharge manuelle")

    if label in forces_scene:
        return classer(TypeLigne.TITRE_SCENE, Confiance.CERTAINE, "surcharge manuelle")

    # Règle 0 bis — en-tête de distribution.
    #
    # Sans cette règle, « **PERSONNAGES** » serait classé comme un rôle : la
    # ligne est en gras et la première ligne qui la suit (« JAN, le frère »)
    # a la forme d'une réplique, ce qui déclenche la règle 5.
    #
    # Le classer comme titre d'acte serait pire encore : `a_acte_lexical`
    # deviendrait vrai et la passe C basculerait tous les titres numérotés
    # en scènes. D'où un type propre, neutre vis-à-vis de la hiérarchie.
    if label in config.ETIQUETTES_DISTRIBUTION:
        return classer(
            TypeLigne.DISTRIBUTION, Confiance.CERTAINE, "en-tête de distribution"
        )

    # Règles 1 et 2 — lexique explicite.
    if _correspond_lexique(label, config.LEXIQUE_ACTE):
        return classer(TypeLigne.TITRE_ACTE, Confiance.CERTAINE, "lexique acte")

    if _correspond_lexique(label, config.LEXIQUE_SCENE):
        return classer(TypeLigne.TITRE_SCENE, Confiance.CERTAINE, "lexique scène")

    # Règle 3 — pur jeton de numérotation : titre certain, niveau à déterminer.
    if est_jeton_numerotation(label):
        return None

    # Règle 4 — présent dans la distribution : le meilleur signal disponible.
    if label in distribution:
        return classer(TypeLigne.PERSONNAGE, Confiance.CERTAINE, "distribution")

    # Règle 5 — introduit une réplique. Attrape les rôles à réplique unique.
    if observation.suivi_replique >= 1:
        return classer(TypeLigne.PERSONNAGE, Confiance.PROBABLE, "suivi d'une réplique")

    # Règle 6 — récurrent : un titre n'apparaît normalement qu'une fois.
    if observation.occurrences >= seuil:
        return classer(
            TypeLigne.PERSONNAGE,
            Confiance.PROBABLE,
            f"récurrent ({observation.occurrences} occurrences)",
        )

    # Règle 7 — aucun signal exploitable.
    #
    # Par défaut : personnage. Ce choix suit le même principe que
    # `IndexStructure.type_de()` — préférer l'erreur invisible. Le cas typique
    # est un rôle dont l'unique intervention est une didascalie (« LA VOIX »
    # suivie de « *Silence.* ») : fréquent au théâtre contemporain.
    #
    # Classer ces labels comme actes, comme le faisait une version antérieure,
    # leur infligeait un saut de page — soit l'erreur la plus voyante possible
    # pour le cas où l'on sait le moins de choses. À l'inverse, un vrai titre
    # rendu en style personnage reste centré et gras : le défaut passe
    # inaperçu. Dans les deux sens, la dégradation est donc bénigne.
    return classer(
        TypeLigne.PERSONNAGE,
        Confiance.INCERTAINE,
        "aucun signal : ni lexique, ni numéro, ni réplique, ni récurrence",
    )


def _resoudre_niveaux(
    index: IndexStructure,
    observations: dict[str, _Observation],
    numerotes: list[str],
) -> None:
    """
    Passe C — attribue un niveau aux titres purement numérotés.

    `**UN.**` est un titre certain, mais acte ou scène ? La réponse dépend du
    document entier, jamais de la ligne. Trois cas, du plus fiable au moins :

    1. des `ACTE` lexicaux existent déjà → les titres numérotés sont des
       scènes imbriquées sous ces actes ;
    2. deux styles de numérotation coexistent → les chiffres romains et les
       nombres écrits marquent le premier niveau, les chiffres arabes le
       second (« ACTE II », « SCÈNE 3 ») ;
    3. un seul style et aucun acte lexical → ces titres *sont* le premier
       niveau, donc des actes. C'est le cas d'une pièce découpée en
       « UN / DEUX / TROIS », où les changements de scène sont marqués par des
       séparateurs `***` et non par des titres.
    """
    if not numerotes:
        return

    a_acte_lexical = any(
        classement.type is TypeLigne.TITRE_ACTE
        for classement in index.classements.values()
    )

    styles = {style_numerotation(label) for label in numerotes}
    styles.discard(None)
    deux_niveaux = len(styles) >= 2

    for label in numerotes:
        if a_acte_lexical:
            type_ligne = TypeLigne.TITRE_SCENE
            motif = "numéroté, sous des actes lexicaux"

        elif deux_niveaux:
            style = style_numerotation(label)
            premier_niveau = style in _STYLES_NIVEAU_SUPERIEUR
            type_ligne = (
                TypeLigne.TITRE_ACTE if premier_niveau else TypeLigne.TITRE_SCENE
            )
            motif = f"numérotation {style}, deux niveaux détectés"

        else:
            type_ligne = TypeLigne.TITRE_ACTE
            motif = "numéroté, niveau supérieur du document"

        observation = observations[label]

        index.classements[label] = ClassementLabel(
            label=label,
            affichage=observation.forme_dominante,
            type=type_ligne,
            confiance=Confiance.DEDUITE,
            motif=motif,
            occurrences=observation.occurrences,
            suivi_replique=observation.suivi_replique,
        )

    _signaler_remise_a_zero(index, numerotes, deux_niveaux)


def _signaler_remise_a_zero(
    index: IndexStructure,
    numerotes: list[str],
    deux_niveaux: bool,
) -> None:
    """
    Signale une numérotation qui redémarre alors qu'un seul niveau est visible.

    Une séquence 1, 2, 3, 1, 2 trahit une hiérarchie à deux niveaux dont le
    niveau supérieur n'est pas titré. Ce cas n'est pas *résolu*
    automatiquement — le faire supposerait de deviner où commencent les actes,
    donc où placer des sauts de page. Il est signalé, pour que la décision
    revienne à un humain via les surcharges.
    """
    if deux_niveaux or len(numerotes) < 3:
        return

    valeurs = [
        valeur
        for valeur in (valeur_numerotation(label) for label in sorted(numerotes))
        if valeur is not None
    ]

    if len(valeurs) < 3:
        return

    # Les labels étant triés alphabétiquement et non par position, on se
    # contente de vérifier la présence de doublons de valeur, signe le plus
    # net d'une remise à zéro.
    if len(set(valeurs)) < len(valeurs):
        index.avertissements.append(
            "numérotation des titres apparemment remise à zéro : la pièce "
            "comporte peut-être deux niveaux dont le supérieur n'est pas "
            "titré. Vérifiez les sauts de page, et au besoin renseignez "
            "TITRES_ACTE_FORCES / TITRES_SCENE_FORCES."
        )


def _ajouter_avertissements(index: IndexStructure, distribution: set[str]) -> None:
    """Complète l'index des constats utiles au rapport et au journal."""
    for classement in index.incertains:
        index.avertissements.append(
            f"classement incertain : « {classement.affichage} » traité par "
            f"défaut comme {classement.type.value}. S'il s'agit d'un titre, "
            f"ajoutez-le à TITRES_ACTE_FORCES ou TITRES_SCENE_FORCES."
        )

    if not distribution:
        index.avertissements.append(
            "aucune distribution détectée en tête d'ouvrage : la "
            "classification repose sur les seuls indices internes."
        )

    if index.compter(TypeLigne.PERSONNAGE) == 0:
        index.avertissements.append(
            "aucun personnage détecté : la convention typographique de "
            "EDIT.txt est peut-être cassée."
        )


# ============================================================
# 10. CLASSIFICATION DES LIGNES
# ============================================================


def classifier_ligne(ligne: str, index: IndexStructure) -> TypeLigne:
    """
    Classe une ligne isolée, sans tenir compte de son contexte.

    Une ligne en italique est toujours rendue comme didascalie : distinguer un
    lieu d'une didascalie exige de savoir ce qui précède. Utiliser
    `classifier_document()` pour obtenir cette distinction.
    """
    nue = ligne.strip()

    if not nue:
        return TypeLigne.VIDE

    if est_separateur(nue):
        return TypeLigne.SEPARATEUR

    contenu = contenu_gras(nue)
    if contenu is not None:
        return index.type_de(normaliser_label(contenu))

    if contenu_italique(nue) is not None:
        return TypeLigne.DIDASCALIE

    return TypeLigne.TEXTE


def classifier_document(texte: str, index: IndexStructure) -> list[LigneClassee]:
    """
    Classe toutes les lignes d'un document, contexte compris.

    Seule différence avec `classifier_ligne()`, mais elle est nécessaire : une
    ligne en italique placée juste après un titre est une **indication de
    lieu**, pas une didascalie. Les deux styles diffèrent par leur espacement.
    """
    resultats: list[LigneClassee] = []
    type_precedent: TypeLigne | None = None

    for numero, ligne in enumerate(texte.split("\n")):
        for brut, type_ligne, contenu in _classer_ligne_eventuellement_dedoublee(
            ligne, index
        ):
            # Une ligne de la liste des rôles reçoit son style propre : lignes
            # courtes alignées à gauche, qu'une justification étirerait d'un
            # bord à l'autre de la page.
            if numero in index.lignes_distribution and type_ligne is TypeLigne.TEXTE:
                type_ligne = TypeLigne.ENTREE_DISTRIBUTION

            if type_ligne is TypeLigne.DIDASCALIE and type_precedent in _OUVRE_UNE_SCENE:
                type_ligne = TypeLigne.LIEU

            resultats.append(LigneClassee(brut=brut, texte=contenu, type=type_ligne))

            # Une ligne vide ne rompt pas l'enchaînement « ouverture → lieu » :
            # elle les sépare presque toujours.
            if type_ligne is not TypeLigne.VIDE:
                type_precedent = type_ligne

    return resultats


# Types après lesquels une ligne en italique est une **indication de lieu**, non
# une didascalie ordinaire.
#
# Le séparateur `***` en fait partie : il marque un changement de scène, et
# beaucoup d'éditions font suivre ce séparateur de la description du nouveau
# lieu, sans titre intermédiaire — c'est le cas des pièces contemporaines
# découpées en fragments.
_OUVRE_UNE_SCENE = frozenset(
    {TypeLigne.TITRE_ACTE, TypeLigne.TITRE_SCENE, TypeLigne.SEPARATEUR}
)


def _classer_ligne_eventuellement_dedoublee(
    ligne: str,
    index: IndexStructure,
) -> list[tuple[str, TypeLigne, str]]:
    """
    Classe une ligne, en la dédoublant si elle porte un nom **et** sa réplique.

    Une ligne du type `**LÉA.** Tu penses à quoi ?` produit deux paragraphes :
    le nom de personnage, puis la réplique. Le nombre de lignes en sortie peut
    donc dépasser celui de l'entrée — c'est voulu, et c'est la seule
    transformation de structure que la classification s'autorise.

    Sans elle, la ligne entière serait du texte : aucun personnage reconnu, et
    des astérisques visibles dans le document final.
    """
    dedouble = dedoubler_replique_en_ligne(ligne)

    if dedouble is not None:
        type_nom = index.type_de(normaliser_label(dedouble.nom))

        # On ne dédouble que pour un personnage. Un titre suivi de texte sur la
        # même ligne est trop inhabituel pour qu'on l'interprète.
        if type_nom is TypeLigne.PERSONNAGE:
            nom = index.affichage_de(normaliser_label(dedouble.nom)) or dedouble.nom
            morceaux = [(ligne, TypeLigne.PERSONNAGE, nom)]

            if dedouble.didascalie:
                morceaux.append((ligne, TypeLigne.DIDASCALIE, dedouble.didascalie))

            morceaux.append((ligne, TypeLigne.TEXTE, dedouble.replique))

            return morceaux

    type_ligne = classifier_ligne(ligne, index)
    contenu = contenu_sans_marqueurs(ligne, type_ligne)

    # Pour un label en gras, on retient la graphie dominante du document plutôt
    # que celle de cette occurrence : c'est ce qui rend le rendu régulier.
    if type_ligne in _TYPES_A_LABEL:
        contenu = index.affichage_de(normaliser_label(contenu)) or contenu

    return [(ligne, type_ligne, contenu)]


# Types dont le contenu est un label recensé dans l'index, et dont la graphie
# doit donc être uniformisée à l'échelle du document.
_TYPES_A_LABEL = frozenset(
    {
        TypeLigne.TITRE_ACTE,
        TypeLigne.TITRE_SCENE,
        TypeLigne.DISTRIBUTION,
        TypeLigne.PERSONNAGE,
    }
)


def contenu_sans_marqueurs(ligne: str, type_ligne: TypeLigne) -> str:
    """
    Retire les marqueurs de structure d'une ligne.

    Les marqueurs `**` et `*` d'une ligne entière sont redondants avec le style
    de paragraphe qui portera le gras ou l'italique : les conserver afficherait
    des astérisques dans le DOCX. En revanche, les emphases *internes* à une
    réplique sont laissées telles quelles, `decouper_en_runs()` s'en chargeant.
    """
    nue = ligne.strip()

    if type_ligne in (
        TypeLigne.TITRE_ACTE,
        TypeLigne.TITRE_SCENE,
        TypeLigne.DISTRIBUTION,
        TypeLigne.PERSONNAGE,
    ):
        return (contenu_gras(nue) or nue).strip()

    if type_ligne in (TypeLigne.LIEU, TypeLigne.DIDASCALIE):
        return (contenu_italique(nue) or nue).strip()

    return nue


def decouper_en_runs(texte: str) -> list[Run]:
    """
    Découpe une ligne en fragments typés, selon ses emphases internes.

    Indispensable pour une réplique du type :

        Je t'attendais *elle se lève* depuis une heure.

    Un traitement purement ligne à ligne produirait un paragraphe entièrement
    romain et perdrait la didascalie intercalée.

    Returns:
        Fragments dans l'ordre, sans fragment vide. Une ligne sans emphase
        donne un unique fragment.
    """
    runs: list[Run] = []
    position = 0

    for correspondance in MOTIF_RUN.finditer(texte):
        if correspondance.start() > position:
            runs.append(Run(texte[position : correspondance.start()]))

        gras = correspondance.group("gras")

        if gras is not None:
            runs.append(Run(gras, gras=True))
        else:
            runs.append(Run(correspondance.group("ital"), italique=True))

        position = correspondance.end()

    if position < len(texte):
        runs.append(Run(texte[position:]))

    return [run for run in runs if run.texte]


# ============================================================
# 11. COMPARAISON OCR ↔ EDIT (contrôles mécaniques de l'étape 3)
# ------------------------------------------------------------
# Ces contrôles sont gratuits, instantanés et déterministes. Ils ne remplacent
# pas la comparaison sémantique par le modèle, mais ils rendent le rapport
# utile même là où le modèle passerait à côté — et, contrairement à lui, ils
# ne produisent jamais de faux négatif sur ce qu'ils savent mesurer.
# ============================================================


def comparer_volumes(ocr: str, edit: str) -> list[str]:
    """
    Compare les volumes de texte entre transcription et édition.

    Returns:
        Liste d'avertissements, vide si le volume est conservé.
    """
    reference = len(normaliser_pour_comparaison(ocr))

    if not reference:
        return []

    ratio = len(normaliser_pour_comparaison(edit)) / reference

    if ratio < config.RATIO_MINIMAL_LONGUEUR:
        return [
            f"volume réduit : l'édition fait {ratio:.0%} de la transcription "
            f"(seuil {config.RATIO_MINIMAL_LONGUEUR:.0%})"
        ]

    return []


# Nombre minimal de lettres pour qu'une ligne en capitales soit tenue pour un
# nom de rôle ou un titre. Écarte les répliques d'une ou deux lettres
# (« A. », « B. ») qu'un scan peut produire.
MIN_LETTRES_LABEL = 3

# Longueur maximale : au-delà, c'est une réplique criée, non un intitulé.
MAX_LONGUEUR_LABEL = 40


def _est_label_de_structure(ligne: str) -> bool:
    """
    Vrai si une ligne peut être un nom de rôle ou un titre, dans un texte brut.

    Prédicat **volontairement strict**, et distinct de `_ressemble_a_un_nom()`
    qui sert à lire une distribution. Le contexte n'est pas le même : ici la
    ligne provient de n'importe où dans un fichier, et la moindre tolérance
    produit des faux positifs à la chaîne.

    Trois rejets, chacun motivé par un faux positif réellement observé :

    - les marqueurs techniques (`[PAGE 3]`, `<<<PAGE_BREAK>>>`), que l'étape 2
      supprime légitimement et qui seraient donc signalés comme « disparus » à
      chaque livre ;
    - les lignes de moins de trois lettres, une réplique « A. » n'étant pas un
      rôle ;
    - les lignes dont les lettres ne sont pas **toutes** en capitales, un seuil
      partiel laissant passer des bouts de dialogue.
    """
    if "<<<" in ligne or MOTIF_MARQUEUR_PAGE_INLINE.search(ligne):
        return False

    if len(ligne) > MAX_LONGUEUR_LABEL:
        return False

    lettres = [caractere for caractere in ligne if caractere.isalpha()]

    if len(lettres) < MIN_LETTRES_LABEL:
        return False

    return all(caractere.isupper() for caractere in lettres)


def recenser_labels_capitales(texte: str) -> set[str]:
    """
    Relève les intitulés en capitales d'un texte, sous forme normalisée.

    Fonctionne indifféremment sur un OCR brut et sur un texte édité : la
    normalisation retire les astérisques, si bien que `JAN` dans l'OCR et
    `**JAN.**` dans l'édition donnent la même clé. C'est ce qui rend les deux
    ensembles comparables malgré la mise en forme ajoutée par l'étape 2.

    L'extraction est **conservatrice** : elle préfère manquer un rôle plutôt
    que d'en inventer. Un rapport bruyant ne serait pas lu, et l'étape de
    comparaison sémantique cherche de son côté les personnages disparus.
    """
    labels: set[str] = set()

    for ligne in texte.split("\n"):
        nue = ligne.strip().strip("*").strip()

        if not nue or not _est_label_de_structure(nue):
            continue

        label = normaliser_label(nue)

        if label:
            labels.add(label)

    return labels


def comparer_labels(ocr: str, edit: str) -> list[str]:
    """
    Signale les noms en capitales présents dans l'OCR et absents de l'édition.

    Détecte la disparition d'un personnage ou d'un titre entier — perte grave
    qu'un ratio de volume global ne verrait pas sur un livre de 400 pages.

    Le contrôle est **volontairement asymétrique** : un label apparu dans
    l'édition sans être dans l'OCR n'est pas signalé, car il résulte le plus
    souvent d'une correction légitime de reconnaissance (« JAN » lu « IAN »).
    """
    manquants = recenser_labels_capitales(ocr) - recenser_labels_capitales(edit)

    return [
        f"présent dans la transcription, absent de l'édition : « {label} »"
        for label in sorted(manquants)
    ]


def comparer_lignes_non_vides(ocr: str, edit: str) -> list[str]:
    """
    Compare le nombre de lignes porteuses de texte.

    L'édition en supprime légitimement quelques-unes — marqueurs de page,
    numéros isolés, artefacts. Une chute importante signale en revanche une
    perte de contenu. Le seuil réutilise `RATIO_MINIMAL_LONGUEUR`.
    """
    def compter(texte: str) -> int:
        return sum(
            1
            for ligne in texte.split("\n")
            if ligne.strip() and not MOTIF_MARQUEUR_PAGE.match(ligne)
        )

    reference = compter(ocr)

    if not reference:
        return []

    ratio = compter(edit) / reference

    if ratio < config.RATIO_MINIMAL_LONGUEUR:
        return [
            f"lignes manquantes : l'édition en compte {ratio:.0%} "
            f"(seuil {config.RATIO_MINIMAL_LONGUEUR:.0%})"
        ]

    return []


def controler_convention(edit: str) -> list[str]:
    """
    Vérifie que le texte édité respecte la convention typographique.

    Une convention cassée n'est pas une perte de contenu, mais elle fera
    échouer la reconnaissance de structure de l'étape 4 : autant le savoir
    avant de générer le DOCX.
    """
    avertissements: list[str] = []

    if edit.count("*") % 2 != 0:
        avertissements.append(
            "nombre impair d'astérisques : la convention typographique est cassée"
        )

    for motif in (r"<<<PAGE_BREAK>>>", r"^\s*\[PAGE\s+\d+\]\s*$", r"```"):
        if re.search(motif, edit, flags=re.MULTILINE):
            avertissements.append(f"artefact non supprimé : {motif}")

    return avertissements


def controles_mecaniques(ocr: str, edit: str) -> list[str]:
    """
    Applique tous les contrôles déterministes à un couple (OCR, EDIT).

    Returns:
        Liste d'avertissements, vide si aucun problème mécanique n'est décelé.
    """
    return [
        *comparer_volumes(ocr, edit),
        *comparer_lignes_non_vides(ocr, edit),
        *comparer_labels(ocr, edit),
        *controler_convention(edit),
    ]


# ============================================================
# 12. RAPPORT D'INSPECTION
# ============================================================

_ENTETES = ("LABEL", "OCC.", "RÉPL.", "CLASSÉ", "CONFIANCE")
_LARGEUR_LABEL = 24
_LARGEUR_TYPE = 13
_ORDRE_AFFICHAGE = (
    TypeLigne.TITRE_ACTE,
    TypeLigne.TITRE_SCENE,
    TypeLigne.DISTRIBUTION,
    TypeLigne.PERSONNAGE,
)


def rapport_classification(index: IndexStructure) -> str:
    """
    Met en forme la table d'inspection de la classification.

    Affichée avant toute génération de DOCX, elle rend visible ce que le
    parseur a compris. C'est la contrepartie assumée d'une heuristique : plutôt
    que d'affirmer qu'elle ne se trompe jamais, on la donne à vérifier.
    """
    lignes = [
        f"{_ENTETES[0]:<{_LARGEUR_LABEL}} {_ENTETES[1]:>5} {_ENTETES[2]:>6}  "
        f"{_ENTETES[3]:<{_LARGEUR_TYPE}} {_ENTETES[4]}",
        "-" * 72,
    ]

    for type_ligne in _ORDRE_AFFICHAGE:
        for classement in index.labels_de_type(type_ligne):
            marque = " ⚠" if classement.confiance is Confiance.INCERTAINE else ""

            lignes.append(
                f"{classement.affichage[:_LARGEUR_LABEL]:<{_LARGEUR_LABEL}} "
                f"{classement.occurrences:>5} "
                f"{classement.suivi_replique:>6}  "
                f"{type_ligne.value:<{_LARGEUR_TYPE}} "
                f"{classement.confiance.value} ({classement.motif}){marque}"
            )

    lignes.append("-" * 72)
    lignes.append(
        f"Actes : {index.compter(TypeLigne.TITRE_ACTE)}     "
        f"Scènes : {index.compter(TypeLigne.TITRE_SCENE)}     "
        f"Personnages : {index.compter(TypeLigne.PERSONNAGE)}"
    )

    if index.incertains:
        lignes.append("")
        lignes.append(
            f"⚠ {len(index.incertains)} classement(s) incertain(s), traité(s) "
            "par défaut sans saut de page. S'il s'agit de titres, renseignez "
            "TITRES_ACTE_FORCES ou TITRES_SCENE_FORCES dans config.py."
        )

    return "\n".join(lignes)
