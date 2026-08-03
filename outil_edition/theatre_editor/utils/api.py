"""
Couche d'accès à l'API OpenAI, mutualisée par les trois étapes IA.

Ce module existe pour une raison précise : `ocr.py`, `edition.py` et
`validation.py` ont tous les trois besoin de la même mécanique — construction
de la requête, réessais, extraction du texte, chronométrage, comptage des
jetons. Sans module commun, cette logique serait recopiée trois fois, donc
divergerait.

**Responses API exclusivement** (`client.responses.create`). Chat Completions
n'est jamais utilisée. Un seul point d'entrée, `appeler_modele()`, sert aussi
bien le texte que la vision : la seule différence est la présence d'une image
dans l'entrée.

Deux partis pris de robustesse méritent d'être signalés :

- **Les erreurs non réessayables échouent immédiatement.** Une clé invalide ou
  un identifiant de modèle inexistant ne deviendront pas valides en attendant :
  réessayer quatre fois avec attente exponentielle ne ferait que perdre plus
  d'une minute avant d'afficher la même erreur. Le tri se fait sur le code HTTP,
  et non sur les classes d'exception du SDK, ce qui le rend testable sans
  dépendance et insensible aux renommages internes du SDK.
- **La troncature est détectée.** La Responses API signale une réponse coupée
  par `status == "incomplete"`. Sans ce contrôle, un bloc tronqué à
  `MAX_OUTPUT_TOKENS` serait enregistré comme un succès, et du texte
  disparaîtrait silencieusement — exactement ce que le pipeline doit empêcher.
"""

from __future__ import annotations

import base64
import random
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from theatre_editor import config
from theatre_editor.utils import io, logging as journalisation


# ============================================================
# 1. EXCEPTIONS
# ============================================================


class ErreurAPI(RuntimeError):
    """Erreur de la couche API."""


class EchecAppelAPI(ErreurAPI):
    """Toutes les tentatives ont échoué."""


class ReponseVide(ErreurAPI):
    """Le modèle n'a renvoyé aucun texte exploitable."""


# ============================================================
# 2. RÉSULTAT D'UN APPEL
# ============================================================


@dataclass(frozen=True)
class ResultatAppel:
    """
    Tout ce qu'un appel produit, y compris ce qui alimente le journal.

    `avertissements` porte les anomalies constatées au niveau de l'appel
    lui-même (troncature, réponse anormale), distinctes des contrôles de
    contenu qu'effectue `blocks.verifier_sortie()`.
    """

    texte: str
    modele: str
    response_id: str | None
    tentative: int
    duree_secondes: float
    tokens_entree: int | None = None
    tokens_sortie: int | None = None
    tronquee: bool = False
    avertissements: list[str] = field(default_factory=list)

    def champs_journal(self) -> dict[str, Any]:
        """Champs à consigner dans le journal de l'étape."""
        return {
            "modele": self.modele,
            "response_id": self.response_id,
            "duree_secondes": self.duree_secondes,
            "tentative_reussie": self.tentative,
            "tokens_entree": self.tokens_entree,
            "tokens_sortie": self.tokens_sortie,
            "longueur_sortie": len(self.texte),
        }


# ============================================================
# 3. CLIENT
# ============================================================


@lru_cache(maxsize=1)
def _module_openai():
    """
    Importe `openai` à la demande.

    Import différé volontairement : importer `theatre_editor.utils.api` ne doit
    pas échouer sur une machine où `openai` n'est pas installé. Cela permet aux
    tests des parties pures de ce module de s'exécuter sans dépendance.
    """
    try:
        import openai
    except ImportError as erreur:  # pragma: no cover - dépend de l'environnement
        raise ErreurAPI(
            "La bibliothèque « openai » est introuvable.\n"
            "Installez-la :  pip install -U openai"
        ) from erreur

    return openai


@lru_cache(maxsize=1)
def obtenir_client():
    """
    Retourne le client OpenAI, construit une seule fois.

    Mis en cache : un client par processus suffit, et il réutilise ses
    connexions HTTP — ce qui compte sur les centaines d'appels d'un livre.
    """
    return _module_openai().OpenAI(api_key=io.charger_cle_api())


def reinitialiser_client() -> None:
    """
    Oublie le client mis en cache.

    Utile dans un notebook après avoir corrigé une clé API : sans cela, le
    client fautif resterait en cache pour toute la session.
    """
    obtenir_client.cache_clear()


# ============================================================
# 4. CONSTRUCTION DE LA REQUÊTE
# ============================================================


def encoder_image_png(image_png: bytes) -> str:
    """Encode une image PNG en URL de données, format attendu par l'API."""
    encodee = base64.b64encode(image_png).decode("ascii")

    return f"data:image/png;base64,{encodee}"


def construire_entree(
    message: str,
    image_png: bytes | None = None,
) -> list[dict[str, Any]]:
    """
    Construit le paramètre `input` de la Responses API.

    Les types de contenu sont ceux de la Responses API — `input_text` et
    `input_image` — et non ceux de Chat Completions (`text`, `image_url`).
    C'est une source de confusion classique lors d'une migration.
    """
    contenu: list[dict[str, Any]] = [{"type": "input_text", "text": message}]

    if image_png is not None:
        contenu.append(
            {"type": "input_image", "image_url": encoder_image_png(image_png)}
        )

    return [{"role": "user", "content": contenu}]


def construire_parametres(
    *,
    modele: str,
    instructions: str,
    message: str,
    image_png: bytes | None = None,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    """
    Assemble les paramètres de `responses.create()`.

    `temperature` n'est transmis que si `config.TEMPERATURE` n'est pas None :
    certains modèles récents rejettent ce paramètre, et l'envoyer
    systématiquement ferait échouer chaque appel après un changement de modèle.
    """
    parametres: dict[str, Any] = {
        "model": modele,
        "instructions": instructions,
        "input": construire_entree(message, image_png),
        "max_output_tokens": max_output_tokens or config.MAX_OUTPUT_TOKENS,
        "store": config.STOCKER_REPONSES,
    }

    if config.TEMPERATURE is not None:
        parametres["temperature"] = config.TEMPERATURE

    return parametres


# ============================================================
# 5. LECTURE DE LA RÉPONSE
# ============================================================


def extraire_texte(reponse: Any) -> str:
    """
    Extrait le texte d'une réponse.

    `output_text` est l'accès direct fourni par le SDK. Le repli parcourt la
    structure `output → content → text`, ce qui couvre les réponses dont le
    premier élément n'est pas du texte (un bloc de raisonnement, par exemple).

    Raises:
        ReponseVide: si aucun texte n'est exploitable.
    """
    texte = getattr(reponse, "output_text", None)

    if texte and texte.strip():
        return texte.strip()

    morceaux: list[str] = []

    for element in getattr(reponse, "output", None) or []:
        for partie in getattr(element, "content", None) or []:
            valeur = getattr(partie, "text", None)
            if valeur:
                morceaux.append(valeur)

    if morceaux:
        return "\n".join(morceaux).strip()

    raise ReponseVide("Le modèle n'a renvoyé aucun texte exploitable.")


def raison_troncature(reponse: Any) -> str | None:
    """
    Retourne la raison d'une troncature, ou None si la réponse est complète.

    Contrôle essentiel : une réponse coupée à `MAX_OUTPUT_TOKENS` contient du
    texte parfaitement valide, simplement incomplet. Sans cette vérification,
    elle serait enregistrée comme un succès et la fin du bloc disparaîtrait.
    """
    if getattr(reponse, "status", None) != "incomplete":
        return None

    details = getattr(reponse, "incomplete_details", None)

    return getattr(details, "reason", None) or "raison non précisée"


def lire_jetons(reponse: Any) -> tuple[int | None, int | None]:
    """Retourne (jetons d'entrée, jetons de sortie), si l'API les fournit."""
    usage = getattr(reponse, "usage", None)

    if usage is None:
        return None, None

    return (
        getattr(usage, "input_tokens", None),
        getattr(usage, "output_tokens", None),
    )


# ============================================================
# 6. POLITIQUE DE RÉESSAI
# ============================================================

# Codes HTTP qu'il est inutile de réessayer : la requête ou les droits sont en
# cause, pas un aléa passager. Réessayer ne changerait rien et retarderait
# l'affichage de l'erreur réelle de plus d'une minute.
CODES_NON_REESSAYABLES = frozenset({400, 401, 403, 404, 422})


def _code_http(erreur: BaseException) -> int | None:
    """Extrait le code HTTP d'une exception, s'il y en a un."""
    code = getattr(erreur, "status_code", None)

    if code is None:
        reponse = getattr(erreur, "response", None)
        code = getattr(reponse, "status_code", None)

    return code if isinstance(code, int) else None


def est_reessayable(erreur: BaseException) -> bool:
    """
    Détermine si une erreur justifie une nouvelle tentative.

    Le tri se fonde sur le code HTTP plutôt que sur les classes d'exception du
    SDK : c'est testable sans installer `openai`, et insensible à une
    réorganisation interne du SDK.

    Une exception sans code HTTP est réessayée — c'est le cas des erreurs
    réseau et des délais dépassés, qui sont précisément transitoires.
    """
    if isinstance(erreur, ReponseVide):
        return True

    code = _code_http(erreur)

    if code is None:
        return True

    return code not in CODES_NON_REESSAYABLES


def calculer_attente(tentative: int) -> float:
    """
    Calcule l'attente avant la tentative suivante.

    Attente exponentielle plafonnée, plus un aléa. L'aléa n'est pas cosmétique :
    sans lui, plusieurs reprises déclenchées par le même incident se
    resynchroniseraient sur le même instant et provoqueraient une nouvelle
    salve d'erreurs de quota.

    Args:
        tentative: numéro de la tentative qui vient d'échouer, à partir de 1.
    """
    base = config.ATTENTE_BASE_BACKOFF * (2 ** (tentative - 1))
    attente = min(config.ATTENTE_MAX_BACKOFF, base)

    return round(attente + random.uniform(0, config.JITTER_BACKOFF * attente), 2)


def patienter() -> None:
    """
    Marque la pause régulière entre deux appels.

    Appelée par les orchestrateurs, et non par `appeler_modele()` : la cadence
    relève de la boucle de traitement, pas d'un appel isolé.
    """
    if config.PAUSE_ENTRE_APPELS > 0:
        time.sleep(config.PAUSE_ENTRE_APPELS)


# ============================================================
# 7. APPEL
# ============================================================


def appeler_modele(
    *,
    modele: str,
    instructions: str,
    message: str,
    image_png: bytes | None = None,
    max_output_tokens: int | None = None,
    libelle: str = "",
) -> ResultatAppel:
    """
    Appelle un modèle via la Responses API, avec réessais.

    Point d'entrée unique des trois étapes IA. Fournir `image_png` bascule
    l'appel en mode vision, sans autre changement.

    Args:
        modele: identifiant du modèle.
        instructions: prompt système, chargé depuis `prompts/`.
        message: contenu utilisateur.
        image_png: image à joindre, pour l'OCR.
        max_output_tokens: `config.MAX_OUTPUT_TOKENS` par défaut.
        libelle: intitulé de l'unité traitée, pour les messages de console.

    Returns:
        Le résultat, y compris les avertissements constatés.

    Raises:
        EchecAppelAPI: après épuisement des tentatives, ou immédiatement pour
            une erreur non réessayable.
    """
    parametres = construire_parametres(
        modele=modele,
        instructions=instructions,
        message=message,
        image_png=image_png,
        max_output_tokens=max_output_tokens,
    )

    client = obtenir_client()
    derniere_erreur: BaseException | None = None

    for tentative in range(1, config.MAX_TENTATIVES + 1):
        try:
            with journalisation.Chrono() as chrono:
                reponse = client.responses.create(**parametres)

            return _construire_resultat(
                reponse=reponse,
                modele=modele,
                tentative=tentative,
                duree=chrono.secondes,
                libelle=libelle,
            )

        except Exception as erreur:
            derniere_erreur = erreur

            if not est_reessayable(erreur):
                raise EchecAppelAPI(
                    f"Erreur non réessayable{_suffixe(libelle)} : {erreur}\n"
                    f"Vérifiez la clé API et l'identifiant du modèle "
                    f"« {modele} »."
                ) from erreur

            journalisation.alerte(
                f"tentative {tentative}/{config.MAX_TENTATIVES}"
                f"{_suffixe(libelle)} : {erreur}"
            )

            if tentative < config.MAX_TENTATIVES:
                attente = calculer_attente(tentative)
                journalisation.detail(f"nouvelle tentative dans {attente} s")
                time.sleep(attente)

    raise EchecAppelAPI(
        f"Échec après {config.MAX_TENTATIVES} tentatives"
        f"{_suffixe(libelle)} : {derniere_erreur}"
    ) from derniere_erreur


def _suffixe(libelle: str) -> str:
    """Ajoute l'intitulé de l'unité à un message, s'il est renseigné."""
    return f" ({libelle})" if libelle else ""


def _construire_resultat(
    *,
    reponse: Any,
    modele: str,
    tentative: int,
    duree: float,
    libelle: str,
) -> ResultatAppel:
    """Assemble le résultat et relève les anomalies de l'appel."""
    avertissements: list[str] = []

    raison = raison_troncature(reponse)

    if raison is not None:
        message = f"réponse tronquée par l'API ({raison})"
        avertissements.append(message)
        journalisation.alerte(f"{message}{_suffixe(libelle)}")

    tokens_entree, tokens_sortie = lire_jetons(reponse)

    return ResultatAppel(
        texte=extraire_texte(reponse),
        modele=modele,
        response_id=getattr(reponse, "id", None),
        tentative=tentative,
        duree_secondes=duree,
        tokens_entree=tokens_entree,
        tokens_sortie=tokens_sortie,
        tronquee=raison is not None,
        avertissements=avertissements,
    )


# ============================================================
# 8. INSPECTION DES MODÈLES
# ============================================================


def lister_modeles_disponibles(motif: str | None = None) -> list[str]:
    """
    Liste les modèles accessibles avec la clé courante.

    Sert à vérifier depuis un notebook qu'un identifiant de `config.py` existe
    réellement. C'est ce contrôle qui a révélé que `gpt-5.5-mini` n'existe pas,
    et conduit à retenir `gpt-5.4-mini` pour la passe de raccord.

    Args:
        motif: filtre de sous-chaîne, insensible à la casse.
    """
    modeles = sorted(modele.id for modele in obtenir_client().models.list())

    if motif:
        aiguille = motif.lower()
        modeles = [identifiant for identifiant in modeles if aiguille in identifiant.lower()]

    return modeles


# Modèles configurés, associés à l'étape qui les utilise.
MODELES_CONFIGURES: dict[str, str] = {
    "ocr": config.MODEL_OCR,
    "edition": config.MODEL_EDITION,
    "raccord": config.MODEL_RACCORD,
    "validation": config.MODEL_VALIDATION,
}


def verifier_modeles_configures() -> dict[str, bool]:
    """
    Vérifie que les quatre modèles de `config.py` sont disponibles.

    À lancer une fois avant de traiter un livre : découvrir qu'un identifiant
    est erroné après trois heures d'OCR coûte cher, le découvrir en deux
    secondes ne coûte rien.

    Returns:
        étape → disponibilité.
    """
    disponibles = set(lister_modeles_disponibles())

    resultats = {
        etape: modele in disponibles for etape, modele in MODELES_CONFIGURES.items()
    }

    for etape, present in resultats.items():
        modele = MODELES_CONFIGURES[etape]

        if present:
            journalisation.succes(f"{etape:<11} {modele}")
        else:
            journalisation.echec(f"{etape:<11} {modele} — introuvable sur ce compte")

    return resultats
