"""
Orchestration du pipeline : point d'entrée unique, en ligne de commande.

    python -m theatre_editor.main --etape ocr
    python -m theatre_editor.main --etape tout
    python -m theatre_editor.main --etape docx --dossier "/chemin/vers/dossier"
    python -m theatre_editor.main --verifier-modeles

Ce module ne contient **aucune logique métier** : il choisit l'étape, la lance,
agrège les bilans et rend un code de sortie. Chaque étape reste par ailleurs
directement appelable depuis un notebook (`ocr.executer(...)`), ce qui est
l'usage prévu dans Colab.

Les imports des étapes sont **différés** dans `_charger_etape()`. C'est
volontaire : lancer l'étape DOCX ne doit pas exiger `openai` ni `pymupdf`, et
inversement. Sur une installation partielle, on obtient une erreur portant sur
la dépendance réellement manquante, au lieu d'un échec à l'import du module.

Le code de sortie suit la convention Unix : `0` si tout est terminé, `1` s'il
reste quelque chose à reprendre ou qu'une étape a échoué. Un enchaînement de
commandes dans un shell peut ainsi s'arrêter au premier problème.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

from theatre_editor import ETAPES, __version__, config
from theatre_editor.utils import logging as journalisation

# Choix admis pour `--etape`, dans l'ordre du pipeline.
CHOIX_ETAPES = (*ETAPES, "tout")

CODE_SUCCES = 0
CODE_REPRISE_NECESSAIRE = 1


# ============================================================
# 1. CHARGEMENT DIFFÉRÉ DES ÉTAPES
# ============================================================


def _charger_etape(nom: str) -> Callable[[Path | None], list[Any]]:
    """
    Retourne la fonction `executer` d'une étape, importée à la demande.

    Import différé : l'étape DOCX ne dépend ni d'`openai` ni de `pymupdf`, et
    doit rester utilisable sans eux. Importer les quatre étapes en tête de
    module ferait échouer la commande entière sur une dépendance dont on n'a
    pas besoin.
    """
    if nom == "ocr":
        from theatre_editor import ocr

        return ocr.executer

    if nom == "edition":
        from theatre_editor import edition

        return edition.executer

    if nom == "liminaires":
        from theatre_editor import liminaires

        return liminaires.executer

    if nom == "validation":
        from theatre_editor import validation

        return validation.executer

    if nom == "docx":
        from theatre_editor import docx_export

        return docx_export.executer

    raise ValueError(f"étape inconnue : « {nom} ». Choix : {', '.join(ETAPES)}.")


# ============================================================
# 2. EXÉCUTION
# ============================================================


def _etape_reussie(resultats: Sequence[Any]) -> bool:
    """
    Détermine si une étape est pleinement terminée.

    Une étape sans résultat — aucun fichier d'entrée trouvé — n'est pas une
    réussite : c'est le signe que l'étape précédente n'a pas été lancée.
    """
    if not resultats:
        return False

    return all(
        resultat.statut == config.STATUT_TERMINE
        and getattr(resultat, "complet", True)
        for resultat in resultats
    )


def executer_etape(nom: str, dossier: Path | None = None) -> list[Any]:
    """Lance une étape et retourne ses bilans."""
    return _charger_etape(nom)(dossier)


def executer_pipeline(
    etapes: Sequence[str],
    dossier: Path | None = None,
    arreter_au_premier_echec: bool = True,
) -> dict[str, list[Any]]:
    """
    Enchaîne plusieurs étapes.

    Args:
        etapes: noms des étapes, dans l'ordre.
        dossier: dossier de travail.
        arreter_au_premier_echec: par défaut, on s'arrête dès qu'une étape
            n'est pas pleinement terminée. Poursuivre n'aurait pas de sens :
            l'étape suivante travaillerait sur des données incomplètes et
            produirait un résultat trompeur.

    Returns:
        Les bilans, par étape lancée.
    """
    bilans: dict[str, list[Any]] = {}

    for nom in etapes:
        bilans[nom] = executer_etape(nom, dossier)

        if arreter_au_premier_echec and not _etape_reussie(bilans[nom]):
            journalisation.info("")
            journalisation.alerte(
                f"étape « {nom} » incomplète — enchaînement interrompu.\n"
                "          Corrigez ce qui est signalé ci-dessus, puis relancez : "
                "les unités déjà traitées ne seront pas refaites."
            )
            break

    return bilans


# ============================================================
# 3. RÉCAPITULATIF GLOBAL
# ============================================================


def afficher_bilan_global(bilans: dict[str, list[Any]]) -> None:
    """Affiche l'état de chaque étape lancée."""
    if len(bilans) < 2:
        return

    journalisation.titre("Bilan du pipeline")

    for nom in ETAPES:
        if nom not in bilans:
            journalisation.info(f"   {nom:<12} non lancée")
            continue

        resultats = bilans[nom]

        if not resultats:
            journalisation.alerte(f"{nom:<12} aucun fichier d'entrée")
        elif _etape_reussie(resultats):
            journalisation.succes(f"{nom:<12} {len(resultats)} livre(s)")
        else:
            journalisation.echec(f"{nom:<12} à reprendre")


# ============================================================
# 4. INTERFACE EN LIGNE DE COMMANDE
# ============================================================


def construire_analyseur() -> argparse.ArgumentParser:
    """Construit l'analyseur d'arguments."""
    analyseur = argparse.ArgumentParser(
        prog="python -m theatre_editor.main",
        description=(
            "Pipeline d'édition de pièces de théâtre : "
            "scans PDF → DOCX. Chaque étape est indépendante et reprenable."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemples :\n"
            "  --etape ocr                     transcrit les PDF du dossier\n"
            "  --etape tout                    enchaîne les quatre étapes\n"
            "  --etape docx --dossier ./essai  regénère les DOCX d'un dossier\n"
            "  --verifier-modeles              contrôle les identifiants de "
            "config.py\n\n"
            "Relancer une étape ne refait jamais le travail déjà validé."
        ),
    )

    analyseur.add_argument(
        "--etape",
        choices=CHOIX_ETAPES,
        default="tout",
        help="étape à lancer, ou « tout » pour les enchaîner (défaut : tout)",
    )

    analyseur.add_argument(
        "--dossier",
        type=Path,
        default=None,
        help=f"dossier de travail (défaut : {config.DOSSIER_DRIVE})",
    )

    analyseur.add_argument(
        "--continuer-malgre-echec",
        action="store_true",
        help=(
            "poursuit l'enchaînement même si une étape est incomplète. "
            "À éviter : l'étape suivante travaillerait sur des données "
            "partielles"
        ),
    )

    analyseur.add_argument(
        "--verifier-modeles",
        action="store_true",
        help="vérifie que les modèles de config.py existent, puis quitte",
    )

    analyseur.add_argument(
        "--silencieux",
        action="store_true",
        help="n'affiche que les erreurs",
    )

    analyseur.add_argument(
        "--detaille",
        action="store_true",
        help="affiche le détail de chaque unité traitée",
    )

    analyseur.add_argument(
        "--version",
        action="version",
        version=f"theatre_editor {__version__}",
    )

    return analyseur


def _appliquer_verbosite(arguments: argparse.Namespace) -> None:
    """Traduit les options d'affichage en niveau de verbosité."""
    if arguments.silencieux:
        config.VERBOSITE = 0
    elif arguments.detaille:
        config.VERBOSITE = 2


def _verifier_modeles() -> int:
    """Contrôle les identifiants de modèles et retourne un code de sortie."""
    from theatre_editor.utils import api

    journalisation.titre("Vérification des modèles configurés")

    resultats = api.verifier_modeles_configures()

    return CODE_SUCCES if all(resultats.values()) else CODE_REPRISE_NECESSAIRE


def main(argv: Sequence[str] | None = None) -> int:
    """
    Point d'entrée en ligne de commande.

    Returns:
        `0` si tout est terminé, `1` s'il reste quelque chose à reprendre.
    """
    arguments = construire_analyseur().parse_args(argv)

    _appliquer_verbosite(arguments)

    try:
        if arguments.verifier_modeles:
            return _verifier_modeles()

        etapes = ETAPES if arguments.etape == "tout" else (arguments.etape,)

        bilans = executer_pipeline(
            etapes,
            dossier=arguments.dossier,
            arreter_au_premier_echec=not arguments.continuer_malgre_echec,
        )

        afficher_bilan_global(bilans)

        toutes_reussies = len(bilans) == len(etapes) and all(
            _etape_reussie(resultats) for resultats in bilans.values()
        )

        return CODE_SUCCES if toutes_reussies else CODE_REPRISE_NECESSAIRE

    except KeyboardInterrupt:
        # Interruption volontaire : ce n'est pas une erreur. Le travail déjà
        # écrit est conservé, et la reprise repartira de là.
        journalisation.info("")
        journalisation.alerte("interrompu — le travail déjà effectué est conservé")
        return CODE_REPRISE_NECESSAIRE

    except (FileNotFoundError, NotADirectoryError, RuntimeError, ValueError) as erreur:
        # Erreurs attendues, dont le message est déjà rédigé pour l'utilisateur.
        journalisation.info("")
        journalisation.echec(str(erreur))
        return CODE_REPRISE_NECESSAIRE


if __name__ == "__main__":
    sys.exit(main())
