"""
Configuration centrale du pipeline d'édition de pièces de théâtre.

Ce module ne contient **que des données**. Aucune fonction, aucune logique,
aucun effet de bord. C'est la contrepartie de la règle « aucun nombre magique
dans le code » : tout ce qui se règle se règle ici, en un seul endroit.

Deux conséquences pratiques de cette discipline :

- ce module n'importe rien d'autre que la bibliothèque standard, il peut donc
  être chargé dans n'importe quel contexte (tests hors ligne, Colab sans clé
  API, machine sans `openai` installé) ;
- il ne vérifie jamais qu'un chemin existe. `DOSSIER_DRIVE` désigne un
  emplacement Colab qui n'existe pas sur une machine de développement, et cela
  doit rester sans conséquence tant qu'aucune étape n'est réellement lancée.
"""

from __future__ import annotations

from pathlib import Path

# ============================================================
# EMPLACEMENTS
# ============================================================

# Dossier Google Drive contenant les PDF et recevant toutes les sorties.
DOSSIER_DRIVE = Path("/content/drive/MyDrive/Troupe 122 - 2026-27")

# Les PDF sont rangés à plat dans ce dossier (décision n° 6).
# Passer à True pour explorer aussi les sous-dossiers.
SCAN_RECURSIF = False

# Nombre maximal de pages traitées par PDF. `None` traite le livre entier.
#
# Destiné aux essais : régler à 10 permet d'éprouver les quatre étapes sur un
# nouveau livre pour quelques centimes, avant d'engager 300 pages.
#
# Les pages transcrites lors d'un essai sont conservées et réutilisées lors du
# passage complet — rien n'est perdu, rien n'est repayé. Les étapes suivantes
# n'ont pas besoin de ce réglage : elles travaillent depuis `OCR.txt`, qui ne
# contiendra que les pages retenues.
LIMITE_PAGES: int | None = None


# ============================================================
# MODÈLES
# ------------------------------------------------------------
# Identifiants vérifiés présents sur le compte le 2026-07-27.
# `lister_modeles_disponibles()` (utils/api.py) permet de refaire ce
# contrôle depuis Colab.
# ============================================================

# Étape 1 — OCR Vision.
#
# L'OCR est l'étape la plus nombreuse en appels (une par page), la plus
# coûteuse, et celle dont tout le reste dépend : une erreur de transcription se
# propage, l'étape 2 ayant pour consigne de ne pas réécrire l'auteur. C'est
# donc le dernier endroit où économiser sur la qualité du modèle.
#
# Identifiant daté, comme pour l'édition : un alias non daté pourrait changer
# de comportement au milieu d'un livre.
#
# Si ce modèle refusait les entrées `input_image`, l'appel échouerait par un
# code 400 — non réessayable, donc immédiat et explicite. Repli connu et
# éprouvé pour la vision : "gpt-4o".
MODEL_OCR = "gpt-5.5-2026-04-23"

# Étape 2a — édition OCR. Tâche la plus exigeante du pipeline.
MODEL_EDITION = "gpt-5.5-2026-04-23"

# Étape 2b — raccord. Tâche étroite (ressouder un mot sur 100 lignes),
# confiée à un modèle léger.
#
# Note : `gpt-5.5-mini` n'existe pas. `gpt-5.4-mini` est la variante légère
# la plus récente disponible. L'identifiant est daté, donc figé : aucun
# risque qu'un changement d'alias modifie le comportement en cours de livre.
MODEL_RACCORD = "gpt-5.4-mini-2026-03-17"

# Étape 3 — contrôle qualité. Comparaison de deux textes longs : tâche
# exigeante, on garde le modèle principal.
MODEL_VALIDATION = "gpt-5.5-2026-04-23"


# ============================================================
# DÉCOUPAGE
# ============================================================

# Nombre de pages OCR envoyées dans un même appel d'édition.
# 6 à 10 est une bonne plage : au-delà, le risque de troncature grandit.
PAGES_PAR_BLOC = 8

# Nombre de lignes de contexte transmises de chaque côté d'une jonction.
LIGNES_CONTEXTE_RACCORD = 50


# ============================================================
# APPELS API
# ============================================================

MAX_OUTPUT_TOKENS = 16000

# Nombre total de tentatives par unité de travail (1 essai + 3 reprises).
MAX_TENTATIVES = 4

# Pause systématique entre deux appels, en secondes. Ménage les quotas.
PAUSE_ENTRE_APPELS = 1.0

# Base et plafond de l'attente exponentielle : 5, 10, 20, 40… plafonnés.
ATTENTE_BASE_BACKOFF = 5
ATTENTE_MAX_BACKOFF = 60

# Part d'aléa ajoutée à l'attente, pour éviter que plusieurs reprises ne se
# resynchronisent sur le même instant.
JITTER_BACKOFF = 0.25

# `None` signifie « ne pas transmettre le paramètre ». Certains modèles
# récents refusent `temperature` et échoueraient à l'appel.
TEMPERATURE = None

# `store=False` : les réponses ne sont pas conservées côté OpenAI.
# Le pipeline ne relit jamais une réponse passée, cette valeur ne retire donc
# aucune fonctionnalité — et c'est plus prudent pour une pièce sous droits.
STOCKER_REPONSES = False


# ============================================================
# RASTERISATION PDF (étape 1)
# ============================================================

# ------------------------------------------------------------
# Couche texte déjà présente dans le PDF
# ------------------------------------------------------------
# Beaucoup de PDF ont déjà été passés à l'OCR par un scanner ou par Acrobat, et
# portent donc une couche texte. La réutiliser évite un appel API par page.
#
# Mais une couche texte n'est pas forcément bonne : un OCR bas de gamme perd les
# accents, laisse des ligatures et peut fausser l'ordre de lecture. S'en servir à
# tort dégraderait tout le livre, puisque l'étape 2 a pour consigne de ne pas
# réécrire l'auteur. L'erreur coûteuse n'est pas de gaspiller des jetons, c'est
# d'accepter un mauvais texte.
#
#   "auto"     couche texte utilisée seulement si elle passe les contrôles
#              de qualité ci-dessous (recommandé)
#   "jamais"   toujours l'OCR Vision, quel que soit le PDF
#   "toujours" couche texte utilisée dès qu'elle existe, sans contrôle
#              (déconseillé : aucune garantie sur le résultat)
STRATEGIE_COUCHE_TEXTE = "auto"

STRATEGIES_COUCHE_TEXTE = ("auto", "jamais", "toujours")

# Nombre minimal de caractères pour qu'une page soit tenue pour porteuse de
# texte. En dessous, c'est une page image, une page de garde ou une couche
# résiduelle inexploitable.
MIN_CARACTERES_COUCHE_TEXTE = 200

# Part minimale de lettres parmi les caractères non blancs. Une couche texte
# dégradée abonde en symboles parasites.
MIN_RATIO_ALPHABETIQUE = 0.60

# Part minimale de caractères accentués. Un OCR ancien dépouille souvent le
# texte de ses accents : sur une page de français, leur absence totale est un
# signal fiable de mauvaise qualité. Seuil volontairement bas — il ne s'agit
# que d'écarter le zéro.
MIN_RATIO_ACCENTS = 0.005

# Part maximale de caractères de remplacement ou de contrôle.
MAX_RATIO_CARACTERES_SUSPECTS = 0.02

# Ligatures typographiques fréquentes dans une couche texte, et leur
# équivalent. Substitution déterministe et sans perte.
LIGATURES: dict[str, str] = {
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬀ": "ff",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
    "Ĳ": "IJ",
    "ĳ": "ij",
    "œ": "œ",  # conservé : lettre du français, non une ligature technique
}


DPI_RASTERISATION = 200

# Plancher de dégradation : si l'image dépasse la taille maximale, on réduit
# le DPI par paliers jusqu'à cette valeur avant d'abandonner.
DPI_MINIMAL = 110
FACTEUR_REDUCTION_DPI = 0.75

TAILLE_MAX_IMAGE_MO = 18.0


# ============================================================
# CONTRÔLES QUALITÉ
# ============================================================

# Rapport minimal entre longueur de sortie et longueur d'entrée, après
# neutralisation des marqueurs [PAGE X]. Une édition fidèle se situe entre
# 0,95 et 1,00 ; 0,80 laisse de la marge tout en détectant les troncatures.
RATIO_MINIMAL_LONGUEUR = 0.80

# Si True, un bloc déjà produit mais porteur d'avertissements est refait.
RETRAITER_BLOCS_SUSPECTS = True

# Bornes de variation admises pour un extrait passé en raccord.
#
# Garde-fou important : la passe de raccord réécrit les fichiers EN PLACE.
# Une réponse aberrante — modèle qui résume, qui réécrit, ou qui ne rend
# qu'une partie de l'extrait — détruirait donc du texte définitivement.
#
# Un raccord légitime ne fait que ressouder un mot, rétablir une ponctuation
# ou supprimer un doublon : la longueur ne doit quasiment pas bouger. Hors de
# ces bornes, la correction est refusée et l'extrait d'origine conservé.
RATIO_MINIMAL_RACCORD = 0.90
RATIO_MAXIMAL_RACCORD = 1.10

# Motifs dont la présence en sortie signale un problème : marqueur non
# supprimé, bavardage du modèle, refus, ou balise de code.
MOTIFS_INTERDITS: tuple[str, ...] = (
    r"<<<PAGE_BREAK>>>",
    r"^\s*\[PAGE\s+\d+\]\s*$",
    r"<DEBUT_OCR>",
    r"<FIN_OCR>",
    r"```",
    r"(?i)voici le texte",
    r"(?i)voici la version",
    r"(?i)texte corrigé",
    r"(?i)je ne peux pas",
    r"(?i)i can't assist",
    r"(?i)as an ai",
)

# Motifs interdits en sortie d'OCR. La liste diffère de celle de l'édition :
# l'OCR doit produire du texte NU, donc les marqueurs de page et la mise en
# forme y sont des anomalies, alors que l'édition les produit légitimement.
MOTIFS_INTERDITS_OCR: tuple[str, ...] = (
    r"<<<PAGE_BREAK>>>",
    r"\[PAGE\s+\d+\]",
    r"```",
    r"(?i)voici la transcription",
    r"(?i)voici le texte",
    r"(?i)transcription de la page",
    r"(?i)je ne peux pas",
    r"(?i)i can't assist",
    r"(?i)as an ai",
)


# ============================================================
# CLASSIFICATION STRUCTURELLE (voir ARCHITECTURE.md §9.1)
# ------------------------------------------------------------
# Les lexiques sont comparés à une forme normalisée : capitales, sans
# accents, sans ponctuation finale. On écrit donc « SCENE » et non « SCÈNE ».
# ============================================================

# Divisions de premier niveau → saut de page.
LEXIQUE_ACTE: frozenset[str] = frozenset({
    "ACTE",
    "PARTIE",
    "PROLOGUE",
    "EPILOGUE",
    "MOUVEMENT",
    "JOURNEE",
    "INTERMEDE",
})

# Divisions de second niveau → pas de saut de page.
LEXIQUE_SCENE: frozenset[str] = frozenset({
    "SCENE",
    "TABLEAU",
    "SEQUENCE",
    "FRAGMENT",
})

# Nombres et ordinaux écrits en lettres, reconnus comme jetons de
# numérotation. Sert à identifier un titre du type **UN.** ou **PREMIÈRE.**
NOMBRES_ECRITS: frozenset[str] = frozenset({
    "UN", "UNE", "DEUX", "TROIS", "QUATRE", "CINQ", "SIX", "SEPT", "HUIT",
    "NEUF", "DIX", "ONZE", "DOUZE", "TREIZE", "QUATORZE", "QUINZE", "SEIZE",
    "VINGT", "TRENTE",
    "PREMIER", "PREMIERE", "SECOND", "SECONDE", "DEUXIEME", "TROISIEME",
    "QUATRIEME", "CINQUIEME", "SIXIEME", "SEPTIEME", "HUITIEME", "NEUVIEME",
    "DIXIEME", "ONZIEME", "DOUZIEME", "TREIZIEME", "QUATORZIEME",
    "QUINZIEME", "SEIZIEME",
})

# Nombre minimal d'occurrences pour qu'un label soit tenu pour un personnage
# sur le seul critère statistique (règle 6).
SEUIL_OCCURRENCES_PERSONNAGE = 2

# En-têtes annonçant une distribution en tête d'ouvrage. Quand elle existe,
# c'est le signal le plus fiable pour identifier les personnages.
ETIQUETTES_DISTRIBUTION: frozenset[str] = frozenset({
    "PERSONNAGE",
    "PERSONNAGES",
    "DISTRIBUTION",
    "LES PERSONNAGES",
})

# Nombre maximal de lignes lues après une étiquette de distribution.
MAX_LIGNES_DISTRIBUTION = 60

# ------------------------------------------------------------
# Surcharges manuelles, prioritaires sur toute heuristique.
# Renseigner d'après la table d'inspection affichée avant génération.
# Écrire les labels en capitales sans accents : {"LA VOIX", "LE MESSAGER"}
# ------------------------------------------------------------
PERSONNAGES_FORCES: frozenset[str] = frozenset()
TITRES_ACTE_FORCES: frozenset[str] = frozenset()
TITRES_SCENE_FORCES: frozenset[str] = frozenset()


# ============================================================
# MARQUEURS — contrat entre les étapes (ARCHITECTURE.md §5)
# ------------------------------------------------------------
# Modifier ces valeurs invalide les fichiers OCR déjà produits.
# ============================================================

MARQUEUR_PAGE = "[PAGE {numero}]"
SEPARATEUR_PAGE = "\n\n<<<PAGE_BREAK>>>\n\n"

# Marqueurs insérés à la place d'une unité définitivement échouée, afin que le
# trou soit visible dans le fichier assemblé plutôt que silencieux.
MARQUEUR_ECHEC_PAGE = "[PAGE {numero} — ÉCHEC OCR]"
MARQUEUR_ECHEC_BLOC = "[BLOC {numero} — ÉCHEC ÉDITION]"

# Délimiteurs attendus dans la réponse de la passe de raccord.
DELIM_RACCORD_GAUCHE = "<<<BLOC_GAUCHE>>>"
DELIM_RACCORD_GAUCHE_FIN = "<<<FIN_BLOC_GAUCHE>>>"
DELIM_RACCORD_DROIT = "<<<BLOC_DROIT>>>"
DELIM_RACCORD_DROIT_FIN = "<<<FIN_BLOC_DROIT>>>"

# Délimiteurs encadrant le texte source envoyé au modèle.
DELIM_SOURCE_DEBUT = "<DEBUT_OCR>"
DELIM_SOURCE_FIN = "<FIN_OCR>"

# Délimiteurs encadrant le texte édité, à l'étape de validation, qui reçoit
# les deux versions dans un même message.
DELIM_EDIT_DEBUT = "<DEBUT_EDIT>"
DELIM_EDIT_FIN = "<FIN_EDIT>"

# Marque d'un passage réellement illisible.
MARQUE_ILLISIBLE = "*[texte illisible]*"

# Réponse exacte attendue du modèle de validation lorsqu'un bloc est sain.
# Sa présence permet de distinguer « bloc vérifié, rien à signaler » de
# « bloc non vérifié » — deux situations qu'un rapport vide confondrait.
MENTION_AUCUN_PROBLEME = "AUCUN PROBLEME DETECTE"

# Réponse attendue du modèle OCR pour une page dépourvue de texte.
# Sans elle, une page blanche produirait une réponse vide, indiscernable
# d'un échec d'appel.
MENTION_PAGE_SANS_TEXTE = "[PAGE SANS TEXTE]"

# Catégories de constats admises dans un rapport de validation. Le code s'en
# sert pour vérifier que le modèle a respecté le format imposé.
CATEGORIES_VALIDATION: tuple[str, ...] = (
    "LIGNE DISPARUE",
    "PERSONNAGE DISPARU",
    "DIDASCALIE PERDUE",
    "LIEU PERDU",
    "SCENE OUBLIEE",
    "TITRE OUBLIE",
    "TEXTE RACCOURCI",
    "PHRASE INACHEVEE",
    "RACCORD DEFECTUEUX",
)


# ============================================================
# STATUTS DES SIDECARS
# ------------------------------------------------------------
# Une unité n'est réputée terminée que si son sidecar porte STATUT_TERMINE.
# C'est le pivot de la reprise après interruption (ARCHITECTURE.md §7).
# ============================================================

STATUT_TERMINE = "termine"
STATUT_SUSPECT = "suspect"
STATUT_ECHEC = "echec"


# ============================================================
# GÉNÉRATION DOCX (étape 4)
# ============================================================

POLICE_TEXTE = "EB Garamond"

# Hiérarchie typographique : seuls les titres se détachent par le corps.
#
# Le nom de personnage n'a délibérément pas de constante propre : il doit
# rester de la taille du corps de texte, et le style le référence donc
# directement. Ainsi, changer le corps entraîne le personnage avec lui —
# c'est une relation voulue, non une coïncidence de valeurs.
#
# L'ordre TITRE_ACTE > TITRE_SCENE > TEXTE est vérifié par
# tests/test_config.py, pour qu'une retouche ne l'aplatisse pas par accident.
TAILLE_TITRE_ACTE_PT = 16
TAILLE_TITRE_SCENE_PT = 14
TAILLE_TEXTE_PT = 11

# Marges généreuses, en centimètres, sur les quatre côtés.
MARGE_CM = 3.0

# Saut de page avant chaque acte uniquement (décision n° 7).
SAUT_DE_PAGE_AVANT_ACTE = True
SAUT_DE_PAGE_AVANT_SCENE = False

# Préfixe des styles créés dans le document, pour ne jamais entrer en
# collision avec un style intégré de Word.
PREFIXE_STYLE = "Theatre_"

# Définition complète des six styles de paragraphe.
#
# L'alignement est exprimé en chaîne — et non via l'énumération de
# python-docx — pour que ce module reste dépourvu de dépendance externe.
# `docx_export` fait la correspondance.
#
# `saut_de_page` vaut None quand la valeur est portée par une constante
# dédiée ci-dessus, afin que le réglage reste à un seul endroit.
DEFINITIONS_STYLES: dict[str, dict[str, object]] = {
    "titre_acte": {
        "nom": "Titre_Acte",
        "alignement": "centre",
        "gras": True,
        "italique": False,
        "taille_pt": TAILLE_TITRE_ACTE_PT,
        # Espacement avant nul : le style porte déjà un saut de page, un
        # espacement en haut d'une page neuve ne ferait que décaler le titre.
        "espace_avant_pt": 0,
        "espace_apres_pt": 24,
        "saut_de_page": SAUT_DE_PAGE_AVANT_ACTE,
    },
    "titre_scene": {
        "nom": "Titre_Scene",
        "alignement": "centre",
        "gras": True,
        "italique": False,
        "taille_pt": TAILLE_TITRE_SCENE_PT,
        "espace_avant_pt": 24,
        "espace_apres_pt": 12,
        "saut_de_page": SAUT_DE_PAGE_AVANT_SCENE,
    },
    # En-tête d'une liste de rôles (« PERSONNAGES », « DISTRIBUTION »).
    # Type distinct des titres de scène afin de ne pas fausser le décompte
    # des scènes, et de rester neutre vis-à-vis de l'inférence de hiérarchie.
    # Réglable indépendamment : certaines éditions le composent en petites
    # capitales plutôt qu'en gras.
    "distribution": {
        "nom": "Distribution",
        "alignement": "centre",
        "gras": True,
        "italique": False,
        "taille_pt": TAILLE_TITRE_SCENE_PT,
        "espace_avant_pt": 24,
        "espace_apres_pt": 12,
        "saut_de_page": False,
    },
    "lieu": {
        "nom": "Lieu",
        "alignement": "centre",
        "gras": False,
        "italique": True,
        "taille_pt": TAILLE_TEXTE_PT,
        "espace_avant_pt": 12,
        "espace_apres_pt": 12,
        "saut_de_page": False,
    },
    "personnage": {
        "nom": "Personnage",
        "alignement": "centre",
        "gras": True,
        "italique": False,
        # Même corps que le texte : le nom se distingue par le gras et le
        # centrage, non par la taille.
        "taille_pt": TAILLE_TEXTE_PT,
        # Espacement après nul : la réplique doit adhérer au nom qui
        # l'annonce, sans quoi le lien entre les deux se perd visuellement.
        "espace_avant_pt": 12,
        "espace_apres_pt": 0,
        "saut_de_page": False,
    },
    "didascalie": {
        "nom": "Didascalie",
        "alignement": "centre",
        "gras": False,
        "italique": True,
        "taille_pt": TAILLE_TEXTE_PT,
        "espace_avant_pt": 6,
        "espace_apres_pt": 6,
        "saut_de_page": False,
    },
    "texte": {
        "nom": "Texte",
        "alignement": "justifie",
        "gras": False,
        "italique": False,
        "taille_pt": TAILLE_TEXTE_PT,
        "espace_avant_pt": 0,
        "espace_apres_pt": 6,
        "saut_de_page": False,
    },
}


# ============================================================
# SUFFIXES DE FICHIERS
# ------------------------------------------------------------
# Tous les chemins du pipeline dérivent du nom du livre et de ces suffixes,
# via `utils.io.resoudre_chemins()`.
# ============================================================

SUFFIXE_OCR = "_OCR.txt"
SUFFIXE_OCR_PAGES = "_OCR_pages"
SUFFIXE_EDIT = "_EDIT.txt"
SUFFIXE_EDIT_BLOCS = "_EDIT_blocs"
SUFFIXE_EDIT_RACCORDS = "_EDIT_raccords"
SUFFIXE_REPORT = "_REPORT.txt"
SUFFIXE_REPORT_BLOCS = "_REPORT_blocs"
SUFFIXE_DOCX = ".docx"

# Extension des fichiers temporaires de l'écriture atomique.
EXTENSION_TEMPORAIRE = ".tmp"

# Force l'écriture jusqu'au disque (os.fsync) avant de publier un fichier.
#
# À conserver à True en production : sur un Google Drive monté en FUSE, un
# os.replace() suivi d'une coupure pourrait publier un contenu encore en
# mémoire tampon. Le coût — quelques millisecondes par fichier — est
# négligeable face aux secondes que dure l'appel API qui l'a produit.
#
# La suite de tests le désactive : elle écrit des centaines de fichiers
# minuscules, sans appel API pour amortir la synchronisation.
ECRITURE_SYNCHRONE = True


# ============================================================
# JOURNALISATION
# ============================================================

NOM_JOURNAL = "journal_{etape}.json"

# Plafond du nombre d'appels conservés dans un journal. Au-delà, les plus
# anciens sont oubliés : un journal qui grossit sans fin finirait par coûter
# plus cher à réécrire que l'appel qu'il documente.
MAX_ENTREES_JOURNAL = 5000

# 0 = silencieux, 1 = normal, 2 = détaillé.
VERBOSITE = 1

# Nom de la variable d'environnement, et du secret Colab, portant la clé API.
NOM_CLE_API = "OPENAI_API_KEY"
