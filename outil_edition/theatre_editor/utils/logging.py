"""
Affichage console et journalisation JSON.

Deux responsabilités, volontairement réunies : ce sont les deux façons de
rendre compte de ce que fait le pipeline, et elles partagent le même besoin de
respecter `config.VERBOSITE`.

Aucun `print()` ne doit apparaître ailleurs dans le code métier. Passer par ce
module rend un changement de verbosité, de format ou de destination local à un
seul fichier.

Note sur le nom du module : `theatre_editor.utils.logging` masquerait le module
`logging` de la bibliothèque standard pour un import *relatif*. Python 3
n'utilisant que des imports absolus, il n'y a pas de conflit — un
`import logging` depuis un autre module du paquet charge bien la stdlib.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from theatre_editor import config
from theatre_editor.utils import io

# Largeur des filets de séparation, alignée sur une console Colab standard.
LARGEUR = 72

# Seuils de verbosité.
_SILENCIEUX = 0
_NORMAL = 1
_DETAILLE = 2


# ============================================================
# 1. AFFICHAGE CONSOLE
# ============================================================


def preparer_console() -> None:
    """
    Rend la console capable d'écrire du français — et les symboles de ce module.

    La console Windows par défaut est en cp1252, qui ne sait ni les guillemets
    typographiques d'un texte de théâtre, ni le `⚠` de `alerte()` ci-dessous.
    Sans cela, le pipeline s'interrompt sur un `UnicodeEncodeError` **après**
    avoir fait son travail : le résultat est écrit, mais l'utilisateur ne voit
    qu'une trace d'erreur et croit à un échec. Le reste du projet tourne dans
    Colab, en UTF-8, et n'a jamais rencontré ce cas.

    À appeler depuis un point d'entrée (`main()`), et **jamais à l'import** :
    reconfigurer `sys.stdout` au chargement de ce module en ferait un effet de
    bord global, subi par tout test qui l'importe — y compris ceux qui
    capturent la sortie console pour vérifier un message.
    """
    for flux in (sys.stdout, sys.stderr):
        if hasattr(flux, "reconfigure"):
            flux.reconfigure(encoding="utf-8", errors="replace")


def _afficher(message: str, niveau: int = _NORMAL) -> None:
    """Écrit sur la sortie standard si la verbosité configurée le permet."""
    if config.VERBOSITE >= niveau:
        print(message, flush=True)


def titre(texte: str) -> None:
    """Affiche un titre encadré, pour marquer le début d'une étape."""
    _afficher("")
    _afficher("=" * LARGEUR)
    _afficher(texte.upper())
    _afficher("=" * LARGEUR)


def section(texte: str) -> None:
    """Affiche un sous-titre, pour marquer le passage à un nouveau livre."""
    _afficher("")
    _afficher(texte)
    _afficher("-" * LARGEUR)


def info(texte: str) -> None:
    """Message d'information courant."""
    _afficher(texte)


def detail(texte: str) -> None:
    """Message n'apparaissant qu'en verbosité détaillée."""
    _afficher(f"      {texte}", niveau=_DETAILLE)


def succes(texte: str) -> None:
    """Confirmation d'une opération réussie."""
    _afficher(f"   [OK]      {texte}")


def saute(texte: str) -> None:
    """Signale une unité passée parce que déjà terminée."""
    _afficher(f"   [DEJA]    {texte}")


def alerte(texte: str) -> None:
    """Avertissement : l'exécution continue, mais un point mérite attention."""
    _afficher(f"   [ALERTE]  {texte}")


def echec(texte: str) -> None:
    """Échec d'une unité. L'exécution du livre se poursuit malgré tout."""
    _afficher(f"   [ECHEC]   {texte}")


def progression(courant: int, total: int, libelle: str) -> None:
    """
    Affiche l'avancement sous la forme « 12/37 (32 %) — libellé ».

    Le pourcentage est utile sur un livre : une étape d'OCR peut durer plus
    d'une heure, et savoir où l'on en est évite de croire à un blocage.
    """
    pourcentage = (100 * courant // total) if total else 100
    _afficher(f"   {courant}/{total} ({pourcentage} %) — {libelle}")


def recapitulatif(lignes: dict[str, Any]) -> None:
    """Affiche un tableau récapitulatif en fin d'étape."""
    _afficher("")
    _afficher("=" * LARGEUR)
    _afficher("RÉCAPITULATIF")
    _afficher("-" * LARGEUR)

    largeur_cle = max((len(c) for c in lignes), default=0)

    for cle, valeur in lignes.items():
        _afficher(f"   {cle.ljust(largeur_cle)}  {valeur}")

    _afficher("=" * LARGEUR)


# ============================================================
# 2. CHRONOMÈTRE
# ============================================================


class Chrono:
    """
    Mesure une durée écoulée, en gestionnaire de contexte.

    Utilise `time.monotonic()` et non `time.time()` : une horloge système
    ajustée en cours d'appel (ce qui arrive sur une machine virtuelle Colab)
    produirait sinon une durée négative ou absurde dans le journal.

    Exemple:
        with Chrono() as chrono:
            reponse = appeler_api(...)
        print(chrono.secondes)
    """

    def __init__(self) -> None:
        self._debut = 0.0
        self.secondes = 0.0

    def __enter__(self) -> Chrono:
        self._debut = time.monotonic()
        return self

    def __exit__(self, *_exception: object) -> None:
        self.secondes = round(time.monotonic() - self._debut, 3)


def horodatage() -> str:
    """Date et heure au format ISO, pour les sidecars et les journaux."""
    return datetime.now().isoformat(timespec="seconds")


def formater_nombre(valeur: int) -> str:
    """
    Met en forme un entier avec une espace comme séparateur de milliers.

    Passe par une chaîne intermédiaire plutôt que par un `.replace(",", " ")`
    appliqué à la phrase entière : ce raccourci mangeait aussi les virgules
    légitimes du texte environnant, et produisait « 263 caractères  4 pages ».
    """
    return f"{valeur:,}".replace(",", " ")


def formater_duree(secondes: float) -> str:
    """
    Met en forme une durée pour l'affichage (« 1 h 27 min », « 42 s »).

    Les durées de ce pipeline vont de quelques secondes à plusieurs heures :
    un affichage en secondes brutes serait illisible sur un livre entier.
    """
    secondes = int(secondes)

    if secondes < 60:
        return f"{secondes} s"

    if secondes < 3600:
        return f"{secondes // 60} min {secondes % 60} s"

    return f"{secondes // 3600} h {(secondes % 3600) // 60} min"


# ============================================================
# 3. DÉCOMPTE DES UNITÉS DE TRAVAIL
# ------------------------------------------------------------
# Placé ici, aux côtés de `recapitulatif()`, parce que les trois étapes IA
# partagent exactement ce décompte : le dupliquer dans `edition.py` et
# `validation.py` serait la duplication que le projet s'interdit.
# ============================================================

# Issue du traitement d'une unité (page, bloc, jonction).
UNITE_TERMINEE = "terminee"
UNITE_SAUTEE = "sautee"
UNITE_SUSPECTE = "suspecte"
UNITE_ECHOUEE = "echouee"


@dataclass
class Compteurs:
    """Décompte des unités d'une passe, et bilan de ce qui reste à reprendre."""

    total: int = 0
    traitees: int = 0
    sautees: int = 0
    suspectes: int = 0
    echouees: int = 0
    numeros_echoues: list[int] = field(default_factory=list)

    def enregistrer(self, statut: str, numero: int) -> None:
        """Incrémente le compteur correspondant au statut d'une unité."""
        if statut == UNITE_TERMINEE:
            self.traitees += 1
        elif statut == UNITE_SAUTEE:
            self.sautees += 1
        elif statut == UNITE_SUSPECTE:
            self.suspectes += 1
        else:
            self.echouees += 1
            self.numeros_echoues.append(numero)

    @property
    def complet(self) -> bool:
        """Vrai si aucune unité ne reste à reprendre."""
        return self.echouees == 0 and self.suspectes == 0

    def en_dict(self) -> dict[str, Any]:
        """Représentation destinée au journal."""
        return {
            "total": self.total,
            "traitees": self.traitees,
            "sautees": self.sautees,
            "suspectes": self.suspectes,
            "echouees": self.echouees,
            "numeros_echoues": self.numeros_echoues,
        }


def afficher_reprises(libelle: str, compteurs: Compteurs) -> None:
    """Affiche ce qui reste à reprendre pour une passe."""
    if compteurs.sautees:
        saute(f"{compteurs.sautees} {libelle}(s) déjà traité(s)")

    if compteurs.suspectes:
        alerte(
            f"{compteurs.suspectes} {libelle}(s) suspect(s), "
            "repris au prochain passage"
        )

    if compteurs.numeros_echoues:
        echec(f"{libelle}(s) en échec : {compteurs.numeros_echoues}")


# ============================================================
# 4. JOURNAL JSON
# ============================================================


@dataclass
class Journal:
    """
    Journal d'une étape, persistant et résistant aux interruptions.

    Le journal est rechargé au démarrage puis complété, de sorte qu'une reprise
    après coupure Colab conserve la trace des appels déjà effectués. Il est
    réécrit en entier à chaque sauvegarde : à l'échelle d'un livre (quelques
    centaines d'entrées) le coût est négligeable, et le fichier reste un JSON
    valide en permanence — ce qu'un format en ajout ne garantirait pas si
    l'écriture était interrompue au milieu d'une ligne.
    """

    etape: str
    chemin: Path
    configuration: dict[str, Any] = field(default_factory=dict)
    livres: dict[str, Any] = field(default_factory=dict)
    appels: list[dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------

    @classmethod
    def charger_ou_creer(
        cls,
        etape: str,
        dossier: Path,
        configuration: dict[str, Any] | None = None,
    ) -> Journal:
        """
        Charge le journal existant de l'étape, ou en crée un vide.

        Args:
            etape: identifiant de l'étape (« ocr », « edition »…).
            dossier: dossier de travail où réside le journal.
            configuration: paramètres de l'exécution courante, écrasant ceux
                de l'exécution précédente.
        """
        # Les journaux vivent dans le dossier de travail, non à la racine :
        # le dossier principal ne montre que les PDF et les DOCX.
        chemin = (
            io.assurer_dossier(dossier / config.DOSSIER_TEMPORAIRE)
            / config.NOM_JOURNAL.format(etape=etape)
        )
        existant = io.lire_sidecar(chemin) or {}

        return cls(
            etape=etape,
            chemin=chemin,
            configuration=configuration or existant.get("configuration", {}),
            livres=existant.get("livres", {}),
            appels=existant.get("appels", []),
        )

    # ------------------------------------------------------------
    # Alimentation
    # ------------------------------------------------------------

    def enregistrer_appel(self, **champs: Any) -> None:
        """
        Ajoute une entrée d'appel API au journal.

        Les champs attendus sont ceux du cahier des charges : `modele`,
        `response_id`, `duree_secondes`, `longueur_entree`, `longueur_sortie`,
        `avertissements`. La date est ajoutée automatiquement.

        Attention à `longueur_entree` : elle compte des caractères, sauf à
        l'étape 1 où l'entrée est une image — il s'agit alors de la taille du
        PNG en octets. Deux étapes, deux unités, même nom de champ : c'est
        assumé, la comparaison n'ayant de sens qu'au sein d'une même étape.
        """
        self.appels.append({"date": horodatage(), **champs})

        # Plafonnement : on conserve les entrées les plus récentes, qui sont
        # les seules utiles à un diagnostic.
        if len(self.appels) > config.MAX_ENTREES_JOURNAL:
            self.appels = self.appels[-config.MAX_ENTREES_JOURNAL :]

    def resumer_livre(self, nom_livre: str, **champs: Any) -> None:
        """Enregistre ou met à jour le bilan d'un livre."""
        bilan = self.livres.setdefault(nom_livre, {})
        bilan.update(champs)

    def avertissements_du_livre(self, nom_livre: str) -> list[str]:
        """Rassemble tous les avertissements journalisés pour un livre."""
        return [
            avertissement
            for appel in self.appels
            if appel.get("livre") == nom_livre
            for avertissement in appel.get("avertissements", [])
        ]

    # ------------------------------------------------------------
    # Persistance
    # ------------------------------------------------------------

    def sauvegarder(self) -> None:
        """Écrit le journal sur le disque, de façon atomique."""
        io.ecrire_sidecar(
            self.chemin,
            {
                "etape": self.etape,
                "derniere_execution": horodatage(),
                "configuration": self.configuration,
                "livres": self.livres,
                "appels": self.appels,
            },
        )
