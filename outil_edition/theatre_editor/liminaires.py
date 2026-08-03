"""
Étape 2 bis — Rôles des pages liminaires : `EDIT.txt` → `LIMINAIRES.json`.

Un livre s'ouvre sur des pages que les règles déterministes ne savent pas
départager : titre, auteur, éditeur, épigraphe et son attribution, note
d'édition, liste des rôles, prologue. Une citation en exergue et une didascalie
s'écrivent tous deux en italique ; un nom d'auteur sous une épigraphe et un nom
de personnage s'écrivent tous deux seuls sur leur ligne.

Cette étape confie **ce seul arbitrage** à un modèle, puis met le résultat en
cache.

Trois propriétés justifient ce découpage.

**Un appel par livre, pas un par bloc.** Les ambiguïtés de rôle vivent toutes
dans les premières pages : la passe ne soumet que les lignes précédant la
première division ou le premier personnage reconnu avec certitude. Classer tout
un livre de 300 pages pour trancher une dizaine de cas serait disproportionné.

**L'étape 4 reste gratuite et déterministe.** L'annotation est écrite une fois
sur le disque ; la génération du DOCX la relit. Vous pouvez donc régénérer le
document autant de fois que vous voulez après avoir changé une marge, sans
repayer et sans risque de variation.

**La dégradation est propre.** Si `LIMINAIRES.json` est absent, l'étape 4
fonctionne exactement comme avant : les liminaires retombent sur les règles
déterministes. Cette étape est un raffinement, jamais une dépendance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from theatre_editor import config
from theatre_editor.utils import api, blocks, io
from theatre_editor.utils import logging as journalisation

NOM_ETAPE = "liminaires"

# Une ligne de réponse : « 12|epigraphe ».
MOTIF_ANNOTATION = re.compile(r"^\s*(\d+)\s*\|\s*([a-z_]+)\s*$", re.MULTILINE)


# ============================================================
# 1. RÉSULTATS
# ============================================================


@dataclass
class ResultatLivre:
    """Bilan de l'annotation des liminaires d'un livre."""

    nom: str
    statut: str = config.STATUT_TERMINE
    lignes_soumises: int = 0
    roles_retenus: int = 0
    roles_refuses: list[str] = field(default_factory=list)
    saute: bool = False
    duree_secondes: float = 0.0
    erreur: str | None = None

    @property
    def complet(self) -> bool:
        return self.statut != config.STATUT_ECHEC

    def champs_journal(self) -> dict[str, Any]:
        return {
            "statut": self.statut,
            "lignes_soumises": self.lignes_soumises,
            "roles_retenus": self.roles_retenus,
            "roles_refuses": self.roles_refuses,
            "saute": self.saute,
            "duree_secondes": self.duree_secondes,
            "erreur": self.erreur,
        }


# ============================================================
# 2. ANALYSE DE LA RÉPONSE
# ============================================================


def interpreter_annotations(reponse: str) -> tuple[dict[int, str], list[str]]:
    """
    Traduit la réponse du modèle en rôles par numéro de ligne.

    Un rôle inconnu est **refusé** plutôt que propagé : la ligne retombe alors
    sur son classement déterministe. Accepter un rôle inventé ferait échouer la
    correspondance avec les styles, plusieurs étapes plus loin.

    Returns:
        `(rôles retenus, rôles refusés)`.
    """
    roles: dict[int, str] = {}
    refuses: list[str] = []

    for numero, role in MOTIF_ANNOTATION.findall(reponse):
        if role in config.ROLES_LIMINAIRES:
            roles[int(numero)] = role
        elif role not in refuses:
            refuses.append(role)

    return roles, refuses


def _message(lignes: list[str], fin: int) -> str:
    """
    Numérote les lignes liminaires à soumettre.

    Les lignes vides sont omises : elles n'ont pas de rôle, et les transmettre
    ne ferait qu'allonger la requête.
    """
    numerotees = [
        f"{numero}|{ligne.strip()}"
        for numero, ligne in enumerate(lignes[:fin])
        if ligne.strip()
    ]

    return (
        f"Voici les {len(numerotees)} premières lignes non vides de la pièce, "
        "numérotées.\n\n"
        "Attribue un rôle à chacune, selon les instructions.\n\n"
        + "\n".join(numerotees)
    )


# ============================================================
# 3. TRAITEMENT D'UN LIVRE
# ============================================================


def annoter_livre(
    chemins: io.CheminsLivre,
    journal: journalisation.Journal,
) -> ResultatLivre:
    """Annote les liminaires d'un livre, sauf si c'est déjà fait."""
    resultat = ResultatLivre(nom=chemins.nom)

    journalisation.section(f"Liminaires — {chemins.nom}")

    if io.lire_sidecar(chemins.liminaires) is not None:
        journalisation.saute("annotation déjà présente")
        resultat.saute = True
        return resultat

    with journalisation.Chrono() as chrono:
        try:
            _annoter(chemins=chemins, journal=journal, resultat=resultat)
        except Exception as erreur:
            # Cette étape est un raffinement : son échec ne doit pas empêcher
            # de produire le DOCX, qui retombera sur les règles déterministes.
            resultat.statut = config.STATUT_ECHEC
            resultat.erreur = str(erreur)
            journalisation.echec(f"{chemins.nom} : {erreur}")

    resultat.duree_secondes = chrono.secondes

    journal.resumer_livre(chemins.nom, **resultat.champs_journal())
    journal.sauvegarder()

    return resultat


def _annoter(
    *,
    chemins: io.CheminsLivre,
    journal: journalisation.Journal,
    resultat: ResultatLivre,
) -> None:
    """Corps de l'annotation d'un livre."""
    texte = io.lire_texte(chemins.edit)
    lignes = texte.split("\n")

    index = blocks.construire_index_structure(texte)
    fin = blocks.fin_des_liminaires(texte, index)

    if fin == 0:
        journalisation.info("   aucune page liminaire : la pièce commence aussitôt")
        io.ecrire_sidecar(chemins.liminaires, {"roles": {}, "lignes_soumises": 0})
        return

    resultat.lignes_soumises = fin
    journalisation.info(f"   {fin} ligne(s) liminaire(s) à qualifier")

    appel = api.appeler_modele(
        modele=config.MODEL_LIMINAIRES,
        instructions=io.charger_prompt("prompt_liminaires"),
        message=_message(lignes, fin),
        libelle=f"liminaires de {chemins.nom}",
    )

    roles, refuses = interpreter_annotations(appel.texte)

    resultat.roles_retenus = len(roles)
    resultat.roles_refuses = refuses

    if refuses:
        journalisation.alerte(f"rôles inconnus, ignorés : {', '.join(refuses)}")

    io.ecrire_sidecar(
        chemins.liminaires,
        {
            "roles": {str(numero): role for numero, role in roles.items()},
            "lignes_soumises": fin,
            "date_traitement": journalisation.horodatage(),
            "roles_refuses": refuses,
            **appel.champs_journal(),
        },
    )

    journal.enregistrer_appel(
        livre=chemins.nom,
        unite="liminaires",
        numero=1,
        longueur_entree=sum(len(ligne) for ligne in lignes[:fin]),
        roles_retenus=len(roles),
        avertissements=appel.avertissements,
        **appel.champs_journal(),
    )

    journalisation.succes(f"{len(roles)} rôle(s) attribué(s)")


def charger_roles(chemins: io.CheminsLivre) -> dict[int, blocks.TypeLigne]:
    """
    Relit l'annotation d'un livre, pour l'étape 4.

    Returns:
        Numéro de ligne → type. Vide si l'annotation est absente : l'étape 4
        retombe alors sur les règles déterministes, exactement comme avant.
    """
    sidecar = io.lire_sidecar(chemins.liminaires)

    if sidecar is None:
        return {}

    types: dict[int, blocks.TypeLigne] = {}

    for numero, role in (sidecar.get("roles") or {}).items():
        try:
            types[int(numero)] = blocks.TypeLigne(role)
        except (TypeError, ValueError):
            # Rôle devenu inconnu depuis l'annotation : on l'ignore plutôt que
            # d'échouer, la ligne retombant sur son classement déterministe.
            continue

    return types


# ============================================================
# 4. POINT D'ENTRÉE DE L'ÉTAPE
# ============================================================


def executer(dossier: Path | None = None) -> list[ResultatLivre]:
    """
    Annote les liminaires de tous les livres édités du dossier.

    Args:
        dossier: dossier à parcourir. `config.DOSSIER_DRIVE` par défaut.
    """
    base = dossier if dossier is not None else config.DOSSIER_DRIVE

    journalisation.titre("Étape 2 bis — Rôles des pages liminaires")

    livres = io.lister_livres_avec(config.NOM_EDIT, base)
    journalisation.info(f"Dossier : {base}")
    journalisation.info(f"Livres édités trouvés : {len(livres)}")

    if not livres:
        journalisation.alerte(
            f"aucun « {config.NOM_EDIT} » — lancez d'abord l'étape « edition »"
        )
        return []

    journal = journalisation.Journal.charger_ou_creer(
        NOM_ETAPE,
        base,
        {
            "modele": config.MODEL_LIMINAIRES,
            "lignes_liminaires": config.LIGNES_LIMINAIRES,
        },
    )

    resultats = [annoter_livre(chemins, journal) for chemins in livres]

    journalisation.recapitulatif(
        {
            "Livres annotés": sum(1 for r in resultats if not r.saute and r.complet),
            "Déjà annotés": sum(1 for r in resultats if r.saute),
            "Échecs": sum(1 for r in resultats if not r.complet),
            "Rôles attribués": sum(r.roles_retenus for r in resultats),
            "Durée": journalisation.formater_duree(
                sum(r.duree_secondes for r in resultats)
            ),
            "Journal": journal.chemin.name,
        }
    )

    return resultats
