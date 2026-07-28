"""
Étape 3 — Contrôle qualité : `OCR.txt` + `EDIT.txt` → `REPORT.txt`.

Compare la transcription brute à l'édition qui en est issue, pour détecter ce
que l'édition aurait perdu. **Le texte n'est jamais modifié** : cette étape ne
se trouve pas sur le chemin critique entre `EDIT.txt` et le DOCX, elle produit
un diagnostic destiné à un lecteur humain.

C'est un choix de conception, non une limitation. Une boucle de correction
automatique serait la porte ouverte à la violation du principe de fidélité :
un modèle chargé de « réparer » se croirait autorisé à réécrire.

Deux familles de contrôles, réunies dans un même rapport.

**Mécaniques, sans IA.** Volume conservé, lignes non vides, noms en capitales
présents de part et d'autre, convention typographique intacte. Gratuits,
instantanés, déterministes — et surtout sans faux négatif sur ce qu'ils savent
mesurer. Ils rendent le rapport utile là même où le modèle passerait à côté.

**Sémantiques, avec IA, bloc par bloc.** Pour ce qu'aucune règle ne peut voir :
une didascalie perdue, une réplique abrégée, un raccord mal ressoudé. Le
découpage en blocs n'est pas un choix mais une nécessité : un livre entier ne
tient pas dans une fenêtre de contexte, et un rapport sur un livre entier
dépasserait `MAX_OUTPUT_TOKENS`.

Le rapport ne détaille que les blocs porteurs de constats. Énumérer trente-sept
sections « rien à signaler » noierait les deux qui comptent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from theatre_editor import config
from theatre_editor.utils import api, blocks, io
from theatre_editor.utils import logging as journalisation

NOM_ETAPE = "validation"

UNITE_TERMINEE = journalisation.UNITE_TERMINEE
UNITE_SAUTEE = journalisation.UNITE_SAUTEE
UNITE_SUSPECTE = journalisation.UNITE_SUSPECTE
UNITE_ECHOUEE = journalisation.UNITE_ECHOUEE
Compteurs = journalisation.Compteurs

# Largeur des filets du rapport, alignée sur celle de la console.
LARGEUR = journalisation.LARGEUR

# Repère une ligne de constat, pour compter les problèmes signalés.
MOTIF_CONSTAT = re.compile(r"^\[([A-Z ]+)\]", re.MULTILINE)


# ============================================================
# 1. RÉSULTATS
# ============================================================


@dataclass
class ResultatLivre:
    """Bilan de la validation d'un livre."""

    nom: str
    statut: str = config.STATUT_TERMINE
    blocs: Compteurs = field(default_factory=Compteurs)
    constats_mecaniques: list[str] = field(default_factory=list)
    constats_modele: int = 0
    blocs_sains: int = 0
    duree_secondes: float = 0.0
    erreur: str | None = None

    @property
    def complet(self) -> bool:
        return self.blocs.complet

    @property
    def total_constats(self) -> int:
        """Nombre total de problèmes signalés, toutes familles confondues."""
        return len(self.constats_mecaniques) + self.constats_modele

    def champs_journal(self) -> dict[str, Any]:
        return {
            "statut": self.statut,
            "blocs": self.blocs.en_dict(),
            "constats_mecaniques": len(self.constats_mecaniques),
            "constats_modele": self.constats_modele,
            "blocs_sains": self.blocs_sains,
            "duree_secondes": self.duree_secondes,
            "erreur": self.erreur,
        }


# ============================================================
# 2. ALIGNEMENT DES BLOCS
# ============================================================


def compter_blocs_raccordes(chemins: io.CheminsLivre) -> int:
    """Compte les blocs présents dans `_EDIT_raccords/`."""
    if not chemins.dossier_raccords.is_dir():
        return 0

    return len(list(chemins.dossier_raccords.glob("bloc_*.txt")))


def verifier_alignement(liste_blocs: list[blocks.Bloc], chemins: io.CheminsLivre) -> None:
    """
    Vérifie que le découpage recalculé correspond aux blocs édités.

    Contrôle indispensable. Le découpage est déterministe *à `PAGES_PAR_BLOC`
    constant* : si cette valeur a changé depuis l'étape 2, le bloc 12 recalculé
    ne recouvre plus les mêmes pages que le `bloc_0012.txt` sur le disque. La
    comparaison porterait alors sur des passages différents et produirait un
    rapport entièrement faux — le pire résultat possible, car il aurait l'air
    plausible.

    Raises:
        ValueError: avec la marche à suivre.
    """
    attendus = len(liste_blocs)
    presents = compter_blocs_raccordes(chemins)

    if presents == 0:
        raise ValueError(
            f"aucun bloc raccordé dans {chemins.dossier_raccords.name} — "
            "lancez d'abord l'étape « edition »."
        )

    if presents != attendus:
        raise ValueError(
            f"découpage incohérent : {attendus} bloc(s) recalculé(s) contre "
            f"{presents} sur le disque.\n"
            f"    PAGES_PAR_BLOC vaut {config.PAGES_PAR_BLOC} et a "
            "probablement changé depuis l'édition.\n"
            "    Rétablissez l'ancienne valeur, ou supprimez "
            f"{chemins.dossier_blocs.name} et {chemins.dossier_raccords.name} "
            "pour refaire l'édition."
        )


def texte_ocr_du_bloc(pages: list[str], bloc: blocks.Bloc) -> str:
    """
    Reconstitue la portion d'OCR correspondant à un bloc.

    Les pages sont réassemblées à l'identique de l'étape 2, si bien que le
    modèle compare bien deux versions du même passage.
    """
    return config.SEPARATEUR_PAGE.join(
        pages[bloc.page_debut - 1 : bloc.page_fin]
    )


# ============================================================
# 3. VALIDATION D'UN BLOC
# ============================================================


def _message_bloc(bloc: blocks.Bloc, nombre_blocs: int, ocr: str, edit: str) -> str:
    """Construit le message utilisateur d'une comparaison."""
    return (
        f"Tu vérifies le bloc {bloc.numero} sur {nombre_blocs}, correspondant "
        f"aux pages {bloc.page_debut} à {bloc.page_fin}.\n\n"
        "Voici d'abord la transcription OCR brute, puis la version éditée qui "
        "en est issue.\n\n"
        f"{config.DELIM_SOURCE_DEBUT}\n{ocr}\n{config.DELIM_SOURCE_FIN}\n\n"
        f"{config.DELIM_EDIT_DEBUT}\n{edit}\n{config.DELIM_EDIT_FIN}"
    )


def compter_constats(rapport: str) -> int:
    """Compte les lignes de constat d'un rapport de bloc."""
    if est_sain(rapport):
        return 0

    return len(MOTIF_CONSTAT.findall(rapport))


def est_sain(rapport: str) -> bool:
    """
    Vrai si le modèle n'a rien trouvé à signaler.

    S'appuie sur la mention exacte imposée par le prompt. Sans elle, un rapport
    vide serait indiscernable d'un bloc non vérifié.
    """
    return config.MENTION_AUCUN_PROBLEME in rapport.upper()


def valider_bloc(
    *,
    bloc: blocks.Bloc,
    nombre_blocs: int,
    ocr_du_bloc: str,
    chemins: io.CheminsLivre,
    journal: journalisation.Journal,
    nom_livre: str,
) -> str:
    """
    Compare un bloc édité à sa transcription, sauf s'il est déjà validé.

    Returns:
        L'un des statuts `UNITE_*`.
    """
    libelle = f"bloc {bloc.numero}"

    if io.unite_terminee(chemins.report_bloc_json(bloc.numero)):
        return UNITE_SAUTEE

    edit_du_bloc = io.lire_texte_si_present(chemins.raccord_txt(bloc.numero))

    if edit_du_bloc is None or not edit_du_bloc.strip():
        journalisation.alerte(f"{libelle} : bloc édité manquant, vérification reportée")
        return UNITE_ECHOUEE

    try:
        resultat = api.appeler_modele(
            modele=config.MODEL_VALIDATION,
            instructions=io.charger_prompt("prompt_validation"),
            message=_message_bloc(bloc, nombre_blocs, ocr_du_bloc, edit_du_bloc),
            libelle=libelle,
        )
    except api.EchecAppelAPI as erreur:
        _enregistrer_echec(
            chemins=chemins,
            bloc=bloc,
            erreur=str(erreur),
            journal=journal,
            nom_livre=nom_livre,
        )
        journalisation.echec(f"{libelle} : {erreur}")
        return UNITE_ECHOUEE

    rapport = blocks.nettoyer_enveloppe(resultat.texte)
    nombre_constats = compter_constats(rapport)

    # Contenu d'abord, sidecar ensuite.
    io.ecrire_texte_atomique(chemins.report_bloc_txt(bloc.numero), rapport)
    io.ecrire_sidecar(
        chemins.report_bloc_json(bloc.numero),
        {
            "statut": config.STATUT_TERMINE,
            "unite": "validation",
            "numero": bloc.numero,
            "page_debut": bloc.page_debut,
            "page_fin": bloc.page_fin,
            "date_traitement": journalisation.horodatage(),
            "longueur_entree": len(ocr_du_bloc) + len(edit_du_bloc),
            "sain": est_sain(rapport),
            "nombre_constats": nombre_constats,
            "avertissements": resultat.avertissements,
            **resultat.champs_journal(),
        },
    )

    journal.enregistrer_appel(
        livre=nom_livre,
        unite="validation",
        numero=bloc.numero,
        longueur_entree=len(ocr_du_bloc) + len(edit_du_bloc),
        nombre_constats=nombre_constats,
        avertissements=resultat.avertissements,
        **resultat.champs_journal(),
    )

    # Un bloc porteur de constats n'est pas une unité « suspecte » : la
    # vérification a parfaitement réussi, c'est le texte qui pose problème.
    # Le confondre ferait refaire la vérification à chaque exécution.
    return UNITE_TERMINEE


def _enregistrer_echec(
    *,
    chemins: io.CheminsLivre,
    bloc: blocks.Bloc,
    erreur: str,
    journal: journalisation.Journal,
    nom_livre: str,
) -> None:
    """Consigne l'échec de la vérification d'un bloc."""
    io.ecrire_sidecar(
        chemins.report_bloc_json(bloc.numero),
        {
            "statut": config.STATUT_ECHEC,
            "unite": "validation",
            "numero": bloc.numero,
            "page_debut": bloc.page_debut,
            "page_fin": bloc.page_fin,
            "modele": config.MODEL_VALIDATION,
            "date_traitement": journalisation.horodatage(),
            "erreur": erreur,
            "avertissements": ["échec définitif de l'appel"],
        },
    )

    journal.enregistrer_appel(
        livre=nom_livre,
        unite="validation",
        numero=bloc.numero,
        modele=config.MODEL_VALIDATION,
        erreur=erreur,
        avertissements=["échec définitif de l'appel"],
    )


# ============================================================
# 4. COMPOSITION DU RAPPORT
# ============================================================


def _filet(caractere: str = "-") -> str:
    return caractere * LARGEUR


def _entete(nom_livre: str, ocr: str, edit: str, nombre_blocs: int) -> list[str]:
    """Composeurs de l'en-tête du rapport."""
    pages = len(blocks.decouper_en_pages(ocr))

    return [
        _filet("="),
        f"RAPPORT DE CONTRÔLE QUALITÉ — {nom_livre}",
        f"Généré le {journalisation.horodatage()}",
        f"OCR  : {journalisation.formater_nombre(len(ocr))} caractères, "
        f"{pages} pages",
        f"EDIT : {journalisation.formater_nombre(len(edit))} caractères, "
        f"{nombre_blocs} blocs",
        _filet("="),
        "",
    ]


def _section_mecanique(constats: list[str]) -> list[str]:
    """Compose la section des contrôles déterministes."""
    lignes = [
        _filet(),
        "CONTRÔLES AUTOMATIQUES (mécaniques, sans IA)",
        _filet(),
    ]

    if not constats:
        lignes.append("[OK]      aucun écart mécanique détecté")
    else:
        lignes.extend(f"[ALERTE]  {constat}" for constat in constats)

    lignes.append("")

    return lignes


def _section_structure(edit: str) -> list[str]:
    """
    Compose la section de structure détectée.

    Figure dans ce rapport bien qu'elle concerne l'étape 4 : elle permet de
    repérer un problème de classification **avant** de générer le DOCX, au
    moment où l'on relit déjà le rapport. Un acte pris pour un personnage se
    verrait autrement à la première page blanche parasite.
    """
    index = blocks.construire_index_structure(edit)

    lignes = [
        _filet(),
        "STRUCTURE DÉTECTÉE",
        _filet(),
        f"Actes : {index.compter(blocks.TypeLigne.TITRE_ACTE)}     "
        f"Scènes : {index.compter(blocks.TypeLigne.TITRE_SCENE)}     "
        f"Personnages : {index.compter(blocks.TypeLigne.PERSONNAGE)}",
    ]

    for avertissement in index.avertissements:
        lignes.append(f"[ATTENTION]  {avertissement}")

    lignes.append("")

    return lignes


def _sections_blocs(
    liste_blocs: list[blocks.Bloc],
    chemins: io.CheminsLivre,
) -> tuple[list[str], int, int]:
    """
    Compose une section par bloc porteur de constats.

    Returns:
        `(lignes, nombre de constats, nombre de blocs sains)`.
    """
    lignes: list[str] = []
    constats = 0
    sains = 0

    for bloc in liste_blocs:
        rapport = io.lire_texte_si_present(chemins.report_bloc_txt(bloc.numero))

        if rapport is None:
            lignes.extend(
                [
                    _filet(),
                    f"BLOC {bloc.numero} — pages {bloc.page_debut} à {bloc.page_fin}",
                    _filet(),
                    "[NON VÉRIFIÉ] relancez l'étape de validation",
                    "",
                ]
            )
            continue

        if est_sain(rapport):
            sains += 1
            continue

        constats += compter_constats(rapport)

        lignes.extend(
            [
                _filet(),
                f"BLOC {bloc.numero} — pages {bloc.page_debut} à {bloc.page_fin}",
                _filet(),
                rapport.strip(),
                "",
            ]
        )

    return lignes, constats, sains


def composer_rapport(
    *,
    nom_livre: str,
    ocr: str,
    edit: str,
    liste_blocs: list[blocks.Bloc],
    chemins: io.CheminsLivre,
    constats_mecaniques: list[str],
) -> tuple[str, int, int]:
    """
    Assemble le rapport complet.

    Returns:
        `(rapport, nombre de constats du modèle, nombre de blocs sains)`.
    """
    sections_blocs, constats, sains = _sections_blocs(liste_blocs, chemins)

    lignes = [
        *_entete(nom_livre, ocr, edit, len(liste_blocs)),
        *_section_mecanique(constats_mecaniques),
        *_section_structure(edit),
    ]

    if sections_blocs:
        lignes.extend(sections_blocs)
    else:
        lignes.extend(
            [
                _filet(),
                "COMPARAISON BLOC PAR BLOC",
                _filet(),
                "[OK]      aucun constat sur les "
                f"{len(liste_blocs)} bloc(s) vérifié(s)",
                "",
            ]
        )

    lignes.extend(
        [
            _filet("="),
            f"{constats} constat(s) du modèle — "
            f"{sains}/{len(liste_blocs)} bloc(s) sans remarque",
            _filet("="),
        ]
    )

    return "\n".join(lignes) + "\n", constats, sains


# ============================================================
# 5. TRAITEMENT D'UN LIVRE
# ============================================================


def traiter_livre(
    chemins: io.CheminsLivre,
    journal: journalisation.Journal,
) -> ResultatLivre:
    """Valide un livre : contrôles mécaniques, comparaison par bloc, rapport."""
    nom_livre = chemins.nom
    resultat = ResultatLivre(nom=nom_livre)

    journalisation.section(f"Validation — {nom_livre}")

    with journalisation.Chrono() as chrono:
        try:
            _valider(
                chemins=chemins,
                journal=journal,
                resultat=resultat,
            )
        except Exception as erreur:
            resultat.statut = config.STATUT_ECHEC
            resultat.erreur = str(erreur)
            journalisation.echec(f"{nom_livre} : {erreur}")

    resultat.duree_secondes = chrono.secondes

    if resultat.statut != config.STATUT_ECHEC:
        resultat.statut = (
            config.STATUT_TERMINE if resultat.complet else config.STATUT_SUSPECT
        )
        journalisation.afficher_reprises("bloc", resultat.blocs)

    journal.resumer_livre(nom_livre, **resultat.champs_journal())
    journal.sauvegarder()

    return resultat


def _valider(
    *,
    chemins: io.CheminsLivre,
    journal: journalisation.Journal,
    resultat: ResultatLivre,
) -> None:
    """Corps de la validation d'un livre."""
    io.verifier_entree_etape(chemins.edit, "validation", "edition")

    ocr = io.lire_texte(chemins.ocr)
    edit = io.lire_texte(chemins.edit)

    pages = blocks.decouper_en_pages(ocr)

    if not pages:
        raise ValueError(f"aucune page exploitable dans {chemins.ocr.name}")

    liste_blocs = blocks.former_blocs(pages, config.PAGES_PAR_BLOC)
    verifier_alignement(liste_blocs, chemins)

    # Contrôles mécaniques : instantanés, on les fait d'abord et ils sont
    # toujours refaits — ils ne coûtent rien et reflètent l'état courant.
    resultat.constats_mecaniques = blocks.controles_mecaniques(ocr, edit)

    for constat in resultat.constats_mecaniques:
        journalisation.alerte(constat)

    _comparer_blocs(
        liste_blocs=liste_blocs,
        pages=pages,
        chemins=chemins,
        journal=journal,
        resultat=resultat,
    )

    rapport, constats, sains = composer_rapport(
        nom_livre=resultat.nom,
        ocr=ocr,
        edit=edit,
        liste_blocs=liste_blocs,
        chemins=chemins,
        constats_mecaniques=resultat.constats_mecaniques,
    )

    resultat.constats_modele = constats
    resultat.blocs_sains = sains

    io.ecrire_texte_atomique(chemins.report, rapport)

    journalisation.succes(
        f"{chemins.report.name} — {resultat.total_constats} constat(s), "
        f"{sains}/{len(liste_blocs)} bloc(s) sans remarque"
    )


def _comparer_blocs(
    *,
    liste_blocs: list[blocks.Bloc],
    pages: list[str],
    chemins: io.CheminsLivre,
    journal: journalisation.Journal,
    resultat: ResultatLivre,
) -> None:
    """Compare chaque bloc, en sautant ceux déjà vérifiés."""
    io.assurer_dossier(chemins.dossier_report)

    nombre = len(liste_blocs)
    resultat.blocs.total = nombre

    journalisation.info(f"   comparaison de {nombre} bloc(s)")

    for bloc in liste_blocs:
        statut = valider_bloc(
            bloc=bloc,
            nombre_blocs=nombre,
            ocr_du_bloc=texte_ocr_du_bloc(pages, bloc),
            chemins=chemins,
            journal=journal,
            nom_livre=resultat.nom,
        )

        resultat.blocs.enregistrer(statut, bloc.numero)

        if statut != UNITE_SAUTEE:
            journal.sauvegarder()
            api.patienter()

        journalisation.progression(bloc.numero, nombre, "blocs")


# ============================================================
# 6. POINT D'ENTRÉE DE L'ÉTAPE
# ============================================================


def executer(dossier: Path | None = None) -> list[ResultatLivre]:
    """
    Lance le contrôle qualité sur tous les livres édités du dossier.

    Args:
        dossier: dossier à parcourir. `config.DOSSIER_DRIVE` par défaut.

    Returns:
        Un bilan par livre traité.
    """
    base = dossier if dossier is not None else config.DOSSIER_DRIVE

    journalisation.titre("Étape 3 — Contrôle qualité")

    livres = io.lister_livres_avec(config.NOM_OCR, base)
    journalisation.info(f"Dossier : {base}")
    journalisation.info(f"Livres transcrits trouvés : {len(livres)}")

    if not livres:
        journalisation.alerte(
            f"aucun « {config.NOM_OCR} » dans {config.DOSSIER_TEMPORAIRE}/ — "
            "lancez d'abord l'étape OCR"
        )
        return []

    journal = journalisation.Journal.charger_ou_creer(
        NOM_ETAPE,
        base,
        {
            "modele": config.MODEL_VALIDATION,
            "pages_par_bloc": config.PAGES_PAR_BLOC,
            "ratio_minimal_longueur": config.RATIO_MINIMAL_LONGUEUR,
            "max_output_tokens": config.MAX_OUTPUT_TOKENS,
        },
    )

    resultats = [traiter_livre(chemins, journal) for chemins in livres]

    _afficher_recapitulatif(resultats, journal)

    return resultats


def _afficher_recapitulatif(
    resultats: list[ResultatLivre],
    journal: journalisation.Journal,
) -> None:
    """Affiche le bilan global de l'étape."""
    journalisation.recapitulatif(
        {
            "Livres validés": len(resultats),
            "Blocs comparés": sum(r.blocs.traitees for r in resultats),
            "Blocs déjà faits": sum(r.blocs.sautees for r in resultats),
            "Blocs en échec": sum(r.blocs.echouees for r in resultats),
            "Constats mécaniques": sum(
                len(r.constats_mecaniques) for r in resultats
            ),
            "Constats du modèle": sum(r.constats_modele for r in resultats),
            "Durée": journalisation.formater_duree(
                sum(r.duree_secondes for r in resultats)
            ),
            "Journal": journal.chemin.name,
        }
    )

    signales = [r.nom for r in resultats if r.total_constats]

    if signales:
        journalisation.info("")
        journalisation.alerte(
            f"rapports à relire : {', '.join(signales)}"
        )
