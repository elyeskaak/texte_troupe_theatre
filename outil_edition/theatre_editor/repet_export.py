"""
Étape 4 bis — sortie pour l'outil de répétition : `<Livre>_REPET.json`.

**Aucune IA, aucun coût, aucun parcours supplémentaire du document.** Ce module
ne reclassifie rien : il reçoit les lignes déjà classées par `classifier_document`
et l'index déjà construit pour le DOCX, et se contente de les regrouper en une
structure exploitable par `../outil_repetition/`.

Cette dépendance à sens unique est ce qui rend l'ensemble tenable : la
classification acte / scène / personnage vit **à un seul endroit**, dans
`blocks.construire_index_structure()`. Corriger un classement dans `config.py`
corrige les deux sorties du même coup, et le JSON ne peut pas se mettre à
diverger du DOCX.

Trois décisions de conception méritent d'être connues avant de lire le code.

**L'unité de premier niveau est l'« unité jouable », pas l'acte.** Une liste
plate d'unités couvre sans arborescence conditionnelle les trois cas réels : la
pièce classique (acte et scène renseignés), la pièce contemporaine sans titres de
scène — où les `***` marquent les changements — et le texte d'un seul tenant.
C'est aussi le grain dont l'outil a besoin pour replier une scène.

**L'identifiant d'une réplique est une empreinte de son contenu**, jamais sa
position. Un `EDIT.txt` relu et corrigé décale toutes les positions ; des
identifiants positionnels feraient alors migrer silencieusement la progression
d'une réplique vers sa voisine. Avec une empreinte, la dégradation est juste :
une réplique dont le texte a changé perd son statut — il faut la réapprendre —
et toutes les autres conservent le leur.

**Rien n'est jamais écarté en silence.** Une ligne de texte sans personnage
annoncé est conservée *et* signalée. C'est la leçon du prototype de l'outil de
répétition, dont le parseur concaténait ou jetait sans trace tout ce qu'il ne
reconnaissait pas : une réplique perdue y était indétectable.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from theatre_editor import __version__, config
from theatre_editor.utils import blocks, io

# Types de ligne qui n'apparaissent pas dans le JSON : ils ne portent ni texte
# à réciter, ni structure.
TYPES_SANS_TRACE = frozenset({blocks.TypeLigne.VIDE})

# Types de ligne appartenant aux pages liminaires. Ils ne se répètent pas, mais
# ils sont conservés : ils portent le titre de la pièce et sa distribution, que
# l'outil affiche à l'accueil.
TYPES_LIMINAIRES = frozenset({
    blocks.TypeLigne.TITRE_OEUVRE,
    blocks.TypeLigne.TITRE_SECONDAIRE,
    blocks.TypeLigne.EPIGRAPHE,
    blocks.TypeLigne.ATTRIBUTION,
    blocks.TypeLigne.NOTE,
    blocks.TypeLigne.DISTRIBUTION,
    blocks.TypeLigne.ENTREE_DISTRIBUTION,
})

# Types de ligne ouvrant une unité jouable.
TYPES_OUVRENT_UNITE = frozenset({
    blocks.TypeLigne.TITRE_ACTE,
    blocks.TypeLigne.TITRE_SCENE,
    blocks.TypeLigne.SEPARATEUR,
})

# Types rendus tels quels comme éléments d'une unité.
TYPES_ELEMENT_SIMPLE = {
    blocks.TypeLigne.LIEU: "lieu",
    blocks.TypeLigne.DIDASCALIE: "didascalie",
    blocks.TypeLigne.DIDASCALIE_LONGUE: "didascalie",
    blocks.TypeLigne.PROLOGUE: "didascalie",
}

# Longueur de l'empreinte d'identifiant. 12 caractères hexadécimaux, soit 48
# bits : sur les quelques milliers de répliques d'une pièce, la probabilité
# d'une collision fortuite est négligeable — et les collisions *légitimes*
# (deux « Oui. » du même personnage) sont de toute façon traitées explicitement
# par un suffixe d'occurrence.
LONGUEUR_EMPREINTE = 12

MOTIF_ESPACES = re.compile(r"\s+")

# Apostrophes ramenées à la forme droite dans un nom de personnage. Voir
# `nom_personnage` : sans cela, la même personne se dédouble.
MOTIF_APOSTROPHES = re.compile(r"[’‘‛`´]")

# Jonction de plusieurs personnages dans un même label : « X et Y. » ou
# « X ET Y. ». Insensible à la casse, comme le reste de la saisie.
MOTIF_JONCTION = re.compile(r"\s+et\s+", re.IGNORECASE)

# Label qui ne nomme aucun personnage précis : toute la distribution parle.
MARQUEUR_TOUS = "TOUS"

# Marque une réplique comme appartenant à n'importe quel rôle choisi, plutôt
# qu'à un personnage nommé. Voir `noms_personnages`.
JOKER_TOUS = "*"


# ============================================================
# 1. IDENTIFIANTS
# ============================================================


def nom_personnage(label: str) -> str:
    """
    Nom canonique d'un personnage, à partir de son label de réplique.

    Deux normalisations, et **la même raison pour les deux** : un personnage ne
    doit pas se dédoubler parce que sa graphie varie d'une réplique à l'autre.

    **Le point final est retiré.** La convention typographique écrit
    « **JAN.** », et ce point est une convention d'imprimerie — il annonce la
    réplique. Le conserver donnerait « JAN. » dans le sélecteur de rôles, puis
    deux personnages distincts le jour où une édition écrit « JAN » sans point.

    **Les apostrophes sont ramenées à la forme droite.** Constaté sur un texte
    réel : « L'AGENT DUPONT » (apostrophe droite, 3 répliques) et « L’AGENT
    DUPONT » (apostrophe typographique, 108 répliques) donnaient deux rôles là
    où il n'y en a qu'un. Choisir l'un aurait laissé les répliques de l'autre
    visibles, sans que rien ne le signale. Un traitement de texte substitue
    l'apostrophe automatiquement, mais pas toujours : la variation est
    inévitable dans un document saisi à la main.

    Volontairement **pas** `blocks.normaliser_label()`, qui retire aussi les
    diacritiques : ce nom-là est affiché, et « LE MAÎTRE » ne doit pas devenir
    « LE MAITRE » sur l'écran de choix.
    """
    sans_ponctuation = blocks.MOTIF_PONCTUATION_FINALE.sub("", label.strip())

    return MOTIF_APOSTROPHES.sub("'", sans_ponctuation).strip()


def noms_personnages(label: str) -> list[str]:
    """
    Un ou plusieurs personnages parlant la même réplique.

    « TOUS. » ne nomme personne : qui est en scène n'est pas su à ce stade, et
    énumérer ici serait faux ou incomplet selon la scène. Il se traduit par
    `JOKER_TOUS`, qui vaut pour n'importe quel rôle plutôt que pour un
    personnage fantôme de plus dans la distribution.

    « SIR ROWLAND et CLARISSA. » / « X ET Y. » nomme deux personnages
    distincts qui parlent ensemble ; chacun est renormalisé comme s'il
    parlait seul, pour ne pas se dédoubler avec ses répliques individuelles.
    """
    if nom_personnage(label).upper() == MARQUEUR_TOUS:
        return [JOKER_TOUS]

    return [nom_personnage(morceau) for morceau in MOTIF_JONCTION.split(label)]


def normaliser_pour_identifiant(texte: str) -> str:
    """
    Normalise un texte pour en dériver un identifiant stable.

    Volontairement distincte de `blocks.normaliser_pour_comparaison()`, qui sert
    à comparer des volumes entre étapes et ne touche pas à la casse. Ici, la
    casse ne doit pas compter : une correction éditoriale qui rétablit une
    majuscule ne doit pas faire perdre son statut à une réplique.
    """
    sans_emphase = texte.replace("*", "")

    return MOTIF_ESPACES.sub(" ", sans_emphase).strip().lower()


def identifiant_replique(
    personnages: list[str], texte: str, occurrence: int
) -> str:
    """
    Empreinte stable d'une réplique.

    Args:
        personnages: personnage(s) disant la réplique, tels que classés — un
            seul nom dans l'immense majorité des cas, plusieurs pour une
            réplique collective.
        texte: texte parlé, didascalies internes exclues.
        occurrence: rang de cette réplique parmi les répliques identiques des
            mêmes personnages, à partir de 0.

    Le rang n'entre dans l'empreinte que **s'il est non nul**. Sans cette
    précaution, ajouter un second « Oui. » à MARTHA changerait l'identifiant du
    premier, qui existait pourtant déjà : ajouter une réplique ne doit jamais
    faire perdre le statut d'une autre.

    Un seul personnage produit exactement l'empreinte d'avant l'introduction
    des répliques collectives : la jonction d'une liste à un élément est ce
    nom-là, donc aucun identifiant existant ne se déplace avec cette évolution
    du format.
    """
    graine = f"{'/'.join(personnages)}|{normaliser_pour_identifiant(texte)}"

    if occurrence:
        graine = f"{graine}|{occurrence}"

    empreinte = hashlib.sha1(graine.encode("utf-8")).hexdigest()

    return f"r_{empreinte[:LONGUEUR_EMPREINTE]}"


# ============================================================
# 2. DÉCOUPAGE D'UNE RÉPLIQUE
# ============================================================


@dataclass(frozen=True)
class Parole:
    """Texte réellement prononcé d'une réplique, et ses jeux de scène."""

    texte: str
    didascalies: list[dict[str, Any]]


def separer_parole_et_jeu(lignes: list[str]) -> Parole:
    """
    Sépare le texte parlé des didascalies intercalées.

    « Je t'attendais *elle se lève* depuis une heure » contient deux mots dits,
    une indication de jeu, puis trois mots dits. Le texte parlé est ce qui sera
    comparé à une récitation ; y laisser la didascalie ferait chuter le score de
    fidélité de toutes les répliques portant un jeu de scène — c'est-à-dire les
    plus travaillées.

    Chaque didascalie est repérée par `avant_mot` : le nombre de mots parlés qui
    la précèdent. Cette position résiste au reflux du texte, alors qu'un index
    de caractères ne survivrait pas au premier changement de police.
    """
    morceaux: list[str] = []
    didascalies: list[dict[str, Any]] = []

    for numero, ligne in enumerate(lignes):
        if numero:
            morceaux.append("\n")

        for fragment in blocks.decouper_en_runs(ligne):
            if fragment.italique:
                didascalies.append({
                    "avant_mot": len(_mots("".join(morceaux))),
                    "texte": fragment.texte.strip(),
                })
                continue

            morceaux.append(fragment.texte)

    return Parole(texte=_recomposer("".join(morceaux)), didascalies=didascalies)


def _mots(texte: str) -> list[str]:
    """Mots d'un texte, sans se soucier de la ponctuation."""
    return [mot for mot in MOTIF_ESPACES.split(texte) if mot]


def _recomposer(texte: str) -> str:
    """
    Nettoie les espaces laissés par le retrait des didascalies, sans toucher aux
    retours à la ligne.

    Les retours à la ligne sont **signifiants** : ils marquent un vers (voir
    `_est_en_vers`). Les réduire comme de simples espaces recollerait deux vers,
    exactement ce que l'étape 2 s'est appliquée à ne pas faire.
    """
    lignes = [re.sub(r"[ \t]+", " ", ligne).strip() for ligne in texte.split("\n")]

    return "\n".join(lignes).strip()


def _est_en_vers(lignes: list[str]) -> bool:
    """
    Une réplique tenant sur plusieurs lignes est en vers, ou volontairement
    rompue.

    L'inférence est sûre parce que l'étape 2 a déjà tranché : son prompt impose
    de rejoindre les retours à la ligne **mécaniques** en un texte continu, et de
    ne conserver séparées que les lignes voulues — vers, chant, énumération,
    réplique interrompue. Une réplique restée sur deux lignes dans `EDIT.txt` l'est
    donc par décision, jamais par accident de largeur de page.

    L'outil de répétition s'en sert pour ne pas reflower un vers comme de la
    prose, et pour compter l'amorce autrement.
    """
    return len(lignes) > 1


# ============================================================
# 3. CONSTRUCTION DU DOCUMENT DE RÉPÉTITION
# ============================================================


@dataclass
class _Unite:
    """Unité jouable en cours de construction."""

    numero: int
    acte: str | None
    scene: str | None
    implicite: bool
    elements: list[dict[str, Any]] = field(default_factory=list)
    personnages: list[str] = field(default_factory=list)

    def en_dictionnaire(self) -> dict[str, Any]:
        return {
            "id": f"u{self.numero:03d}",
            "acte": self.acte,
            "scene": self.scene,
            "implicite": self.implicite,
            "personnages": self.personnages,
            "elements": self.elements,
        }

    def vide(self) -> bool:
        return not self.elements


class _Constructeur:
    """
    Assemble les unités jouables au fil des lignes classées.

    Écrit sous forme de classe et non de fonction : l'assemblage porte cinq
    états qui avancent ensemble — unité courante, réplique en cours, acte et
    scène hérités, comptages. Les passer en arguments d'une fonction récursive
    les rendrait tous optionnels et le moindre oubli produirait un JSON
    plausible mais faux.
    """

    def __init__(self) -> None:
        self.unites: list[_Unite] = []
        self.liminaires: list[dict[str, str]] = []
        self.avertissements: list[str] = []

        self._unite: _Unite | None = None
        self._acte: str | None = None
        self._scene: str | None = None

        # Réplique en cours : un PERSONNAGE ouvre, les TEXTE qui suivent
        # l'alimentent, tout autre type la referme. Une liste et non un nom
        # seul : une réplique peut être dite par plusieurs personnages.
        self._personnages: list[str] | None = None
        self._lignes: list[str] = []

        # Comptages, pour la section « personnages » et les identifiants.
        self._repliques: dict[str, int] = {}
        self._mots: dict[str, int] = {}
        self._occurrences: dict[tuple[str, str], int] = {}

        # Graphies rencontrées pour chaque nom canonique, afin de signaler les
        # fusions plutôt que de les taire (voir `_relever_graphie`).
        self._graphies: dict[str, set[str]] = {}

    # --- entrée principale ------------------------------------------

    def ajouter(self, ligne: blocks.LigneClassee) -> None:
        """Traite une ligne classée."""
        if ligne.type in TYPES_SANS_TRACE:
            return

        if ligne.type is blocks.TypeLigne.TEXTE:
            self._ajouter_texte(ligne)
            return

        # Tout ce qui n'est pas du texte referme la réplique en cours.
        self._fermer_replique()

        if ligne.type in TYPES_LIMINAIRES:
            self.liminaires.append({"type": ligne.type.value, "texte": ligne.texte})
            return

        if ligne.type in TYPES_OUVRENT_UNITE:
            self._ouvrir_unite(ligne)
            return

        if ligne.type is blocks.TypeLigne.PERSONNAGE:
            self._personnages = noms_personnages(ligne.texte)

            # Le joker ne provient d'aucune graphie à surveiller : « TOUS »
            # n'est le nom de personne.
            if self._personnages != [JOKER_TOUS]:
                for brut, canonique in zip(
                    MOTIF_JONCTION.split(ligne.texte), self._personnages
                ):
                    self._relever_graphie(brut, canonique)

            return

        nom_element = TYPES_ELEMENT_SIMPLE.get(ligne.type)

        if nom_element is not None:
            self._element({"type": nom_element, "texte": ligne.texte})
            return

        # Aucun type n'est censé manquer : `TypeLigne` est fermé et tous ses
        # membres sont traités ci-dessus. Un type ajouté sans être câblé ici
        # doit se signaler, pas disparaître.
        self.avertissements.append(
            f"type de ligne non pris en charge par repet_export : "
            f"« {ligne.type.value} » — ligne « {_extrait(ligne.texte)} »"
        )

    def _relever_graphie(self, brut: str, canonique: str) -> None:
        """
        Consigne les graphies d'un même nom, pour signaler toute fusion.

        `nom_personnage` réunit « L'AGENT DUPONT » et « L’AGENT DUPONT » — c'est
        voulu. Mais une fusion muette empêcherait de découvrir que le document
        source mélange deux graphies, ce qui se paie ailleurs : dans le DOCX
        imprimé, où les deux apparaissent, et dans l'outil de coupes.
        """
        self._graphies.setdefault(canonique, set()).add(brut.strip())

    def terminer(self) -> None:
        """Referme ce qui reste ouvert."""
        self._fermer_replique()

        for canonique, graphies in sorted(self._graphies.items()):
            if len(graphies) > 1:
                variantes = " / ".join(f"« {g} »" for g in sorted(graphies))
                self.avertissements.append(
                    f"graphies multiples réunies sous « {canonique} » : {variantes} "
                    "— à uniformiser dans le document source"
                )

        if self._unite is not None and not self._unite.vide():
            self.unites.append(self._unite)

        self._unite = None

    # --- unités -----------------------------------------------------

    def _ouvrir_unite(self, ligne: blocks.LigneClassee) -> None:
        """Ouvre une unité jouable, en héritant du contexte."""
        if ligne.type is blocks.TypeLigne.TITRE_ACTE:
            self._acte = ligne.texte
            # Un nouvel acte remet la scène à zéro : « SCÈNE 2 » de l'acte I
            # n'est pas « SCÈNE 2 » de l'acte II.
            self._scene = None
            implicite = False
        elif ligne.type is blocks.TypeLigne.TITRE_SCENE:
            self._scene = ligne.texte
            implicite = False
        else:
            # Séparateur `***` : changement de scène sans titre. L'unité hérite
            # de l'acte et de la scène courants, et se marque implicite pour que
            # l'outil n'affiche pas un titre qui n'existe pas.
            implicite = True

        if self._unite is not None and not self._unite.vide():
            self.unites.append(self._unite)

        self._unite = _Unite(
            numero=len(self.unites) + 1,
            acte=self._acte,
            scene=self._scene,
            implicite=implicite,
        )

    def _unite_courante(self) -> _Unite:
        """
        Unité courante, créée au besoin.

        Une pièce peut commencer par une réplique, sans titre d'acte ni de
        scène : l'unité implicite qui l'accueille évite un cas particulier
        partout ailleurs.
        """
        if self._unite is None:
            self._unite = _Unite(
                numero=len(self.unites) + 1,
                acte=self._acte,
                scene=self._scene,
                implicite=True,
            )

        return self._unite

    def _element(self, element: dict[str, Any]) -> None:
        self._unite_courante().elements.append(element)

    # --- répliques --------------------------------------------------

    def _ajouter_texte(self, ligne: blocks.LigneClassee) -> None:
        """Une ligne de texte alimente la réplique en cours, ou se signale."""
        if self._personnages is None:
            # Ni jetée, ni recollée à la réplique précédente : conservée sous un
            # type propre et signalée. C'est le seul comportement qui rende une
            # anomalie de structure visible plutôt qu'indétectable.
            self._element({"type": "texte_sans_personnage", "texte": ligne.texte})
            self.avertissements.append(
                "texte sans personnage annoncé, conservé tel quel : "
                f"« {_extrait(ligne.texte)} »"
            )
            return

        self._lignes.append(ligne.texte)

    def _fermer_replique(self) -> None:
        """Clôt la réplique en cours et l'ajoute à l'unité."""
        personnages = self._personnages
        lignes = self._lignes

        self._personnages = None
        self._lignes = []

        if personnages is None:
            return

        if not lignes:
            # Un personnage annoncé sans réplique : fréquent au théâtre
            # contemporain, où l'unique intervention d'un rôle est une
            # didascalie. Ce n'est pas une anomalie, mais il n'y a rien à
            # réciter — donc rien à écrire.
            return

        parole = separer_parole_et_jeu(lignes)

        if not parole.texte:
            # La réplique ne contenait qu'un jeu de scène : ses didascalies sont
            # conservées comme éléments de l'unité, sinon elles disparaîtraient.
            for didascalie in parole.didascalies:
                self._element({"type": "didascalie", "texte": didascalie["texte"]})
            return

        cle = (tuple(personnages), normaliser_pour_identifiant(parole.texte))
        occurrence = self._occurrences.get(cle, 0)
        self._occurrences[cle] = occurrence + 1

        element = {
            "type": "replique",
            "id": identifiant_replique(personnages, parole.texte, occurrence),
            "personnages": personnages,
            "texte": parole.texte,
            "vers": _est_en_vers(lignes),
        }

        if parole.didascalies:
            element["didascalies_internes"] = parole.didascalies

        self._element(element)

        unite = self._unite_courante()

        for personnage in personnages:
            if personnage not in unite.personnages:
                unite.personnages.append(personnage)

            # Le joker ne compte pour personne en particulier : il n'a pas de
            # volume propre, et l'inscrire gonflerait faussement le rôle de
            # tout le monde.
            if personnage == JOKER_TOUS:
                continue

            self._repliques[personnage] = self._repliques.get(personnage, 0) + 1
            self._mots[personnage] = self._mots.get(personnage, 0) + len(
                _mots(parole.texte)
            )

    # --- sortie -----------------------------------------------------

    def personnages(self) -> list[dict[str, Any]]:
        """
        Distribution parlante, du plus disert au moins bavard.

        Le tri par volume place en tête les rôles qu'on est susceptible de
        jouer, ce qui est exactement l'ordre attendu de l'écran de choix.
        À volume égal, l'ordre alphabétique tranche : sans lui, deux exécutions
        pourraient différer.
        """
        return [
            {
                "nom": nom,
                "repliques": self._repliques[nom],
                "mots": self._mots[nom],
            }
            for nom in sorted(
                self._repliques, key=lambda nom: (-self._mots[nom], nom)
            )
        ]


def _extrait(texte: str, longueur: int = 60) -> str:
    """Début d'un texte, pour un message d'avertissement lisible."""
    aplati = MOTIF_ESPACES.sub(" ", texte).strip()

    if len(aplati) <= longueur:
        return aplati

    return aplati[: longueur - 1] + "…"


def construire_repet(
    lignes: list[blocks.LigneClassee],
    index: blocks.IndexStructure,
    *,
    piece: str,
) -> dict[str, Any]:
    """
    Construit le document de répétition à partir de lignes déjà classées.

    Args:
        lignes: sortie de `blocks.classifier_document()`, rôles liminaires
            appliqués si l'étape 2 bis a tourné.
        index: index de structure du même document.
        piece: nom du livre.

    Returns:
        Le contenu du futur `REPET.json`, **sans champ de date** : la fonction
        est ainsi déterministe, et deux appels sur le même texte produisent des
        dictionnaires strictement égaux. La date est ajoutée à l'écriture.
    """
    constructeur = _Constructeur()

    for ligne in lignes:
        constructeur.ajouter(ligne)

    constructeur.terminer()

    return {
        "schema": config.SCHEMA_REPET,
        "piece": piece,
        "outil": f"outil_edition {__version__} — étape 4",
        "avertissements": list(index.avertissements) + constructeur.avertissements,
        "liminaires": constructeur.liminaires,
        "personnages": constructeur.personnages(),
        "unites": [unite.en_dictionnaire() for unite in constructeur.unites],
    }


# ============================================================
# 4. ÉCRITURE
# ============================================================


def ecrire_repet(
    chemins: io.CheminsLivre,
    lignes: list[blocks.LigneClassee],
    index: blocks.IndexStructure,
) -> dict[str, Any]:
    """
    Écrit `<Livre>_REPET.json` et retourne son contenu.

    Appelée par l'étape 4 après l'enregistrement du DOCX. L'échec de cette
    écriture ne doit jamais empêcher un DOCX d'exister : c'est à l'appelant de
    le garantir, et `docx_export` le fait.
    """
    document = construire_repet(lignes, index, piece=chemins.nom)
    document["genere_le"] = datetime.now().isoformat(timespec="seconds")

    io.ecrire_sidecar(chemins.repet, document)

    return document


def compter(document: dict[str, Any]) -> dict[str, int]:
    """Quelques totaux, pour le journal et le récapitulatif de l'étape."""
    repliques = sum(
        1
        for unite in document["unites"]
        for element in unite["elements"]
        if element["type"] == "replique"
    )

    return {
        "unites": len(document["unites"]),
        "repliques": repliques,
        "personnages": len(document["personnages"]),
    }
