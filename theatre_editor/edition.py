"""
Étape 2 — Édition OCR : `<Livre>_OCR.txt` → `<Livre>_EDIT.txt`.

L'étape se déroule en deux passes distinctes, chacune reprenable.

**2a — édition par blocs.** `OCR.txt` est découpé en blocs de
`PAGES_PAR_BLOC` pages, et chaque bloc est confié au modèle d'édition, qui
corrige les erreurs de reconnaissance sans jamais réécrire l'auteur. Les blocs
vont dans `_EDIT_blocs/`.

**2b — passe de raccord.** Les blocs sont copiés dans `_EDIT_raccords/`, puis
chaque jonction est examinée : 50 dernières lignes du bloc gauche, 50 premières
du bloc droit. Le modèle ne peut que ressouder. `EDIT.txt` est assemblé
**exclusivement** depuis `_EDIT_raccords/`.

Deux propriétés à garder en tête.

**L'ordre croissant des jonctions est significatif.** Le bloc droit corrigé à la
jonction N devient le bloc gauche de la jonction N+1. Les corrections se
propagent donc, et les fichiers de `_EDIT_raccords/` sont mis à jour en place,
jonction par jonction.

**Cette mutation en place est dangereuse, donc encadrée.** Une réponse aberrante
du modèle — qui résumerait, réécrirait, ou ne rendrait qu'une partie de
l'extrait — détruirait du texte sans retour possible. Deux protections :
`blocks.extraire_blocs_raccord()` refuse une réponse mal formée, et
`blocks.verifier_raccord()` refuse une correction dont la longueur a dérivé. Dans
les deux cas, l'extrait d'origine est conservé : mieux vaut une jonction non
corrigée qu'une jonction corrompue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from theatre_editor import config
from theatre_editor.utils import api, blocks, io
from theatre_editor.utils import logging as journalisation

NOM_ETAPE = "edition"

# Les statuts d'unité et le décompte sont partagés avec les autres étapes IA.
UNITE_TERMINEE = journalisation.UNITE_TERMINEE
UNITE_SAUTEE = journalisation.UNITE_SAUTEE
UNITE_SUSPECTE = journalisation.UNITE_SUSPECTE
UNITE_ECHOUEE = journalisation.UNITE_ECHOUEE
Compteurs = journalisation.Compteurs


# ============================================================
# 1. RÉSULTATS
# ============================================================


@dataclass
class ResultatLivre:
    """Bilan du traitement d'un fichier OCR."""

    nom: str
    statut: str = config.STATUT_TERMINE
    blocs: Compteurs = field(default_factory=Compteurs)
    raccords: Compteurs = field(default_factory=Compteurs)
    duree_secondes: float = 0.0
    erreur: str | None = None

    @property
    def complet(self) -> bool:
        return self.blocs.complet and self.raccords.complet

    def champs_journal(self) -> dict[str, Any]:
        return {
            "statut": self.statut,
            "blocs": self.blocs.en_dict(),
            "raccords": self.raccords.en_dict(),
            "duree_secondes": self.duree_secondes,
            "erreur": self.erreur,
        }


# ============================================================
# 2. PASSE 2a — ÉDITION D'UN BLOC
# ============================================================


def _message_bloc(bloc: blocks.Bloc, nombre_blocs: int) -> str:
    """
    Construit le message utilisateur accompagnant un bloc.

    Le modèle est averti que le bloc est une découpe arbitraire : sans cet
    avertissement, il aurait tendance à « terminer » une phrase coupée ou à
    fabriquer une transition, ce qui violerait la fidélité au texte.
    """
    return (
        f"Tu traites le bloc {bloc.numero} sur {nombre_blocs}.\n\n"
        f"Ce bloc provient approximativement des pages de fichier "
        f"{bloc.page_debut} à {bloc.page_fin}.\n\n"
        "Applique strictement les instructions d'édition OCR au texte situé "
        "entre les délimiteurs.\n\n"
        "Le début ou la fin du bloc peut appartenir à une phrase ou à une "
        "scène commencée dans un autre bloc. Ne complète rien qui ne figure "
        "pas dans le texte. Ne crée aucune transition.\n\n"
        f"{config.DELIM_SOURCE_DEBUT}\n{bloc.contenu}\n{config.DELIM_SOURCE_FIN}"
    )


def editer_bloc(
    *,
    bloc: blocks.Bloc,
    nombre_blocs: int,
    chemins: io.CheminsLivre,
    journal: journalisation.Journal,
    nom_livre: str,
) -> str:
    """
    Édite un bloc et l'enregistre, sauf s'il est déjà terminé.

    Returns:
        L'un des statuts `UNITE_*`.
    """
    libelle = f"bloc {bloc.numero}"

    if io.unite_terminee(chemins.bloc_json(bloc.numero)):
        return UNITE_SAUTEE

    try:
        resultat = api.appeler_modele(
            modele=config.MODEL_EDITION,
            instructions=io.charger_prompt("prompt_edition"),
            message=_message_bloc(bloc, nombre_blocs),
            libelle=libelle,
        )
    except api.EchecAppelAPI as erreur:
        _enregistrer_echec_bloc(
            chemins=chemins,
            bloc=bloc,
            erreur=str(erreur),
            journal=journal,
            nom_livre=nom_livre,
        )
        journalisation.echec(f"{libelle} : {erreur}")
        return UNITE_ECHOUEE

    texte = blocks.nettoyer_enveloppe(resultat.texte)

    avertissements = list(resultat.avertissements)
    avertissements += blocks.verifier_sortie(bloc.contenu, texte)

    statut = io.statut_depuis_avertissements(avertissements)

    # Contenu d'abord, sidecar ensuite : l'ordre porte l'invariant de reprise.
    io.ecrire_texte_atomique(chemins.bloc_txt(bloc.numero), texte)
    io.ecrire_sidecar(
        chemins.bloc_json(bloc.numero),
        {
            "statut": statut,
            "unite": "bloc",
            "numero": bloc.numero,
            "page_debut": bloc.page_debut,
            "page_fin": bloc.page_fin,
            "date_traitement": journalisation.horodatage(),
            "longueur_entree": len(bloc.contenu),
            "avertissements": avertissements,
            **resultat.champs_journal(),
        },
    )

    journal.enregistrer_appel(
        livre=nom_livre,
        unite="bloc",
        numero=bloc.numero,
        longueur_entree=len(bloc.contenu),
        avertissements=avertissements,
        **resultat.champs_journal(),
    )

    if avertissements:
        journalisation.alerte(f"{libelle} : {', '.join(avertissements)}")
        return UNITE_SUSPECTE

    return UNITE_TERMINEE


def _enregistrer_echec_bloc(
    *,
    chemins: io.CheminsLivre,
    bloc: blocks.Bloc,
    erreur: str,
    journal: journalisation.Journal,
    nom_livre: str,
) -> None:
    """Consigne l'échec définitif d'un bloc, sans écrire de `.txt`."""
    io.ecrire_sidecar(
        chemins.bloc_json(bloc.numero),
        {
            "statut": config.STATUT_ECHEC,
            "unite": "bloc",
            "numero": bloc.numero,
            "page_debut": bloc.page_debut,
            "page_fin": bloc.page_fin,
            "modele": config.MODEL_EDITION,
            "date_traitement": journalisation.horodatage(),
            "longueur_entree": len(bloc.contenu),
            "erreur": erreur,
            "avertissements": ["échec définitif de l'appel"],
        },
    )

    journal.enregistrer_appel(
        livre=nom_livre,
        unite="bloc",
        numero=bloc.numero,
        modele=config.MODEL_EDITION,
        longueur_entree=len(bloc.contenu),
        erreur=erreur,
        avertissements=["échec définitif de l'appel"],
    )


def editer_blocs(
    *,
    liste_blocs: list[blocks.Bloc],
    chemins: io.CheminsLivre,
    journal: journalisation.Journal,
    resultat: ResultatLivre,
) -> None:
    """Édite tous les blocs d'un livre."""
    io.assurer_dossier(chemins.dossier_blocs)

    nombre = len(liste_blocs)
    resultat.blocs.total = nombre

    journalisation.info(f"   passe 2a — édition de {nombre} bloc(s)")

    for bloc in liste_blocs:
        statut = editer_bloc(
            bloc=bloc,
            nombre_blocs=nombre,
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
# 3. PASSE 2b — RACCORD
# ============================================================


def preparer_blocs_raccords(
    liste_blocs: list[blocks.Bloc],
    chemins: io.CheminsLivre,
) -> list[int]:
    """
    Copie les blocs édités vers `_EDIT_raccords/`, sans écraser l'existant.

    Ne pas écraser est essentiel : les fichiers de `_EDIT_raccords/` portent
    déjà les corrections des jonctions précédentes. Les recopier depuis
    `_EDIT_blocs/` à chaque exécution annulerait tout le travail de raccord.

    Returns:
        Les numéros des blocs dont la source est absente ou non validée.
    """
    io.assurer_dossier(chemins.dossier_raccords)

    manquants: list[int] = []

    for bloc in liste_blocs:
        numero = bloc.numero
        destination = chemins.raccord_txt(numero)

        if destination.exists():
            continue

        if not io.unite_terminee(chemins.bloc_json(numero)):
            manquants.append(numero)
            continue

        contenu = io.lire_texte_si_present(chemins.bloc_txt(numero))

        if contenu is None:
            manquants.append(numero)
            continue

        io.ecrire_texte_atomique(destination, contenu)

    return manquants


def _message_jonction(
    extrait_gauche: str,
    extrait_droit: str,
    numero: int,
    nombre: int,
) -> str:
    """Construit le message utilisateur d'une jonction."""
    return (
        f"Tu examines la jonction {numero} sur {nombre}.\n\n"
        "Voici la fin du bloc gauche, puis le début du bloc droit.\n\n"
        f"{config.DELIM_RACCORD_GAUCHE}\n{extrait_gauche}\n"
        f"{config.DELIM_RACCORD_GAUCHE_FIN}\n"
        f"{config.DELIM_RACCORD_DROIT}\n{extrait_droit}\n"
        f"{config.DELIM_RACCORD_DROIT_FIN}"
    )


def traiter_jonction(
    *,
    numero: int,
    nombre: int,
    chemins: io.CheminsLivre,
    journal: journalisation.Journal,
    nom_livre: str,
) -> str:
    """
    Examine et corrige une jonction entre les blocs `numero` et `numero + 1`.

    Les deux blocs sont relus **depuis le disque** au moment du traitement, et
    non depuis un état en mémoire : c'est ce qui permet aux corrections de se
    propager de jonction en jonction, et ce qui rend la reprise correcte.

    Returns:
        L'un des statuts `UNITE_*`.
    """
    libelle = f"raccord {numero}"

    if io.unite_terminee(chemins.raccord_json(numero)):
        return UNITE_SAUTEE

    chemin_gauche = chemins.raccord_txt(numero)
    chemin_droit = chemins.raccord_txt(numero + 1)

    texte_gauche = io.lire_texte_si_present(chemin_gauche)
    texte_droit = io.lire_texte_si_present(chemin_droit)

    if texte_gauche is None or texte_droit is None:
        # Un bloc voisin manque : la jonction est intraitable, mais ce n'est pas
        # un échec du raccord. Elle sera reprise quand le bloc sera édité.
        journalisation.alerte(f"{libelle} : bloc voisin manquant, jonction reportée")
        return UNITE_ECHOUEE

    prefixe, extrait_gauche = blocks.fenetre_fin(
        texte_gauche.strip(), config.LIGNES_CONTEXTE_RACCORD
    )
    extrait_droit, suffixe = blocks.fenetre_debut(
        texte_droit.strip(), config.LIGNES_CONTEXTE_RACCORD
    )

    try:
        resultat = api.appeler_modele(
            modele=config.MODEL_RACCORD,
            instructions=io.charger_prompt("prompt_raccord"),
            message=_message_jonction(extrait_gauche, extrait_droit, numero, nombre),
            libelle=libelle,
        )
    except api.EchecAppelAPI as erreur:
        journalisation.echec(f"{libelle} : {erreur}")
        _enregistrer_echec_raccord(
            chemins=chemins,
            numero=numero,
            erreur=str(erreur),
            journal=journal,
            nom_livre=nom_livre,
        )
        return UNITE_ECHOUEE

    gauche_finale, droite_finale, avertissements = _valider_correction(
        reponse=resultat.texte,
        extrait_gauche=extrait_gauche,
        extrait_droit=extrait_droit,
        libelle=libelle,
    )

    avertissements = list(resultat.avertissements) + avertissements

    # Écriture immédiate des deux blocs, puis du sidecar. Une coupure entre les
    # deux fait refaire la jonction sur un texte déjà raccordé — ce qui est sans
    # effet, le prompt exigeant de rendre les extraits inchangés lorsqu'aucune
    # correction n'est nécessaire.
    io.ecrire_texte_atomique(chemin_gauche, blocks.recoller_gauche(prefixe, gauche_finale))
    io.ecrire_texte_atomique(chemin_droit, blocks.recoller_droite(droite_finale, suffixe))

    statut = io.statut_depuis_avertissements(avertissements)

    io.ecrire_sidecar(
        chemins.raccord_json(numero),
        {
            "statut": statut,
            "unite": "raccord",
            "numero": numero,
            "bloc_gauche": numero,
            "bloc_droit": numero + 1,
            "date_traitement": journalisation.horodatage(),
            "lignes_contexte": config.LIGNES_CONTEXTE_RACCORD,
            "longueur_entree": len(extrait_gauche) + len(extrait_droit),
            "avertissements": avertissements,
            **resultat.champs_journal(),
        },
    )

    journal.enregistrer_appel(
        livre=nom_livre,
        unite="raccord",
        numero=numero,
        longueur_entree=len(extrait_gauche) + len(extrait_droit),
        avertissements=avertissements,
        **resultat.champs_journal(),
    )

    return UNITE_SUSPECTE if avertissements else UNITE_TERMINEE


def _valider_correction(
    *,
    reponse: str,
    extrait_gauche: str,
    extrait_droit: str,
    libelle: str,
) -> tuple[str, str, list[str]]:
    """
    Valide la correction proposée, ou conserve les extraits d'origine.

    C'est le garde-fou de la mutation en place. Deux refus possibles :

    - **format non respecté** : les délimiteurs sont introuvables, on ne sait
      donc pas ce que le modèle a voulu dire ;
    - **longueur dérivée** : le modèle a résumé, réécrit, ou tronqué.

    Dans les deux cas, on rend les extraits d'origine. Une jonction non
    corrigée est un défaut mineur ; une jonction corrompue est une perte de
    texte irréversible.

    Returns:
        `(gauche retenue, droite retenue, avertissements)`.
    """
    try:
        gauche, droite = blocks.extraire_blocs_raccord(reponse)
    except ValueError as erreur:
        journalisation.alerte(f"{libelle} : {erreur} — extraits conservés tels quels")
        return extrait_gauche, extrait_droit, [str(erreur)]

    avertissements = [
        *blocks.verifier_raccord(extrait_gauche, gauche),
        *blocks.verifier_raccord(extrait_droit, droite),
    ]

    if avertissements:
        journalisation.alerte(
            f"{libelle} : {', '.join(avertissements)} — extraits conservés tels quels"
        )
        return extrait_gauche, extrait_droit, avertissements

    return gauche, droite, []


def _enregistrer_echec_raccord(
    *,
    chemins: io.CheminsLivre,
    numero: int,
    erreur: str,
    journal: journalisation.Journal,
    nom_livre: str,
) -> None:
    """Consigne l'échec d'une jonction, sans toucher aux blocs."""
    io.ecrire_sidecar(
        chemins.raccord_json(numero),
        {
            "statut": config.STATUT_ECHEC,
            "unite": "raccord",
            "numero": numero,
            "bloc_gauche": numero,
            "bloc_droit": numero + 1,
            "modele": config.MODEL_RACCORD,
            "date_traitement": journalisation.horodatage(),
            "erreur": erreur,
            "avertissements": ["échec définitif de l'appel"],
        },
    )

    journal.enregistrer_appel(
        livre=nom_livre,
        unite="raccord",
        numero=numero,
        modele=config.MODEL_RACCORD,
        erreur=erreur,
        avertissements=["échec définitif de l'appel"],
    )


def effectuer_passe_raccord(
    *,
    liste_blocs: list[blocks.Bloc],
    chemins: io.CheminsLivre,
    journal: journalisation.Journal,
    resultat: ResultatLivre,
) -> None:
    """
    Corrige successivement toutes les jonctions, dans l'ordre croissant.

    L'ordre importe : le bloc droit corrigé à la jonction N sert de bloc gauche
    à la jonction N+1, si bien que les corrections se propagent.
    """
    manquants = preparer_blocs_raccords(liste_blocs, chemins)

    if manquants:
        journalisation.alerte(
            f"   {len(manquants)} bloc(s) non édité(s) : {manquants}"
        )

    nombre = max(0, len(liste_blocs) - 1)
    resultat.raccords.total = nombre

    if nombre == 0:
        journalisation.info("   passe 2b — aucun raccord nécessaire (un seul bloc)")
        return

    journalisation.info(f"   passe 2b — {nombre} jonction(s)")

    for numero in range(1, nombre + 1):
        statut = traiter_jonction(
            numero=numero,
            nombre=nombre,
            chemins=chemins,
            journal=journal,
            nom_livre=resultat.nom,
        )

        resultat.raccords.enregistrer(statut, numero)

        if statut != UNITE_SAUTEE:
            journal.sauvegarder()
            api.patienter()

        journalisation.progression(numero, nombre, "raccords")


# ============================================================
# 4. ASSEMBLAGE
# ============================================================


def assembler_edit(chemins: io.CheminsLivre, nombre_blocs: int) -> str:
    """
    Assemble `EDIT.txt` **exclusivement** depuis `_EDIT_raccords/`.

    Ne jamais assembler depuis `_EDIT_blocs/` : ces fichiers ne portent pas les
    corrections de jonction, et le fichier final présenterait alors les mots
    coupés et les doublons que la passe 2b vient précisément de résoudre.

    Un bloc absent reçoit un marqueur visible, sur le même principe qu'à
    l'étape 1 : un trou repérable vaut mieux qu'un trou silencieux.
    """
    morceaux: list[str] = []

    for numero in range(1, nombre_blocs + 1):
        texte = io.lire_texte_si_present(chemins.raccord_txt(numero))

        if texte is None or not texte.strip():
            morceaux.append(config.MARQUEUR_ECHEC_BLOC.format(numero=numero))
            continue

        morceaux.append(texte.strip())

    return blocks.assembler(morceaux)


# ============================================================
# 5. TRAITEMENT D'UN LIVRE
# ============================================================


def traiter_fichier_ocr(
    chemin_ocr: Path,
    journal: journalisation.Journal,
) -> ResultatLivre:
    """Édite un fichier OCR de bout en bout : passe 2a, passe 2b, assemblage."""
    nom_livre = io.nom_livre_depuis_ocr(chemin_ocr)
    chemins = io.resoudre_chemins(nom_livre, chemin_ocr.parent)
    resultat = ResultatLivre(nom=nom_livre)

    journalisation.section(f"Édition — {nom_livre}")

    with journalisation.Chrono() as chrono:
        try:
            liste_blocs = _preparer_blocs(chemin_ocr)

            journalisation.info(
                f"   {len(liste_blocs)} bloc(s) de "
                f"{config.PAGES_PAR_BLOC} page(s) au plus"
            )

            editer_blocs(
                liste_blocs=liste_blocs,
                chemins=chemins,
                journal=journal,
                resultat=resultat,
            )
            effectuer_passe_raccord(
                liste_blocs=liste_blocs,
                chemins=chemins,
                journal=journal,
                resultat=resultat,
            )
            _ecrire_edit(chemins, len(liste_blocs))

        except Exception as erreur:
            # Un livre en erreur ne doit pas empêcher de traiter les suivants.
            resultat.statut = config.STATUT_ECHEC
            resultat.erreur = str(erreur)
            journalisation.echec(f"{nom_livre} : {erreur}")

    resultat.duree_secondes = chrono.secondes

    if resultat.statut != config.STATUT_ECHEC:
        resultat.statut = (
            config.STATUT_TERMINE if resultat.complet else config.STATUT_SUSPECT
        )
        _afficher_bilan_livre(resultat)

    journal.resumer_livre(nom_livre, **resultat.champs_journal())
    journal.sauvegarder()

    return resultat


def _preparer_blocs(chemin_ocr: Path) -> list[blocks.Bloc]:
    """
    Découpe le fichier OCR en blocs.

    Raises:
        ValueError: si le fichier ne contient aucune page exploitable.
    """
    texte = io.lire_texte(chemin_ocr)
    pages = blocks.decouper_en_pages(texte)

    if not pages:
        raise ValueError(f"aucune page exploitable dans {chemin_ocr.name}")

    return blocks.former_blocs(pages, config.PAGES_PAR_BLOC)


def _ecrire_edit(chemins: io.CheminsLivre, nombre_blocs: int) -> None:
    """Écrit le fichier EDIT assemblé."""
    contenu = assembler_edit(chemins, nombre_blocs)
    io.ecrire_texte_atomique(chemins.edit, contenu)

    journalisation.succes(
        f"{chemins.edit.name} — "
        f"{journalisation.formater_nombre(len(contenu))} caractères"
    )


def _afficher_bilan_livre(resultat: ResultatLivre) -> None:
    """Affiche les reprises restantes pour un livre."""
    journalisation.afficher_reprises("bloc", resultat.blocs)
    journalisation.afficher_reprises("raccord", resultat.raccords)


# ============================================================
# 6. POINT D'ENTRÉE DE L'ÉTAPE
# ============================================================


def executer(dossier: Path | None = None) -> list[ResultatLivre]:
    """
    Lance l'étape d'édition sur tous les fichiers OCR du dossier.

    Args:
        dossier: dossier à parcourir. `config.DOSSIER_DRIVE` par défaut.

    Returns:
        Un bilan par livre traité.
    """
    base = dossier if dossier is not None else config.DOSSIER_DRIVE

    journalisation.titre("Étape 2 — Édition OCR")

    fichiers = io.lister_fichiers_ocr(base)
    journalisation.info(f"Dossier : {base}")
    journalisation.info(f"Fichiers OCR trouvés : {len(fichiers)}")

    if not fichiers:
        journalisation.alerte(
            f"aucun fichier « {config.SUFFIXE_OCR} » — lancez d'abord l'étape OCR"
        )
        return []

    journal = journalisation.Journal.charger_ou_creer(
        NOM_ETAPE,
        base,
        {
            "modele_edition": config.MODEL_EDITION,
            "modele_raccord": config.MODEL_RACCORD,
            "pages_par_bloc": config.PAGES_PAR_BLOC,
            "lignes_contexte_raccord": config.LIGNES_CONTEXTE_RACCORD,
            "max_output_tokens": config.MAX_OUTPUT_TOKENS,
        },
    )

    resultats = [traiter_fichier_ocr(chemin, journal) for chemin in fichiers]

    _afficher_recapitulatif(resultats, journal)

    return resultats


def _afficher_recapitulatif(
    resultats: list[ResultatLivre],
    journal: journalisation.Journal,
) -> None:
    """Affiche le bilan global de l'étape."""
    a_reprendre = [r.nom for r in resultats if not r.complet]

    journalisation.recapitulatif(
        {
            "Livres traités": len(resultats),
            "Blocs édités": sum(r.blocs.traitees for r in resultats),
            "Blocs déjà faits": sum(r.blocs.sautees for r in resultats),
            "Blocs suspects": sum(r.blocs.suspectes for r in resultats),
            "Blocs en échec": sum(r.blocs.echouees for r in resultats),
            "Raccords traités": sum(r.raccords.traitees for r in resultats),
            "Raccords déjà faits": sum(r.raccords.sautees for r in resultats),
            "Raccords en échec": sum(r.raccords.echouees for r in resultats),
            "Durée": journalisation.formater_duree(
                sum(r.duree_secondes for r in resultats)
            ),
            "Journal": journal.chemin.name,
        }
    )

    if a_reprendre:
        journalisation.info("")
        journalisation.alerte(
            f"à reprendre en relançant cette étape : {', '.join(a_reprendre)}"
        )
