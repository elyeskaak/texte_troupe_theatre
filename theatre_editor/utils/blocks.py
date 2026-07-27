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
    Vrai si un segment de ligne ressemble à un nom de rôle.

    Dans une distribution, les rôles sont écrits en capitales et suivis d'une
    éventuelle description. Exiger une majorité de capitales évite de prendre
    une phrase de préface pour un personnage.
    """
    lettres = [c for c in segment if c.isalpha()]

    if not lettres or len(segment) > 40:
        return False

    majuscules = sum(1 for c in lettres if c.isupper())

    return majuscules / len(lettres) >= 0.5


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
    lignes = texte.split("\n")
    noms: set[str] = set()

    for index, ligne in enumerate(lignes):
        if normaliser_label(ligne) not in config.ETIQUETTES_DISTRIBUTION:
            continue

        noms |= _lire_distribution(lignes, index + 1)

        # Une seule distribution par ouvrage : la première rencontrée.
        break

    return noms


def _lire_distribution(lignes: list[str], depart: int) -> set[str]:
    """Lit les lignes suivant une étiquette de distribution."""
    noms: set[str] = set()
    vides_consecutives = 0

    fin = min(depart + config.MAX_LIGNES_DISTRIBUTION, len(lignes))

    for ligne in lignes[depart:fin]:
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

        # « JAN, jeune homme » → « JAN »
        segment = re.split(r"[,:(–—-]", nue.strip("*"), maxsplit=1)[0].strip()

        if _ressemble_a_un_nom(segment):
            noms.add(normaliser_label(segment))

    return noms


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

        if contenu is None:
            continue

        label = normaliser_label(contenu)

        if not label:
            continue

        observation = observations.setdefault(
            label, _Observation(affichage=contenu.strip(), premier_index=index)
        )
        observation.occurrences += 1

        if _suit_une_replique(lignes, index + 1):
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
    distribution = recenser_personnages(texte)

    index = IndexStructure()

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
            affichage=observation.affichage,
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
            affichage=observation.affichage,
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

    for ligne in texte.split("\n"):
        type_ligne = classifier_ligne(ligne, index)
        contenu = contenu_sans_marqueurs(ligne, type_ligne)

        if type_ligne is TypeLigne.DIDASCALIE and type_precedent in (
            TypeLigne.TITRE_ACTE,
            TypeLigne.TITRE_SCENE,
        ):
            type_ligne = TypeLigne.LIEU

        resultats.append(LigneClassee(brut=ligne, texte=contenu, type=type_ligne))

        # Les lignes vides et les séparateurs ne rompent pas l'enchaînement
        # « titre → lieu » : une ligne vide les sépare presque toujours.
        if type_ligne not in (TypeLigne.VIDE, TypeLigne.SEPARATEUR):
            type_precedent = type_ligne

    return resultats


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
# 11. RAPPORT D'INSPECTION
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
