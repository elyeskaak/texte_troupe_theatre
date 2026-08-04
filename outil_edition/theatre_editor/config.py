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

# Étape 2 bis — rôles des pages liminaires. Un seul appel par livre, sur une
# tâche de jugement éditorial : on garde le modèle principal, le gain d'un
# modèle léger serait dérisoire face au risque d'un classement fautif.
MODEL_LIMINAIRES = "gpt-5.5-2026-04-23"


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


# ------------------------------------------------------------
# Détection des pages blanches, avant tout appel
# ------------------------------------------------------------
# Un livre imprimé comporte normalement des pages blanches : dos de page de
# titre, séparation entre parties, fin de cahier. Les soumettre au modèle
# vision coûte un appel pour rien, et l'expose à répondre autre chose que la
# mention attendue — une phrase qui serait alors écrite dans OCR.txt comme si
# c'était le texte de la pièce.
#
# Une page est donc examinée localement avant tout appel. Le test est
# volontairement **sévère** : une page réellement blanche l'est franchement,
# tandis qu'une page à l'impression pâle doit passer par la vision. Manquer une
# page blanche ne coûte qu'un appel ; sauter une page imprimée perdrait du
# texte.
DETECTER_PAGES_BLANCHES = True

# Résolution du test de blancheur. Très basse à dessein : une page blanche
# l'est à toute résolution, et 40 dpi rend le test instantané là où 200 dpi
# demanderait de parcourir deux millions d'octets par page.
DPI_TEST_BLANCHEUR = 40

# Un octet inférieur à ce seuil est compté comme de l'encre.
SEUIL_ENCRE = 200

# Proportion maximale d'encre pour qu'une page soit tenue pour blanche.
# 0,1 % laisse passer une poussière de numérisation, mais pas une ligne de
# texte : une seule ligne couvre déjà plus de 0,5 % d'une page.
PROPORTION_ENCRE_MAXIMALE = 0.001


# ============================================================
# CONTRÔLES QUALITÉ
# ============================================================

# Rapport minimal entre longueur de sortie et longueur d'entrée, après
# neutralisation des marqueurs [PAGE X]. Une édition fidèle se situe entre
# 0,95 et 1,00 ; 0,80 laisse de la marge tout en détectant les troncatures.
RATIO_MINIMAL_LONGUEUR = 0.80

# Si True, une unité déjà produite mais porteuse d'avertissements est refaite.
RETRAITER_BLOCS_SUSPECTS = True

# Nombre maximal de reprises d'une unité restée suspecte.
#
# Garde-fou indispensable. Sans plafond, une unité dont l'avertissement est
# **reproductible** est refaite à chaque exécution, indéfiniment — et repayée
# chaque fois. C'est le cas d'une page dont le texte imprimé contient une
# astérisque, ou d'un bloc que le modèle abrège systématiquement : réessayer ne
# peut rien changer.
#
# Passé ce nombre, l'unité est acceptée avec ses avertissements, qui restent
# consignés dans son sidecar, dans le journal et dans le rapport.
MAX_REPRISES_SUSPECTES = 2

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
#
# « je ne peux pas » n'y figure pas, à dessein : c'est une réplique banale
# (« je ne peux pas te le dire »), et la signaler marquait le bloc suspect —
# au point de le faire disparaître du fichier assemblé. Un vrai refus de
# transcription est capté par `est_declaration_echec` (§9.7), qui exige que
# l'objet du verbe soit la page, ce qu'une réplique n'a pas.
MOTIFS_INTERDITS: tuple[str, ...] = (
    r"<<<PAGE_BREAK>>>",
    r"^\s*\[PAGE\s+\d+\]\s*$",
    r"<DEBUT_OCR>",
    r"<FIN_OCR>",
    r"```",
    r"(?i)voici le texte",
    r"(?i)voici la version",
    r"(?i)texte corrigé",
    r"(?i)i can't assist",
    r"(?i)as an ai",
)

# Motifs interdits en sortie d'OCR. La liste diffère de celle de l'édition :
# l'OCR doit produire du texte NU, donc les marqueurs de page et la mise en
# forme y sont des anomalies, alors que l'édition les produit légitimement.
#
# Comme pour MOTIFS_INTERDITS, « je ne peux pas » en est absent : le motif se
# déclenchait sur une réplique (« WANG. Je ne peux pas te le dire ») et faisait
# perdre la page. Le vrai refus reste capté par `est_declaration_echec` (§9.7).
MOTIFS_INTERDITS_OCR: tuple[str, ...] = (
    r"<<<PAGE_BREAK>>>",
    r"\[PAGE\s+\d+\]",
    r"```",
    r"(?i)voici la transcription",
    r"(?i)voici le texte",
    r"(?i)transcription de la page",
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

# Formulations par lesquelles un modèle signale une page sans texte.
#
# Le prompt impose la mention ci-dessus, mais un modèle paraphrase parfois.
# Sans ces variantes, sa phrase — « Cette page est vide. » — serait écrite dans
# OCR.txt **comme si c'était le texte de la pièce**, puis rendue dans le DOCX.
# C'est pire qu'une erreur : une corruption silencieuse du texte.
MOTIFS_DECLARATION_PAGE_VIDE: tuple[str, ...] = (
    r"\[?\s*page\s+sans\s+texte\s*\]?",
    r"page\s+(?:est\s+)?(?:vide|blanche)",
    r"(?:aucun|pas\s+de|n'y\s+a\s+(?:pas|aucun))\s+(?:texte|contenu)",
    r"page\s+(?:is\s+)?(?:blank|empty)",
    r"no\s+(?:text|content)",
)

# Une déclaration de page vide est nécessairement courte. Ce plafond évite de
# prendre pour telle une page réelle où figurerait par hasard une de ces
# formules : une page de théâtre dépasse largement cette longueur.
MAX_LONGUEUR_DECLARATION_VIDE = 200

# Formulations par lesquelles un modèle signale qu'il n'a **pas pu** lire une
# page. C'est distinct d'une page vide, et bien plus dangereux.
#
# Sans ces motifs, « Erreur - Impossible d'OCR cette page » était écrit dans
# OCR.txt avec le statut « terminé » : le message d'erreur devenait le texte de
# la pièce, sans la moindre alerte, et la page n'était jamais reprise.
#
# Une telle réponse doit au contraire compter comme un **échec**, donc être
# retentée puis signalée.
# Fragments réutilisés, pour éviter de les répéter — et de les corriger à
# moitié. `_APOSTROPHE` couvre les trois formes que les modèles alternent ;
# `_OBJET_PAGE` est ce qui distingue une déclaration d'échec d'une réplique.
_APOSTROPHE = r"['’‘]"

# L'objet du verbe est le discriminant décisif. « Je ne peux pas lire cette
# page » est un échec ; « Je ne peux pas lire dans tes pensées » est une
# réplique. Exiger que le complément soit la page elle-même sépare les deux,
# là où un critère purement lexical les confondrait.
_OBJET_PAGE = (
    rf"(?:cette|ce|la|le|l{_APOSTROPHE}|votre|the|this)?\s*"
    r"(?:page|image|document|texte|contenu|fichier)"
)

MOTIFS_ECHEC_TRANSCRIPTION: tuple[str, ...] = (
    r"^\W*erreur\b",
    rf"impossible\s+(?:d{_APOSTROPHE}|de\s+)?\s*(?:l{_APOSTROPHE})?\s*ocr",
    r"impossible\s+de\s+(?:lire|transcrire|traiter|d[eé]chiffrer|ocris[eé]r)",
    # Le `ne` peut être élidé — « je n'arrive pas » — et le `à` absent —
    # « je ne peux pas lire ». Les deux formes étaient auparavant manquées.
    rf"je\s+n(?:e\s+|{_APOSTROPHE})(?:peux|parviens|r[eé]ussis|arrive|suis)"
    rf"\s+pas(?:\s+(?:à|en\s+mesure\s+de))?\s*"
    rf"(?:lire|transcrire|traiter|d[eé]chiffrer)\s+{_OBJET_PAGE}",
    rf"{_OBJET_PAGE}\s+(?:est\s+)?(?:illisible|corrompue?|inexploitable)",
    rf"(?:unable|failed|cannot|can{_APOSTROPHE}t)\s+to\s+"
    r"(?:read|process|transcribe|ocr)",
    r"^\W*error\b",
)

# Une déclaration d'échec est courte elle aussi. Au-delà, c'est du texte.
MAX_LONGUEUR_DECLARATION_ECHEC = 300

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
TAILLE_TITRE_OEUVRE_PT = 22
TAILLE_TITRE_ACTE_PT = 16
TAILLE_TITRE_SCENE_PT = 14
TAILLE_TEXTE_PT = 11

# Un intitulé n'est reconnu comme titre de l'œuvre que s'il figure dans les
# toutes premières lignes du document. Au-delà, ce n'est plus une page de titre.
MAX_LIGNE_TITRE_OEUVRE = 12

# Marges généreuses, en centimètres, sur les quatre côtés.
MARGE_CM = 3.0

# Saut de page avant chaque acte uniquement (décision n° 7).
SAUT_DE_PAGE_AVANT_ACTE = True
SAUT_DE_PAGE_AVANT_SCENE = False

# La liste des personnages occupe une page à part entière, comme dans les
# éditions imprimées : saut de page avant l'en-tête, et après la liste.
SAUT_DE_PAGE_AVANT_DISTRIBUTION = True
SAUT_DE_PAGE_APRES_DISTRIBUTION = True

# Préfixe des styles créés dans le document, pour ne jamais entrer en
# collision avec un style intégré de Word.
PREFIXE_STYLE = "Theatre_"

# Longueur au-delà de laquelle une ligne en italique est traitée comme de la
# prose et non comme une didascalie brève.
#
# Une didascalie tient en quelques mots — « Pause. », « Elle sort. » — et se
# centre. Un monologue liminaire ou une note d'éditeur en italique fait des
# centaines de caractères : centré, il deviendrait illisible.
LONGUEUR_DIDASCALIE_LONGUE = 180

# Numéros de page décorés, que certaines éditions encadrent de filets :
#
#     ——— 7 ———        - 52 -        « 19 »
#
# L'étape 2 doit les supprimer, mais sa consigne ne parle que de « numéros de
# pages imprimés isolés » : la version décorée peut lui échapper. Ce filet
# déterministe les retire à l'étape 4, sans coût ni appel.
MOTIF_NUMERO_DE_PAGE_DECORE = r"^[\s\-–—_=«»<>|.·•*]*\d{1,4}[\s\-–—_=«»<>|.·•*]*$"

# Définition complète des six styles de paragraphe.
#
# L'alignement est exprimé en chaîne — et non via l'énumération de
# python-docx — pour que ce module reste dépourvu de dépendance externe.
# `docx_export` fait la correspondance.
#
# `saut_de_page` vaut None quand la valeur est portée par une constante
# dédiée ci-dessus, afin que le réglage reste à un seul endroit.
DEFINITIONS_STYLES: dict[str, dict[str, object]] = {
    # Titre de l'œuvre, sur la page de titre.
    #
    # Reconnu par une règle étroite (§ `blocks`) : le premier intitulé en gras
    # du document, lorsqu'aucun autre indice ne permet de le classer. Sans elle,
    # le titre d'un recueil se retrouvait rendu en corps 11 comme un nom de
    # personnage.
    "titre_oeuvre": {
        "nom": "Titre_Oeuvre",
        "alignement": "centre",
        "gras": True,
        "italique": False,
        "taille_pt": TAILLE_TITRE_OEUVRE_PT,
        "espace_avant_pt": 0,
        "espace_apres_pt": 36,
        "saut_de_page": False,
    },
    # Auteur, traducteur, sous-titre, éditeur : les lignes qui accompagnent le
    # titre sur la page de titre, et les intitulés de section des liminaires.
    "titre_secondaire": {
        "nom": "Titre_Secondaire",
        "alignement": "centre",
        "gras": False,
        "italique": True,
        "taille_pt": TAILLE_TITRE_SCENE_PT,
        "espace_avant_pt": 6,
        "espace_apres_pt": 12,
        "saut_de_page": False,
    },
    # Citation en exergue : italique, justifiée, détachée du corps.
    "epigraphe": {
        "nom": "Epigraphe",
        "alignement": "justifie",
        "gras": False,
        "italique": True,
        "taille_pt": TAILLE_TEXTE_PT,
        "espace_avant_pt": 18,
        "espace_apres_pt": 4,
        "saut_de_page": False,
    },
    # Source d'une épigraphe. Alignée à droite, comme dans l'usage imprimé —
    # c'est le défaut que je n'avais pas su corriger sans cette passe.
    "attribution": {
        "nom": "Attribution",
        "alignement": "droite",
        "gras": False,
        "italique": True,
        "taille_pt": TAILLE_TEXTE_PT,
        "espace_avant_pt": 2,
        "espace_apres_pt": 18,
        "saut_de_page": False,
    },
    # Note d'éditeur, mention de création, copyright, liste d'œuvres.
    "note": {
        "nom": "Note",
        "alignement": "justifie",
        "gras": False,
        "italique": False,
        "taille_pt": TAILLE_TEXTE_PT,
        "espace_avant_pt": 6,
        "espace_apres_pt": 6,
        "saut_de_page": False,
    },
    # Prose continue précédant l'action. Justifiée en italique : c'est un récit,
    # non une didascalie, et le centrer serait illisible.
    "prologue": {
        "nom": "Prologue",
        "alignement": "justifie",
        "gras": False,
        "italique": True,
        "taille_pt": TAILLE_TEXTE_PT,
        "espace_avant_pt": 6,
        "espace_apres_pt": 6,
        "saut_de_page": False,
    },
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
        # Espacement avant nul : le style porte un saut de page.
        "espace_avant_pt": 0,
        "espace_apres_pt": 18,
        "saut_de_page": SAUT_DE_PAGE_AVANT_DISTRIBUTION,
    },
    # Entrées de la liste des rôles : « DON PÉDRO, prince d'Aragon. »
    #
    # Alignées à gauche et non justifiées : ce sont des lignes courtes, et une
    # justification les étirerait d'un bord à l'autre de la page.
    "entree_distribution": {
        "nom": "Entree_Distribution",
        "alignement": "gauche",
        "gras": False,
        "italique": False,
        "taille_pt": TAILLE_TEXTE_PT,
        "espace_avant_pt": 0,
        "espace_apres_pt": 2,
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
    # Didascalie longue, ou prose en italique : monologue liminaire, note de
    # l'éditeur, épigraphe développée.
    #
    # Centrer un paragraphe de quarante lignes serait illisible. Le seuil de
    # bascule est `LONGUEUR_DIDASCALIE_LONGUE`.
    "didascalie_longue": {
        "nom": "Didascalie_Longue",
        "alignement": "justifie",
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
# DISPOSITION DES FICHIERS SUR LE DRIVE
# ------------------------------------------------------------
# Le dossier principal ne montre que ce qui vous intéresse : le PDF source et
# le DOCX final. Tout le travail intermédiaire vit dans un sous-dossier par
# livre, ce qui garde le Drive lisible même avec plusieurs pièces en cours.
#
#     Troupe 122 - 2026-27/
#         Le Malentendu.pdf              ← votre source
#         Le Malentendu.docx             ← le résultat
#         temp/
#             journal_ocr.json …
#             Le Malentendu/
#                 OCR.txt
#                 OCR_pages/
#                 EDIT.txt               ← à corriger à la main au besoin
#                 EDIT_blocs/
#                 EDIT_raccords/
#                 REPORT.txt             ← à relire une fois
#                 REPORT_blocs/
#
# Tous les chemins dérivent du nom du livre, via `utils.io.resoudre_chemins()`.
# ============================================================

DOSSIER_TEMPORAIRE = "temp"

# Les livres à écarter du traitement sont listés dans un fichier unique,
# `ignorer.txt`, posé dans le dossier de travail à côté des PDF :
#
#     Troupe 122 - 2026-27/
#         La mastication des morts.pdf
#         Roberto Zucco.pdf
#         ignorer.txt        ← contient la ligne « La mastication des morts »
#
# Un nom de livre par ligne (l'extension .pdf est facultative). Les lignes
# vides et celles commençant par « # » sont ignorées : on peut y laisser des
# commentaires. La comparaison neutralise la casse et l'extension, ce fichier
# étant édité à la main.
#
# Se gère entièrement depuis le Drive, sans toucher au code. Les livres écartés
# sont toujours **annoncés** au lancement : un livre laissé de côté en silence
# serait une mauvaise surprise trois semaines plus tard.
NOM_FICHIER_IGNORER = "ignorer.txt"

NOM_OCR = "OCR.txt"
NOM_OCR_PAGES = "OCR_pages"
NOM_EDIT = "EDIT.txt"
NOM_EDIT_BLOCS = "EDIT_blocs"
NOM_EDIT_RACCORDS = "EDIT_raccords"
NOM_REPORT = "REPORT.txt"
NOM_REPORT_BLOCS = "REPORT_blocs"

# Annotations des pages liminaires, produites par une passe IA dédiée.
#
# Mises en cache : l'appel est payé **une seule fois par livre**, et l'étape 4
# reste gratuite et déterministe — vous pouvez régénérer le DOCX autant de fois
# que vous voulez après avoir changé une marge.
#
# Si le fichier est absent, l'étape 4 fonctionne exactement comme avant : les
# liminaires sont classés par les règles déterministes.
NOM_LIMINAIRES = "LIMINAIRES.json"

# Nombre maximal de lignes soumises à la passe des liminaires.
#
# Les ambiguïtés de rôle — titre, auteur, épigraphe, prologue, distribution —
# vivent toutes dans les premières pages. Y consacrer un appel est
# proportionné ; en consacrer un par bloc sur tout le livre ne le serait pas.
LIGNES_LIMINAIRES = 120

# Rôles admis en retour de cette passe. Un rôle inconnu est ignoré, la ligne
# retombant sur son classement déterministe.
ROLES_LIMINAIRES: frozenset[str] = frozenset({
    "titre_oeuvre",
    "titre_secondaire",
    "epigraphe",
    "attribution",
    "note",
    "distribution",
    "entree_distribution",
    "titre_acte",
    "titre_scene",
    "personnage",
    "didascalie",
    "prologue",
    "texte",
})

SUFFIXE_DOCX = ".docx"

# ------------------------------------------------------------
# Sortie destinée à l'outil de répétition (../outil_repetition/).
# ------------------------------------------------------------
#
# Écrite par `repet_export.py` pendant l'étape 4, à partir de l'index de
# structure déjà construit pour le DOCX. Aucune IA, aucun appel, aucun coût :
# c'est le même parcours du document qui sert aux deux sorties.
#
# Le fichier est **visible dans le dossier principal**, à côté du DOCX, parce
# qu'il est fait pour être transféré sur un téléphone. C'est la seule exception
# à la règle « le dossier principal ne montre que le PDF et le DOCX », et elle
# est délibérée : un livrable rangé dans temp/ serait introuvable.
SUFFIXE_REPET = "_REPET.json"

# Version du schéma du fichier de répétition.
#
# L'outil de répétition refuse un schéma qu'il ne connaît pas, au lieu de
# l'interpréter au mieux. À incrémenter dès qu'un champ change de sens — jamais
# quand un champ est seulement ajouté.
SCHEMA_REPET = "repetition/2"

# ------------------------------------------------------------
# Suffixes de l'ancienne disposition, à plat dans le dossier principal.
#
# Conservés pour `io.migrer_livre()` : sans migration, les fichiers déjà
# produits deviendraient invisibles et tout serait retranscrit, donc repayé.
# ------------------------------------------------------------

SUFFIXE_OCR = "_OCR.txt"
SUFFIXE_OCR_PAGES = "_OCR_pages"
SUFFIXE_EDIT = "_EDIT.txt"
SUFFIXE_EDIT_BLOCS = "_EDIT_blocs"
SUFFIXE_EDIT_RACCORDS = "_EDIT_raccords"
SUFFIXE_REPORT = "_REPORT.txt"
SUFFIXE_REPORT_BLOCS = "_REPORT_blocs"

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
