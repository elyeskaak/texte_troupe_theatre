/**
 * Index dérivé d'une pièce.
 *
 * Module **pur**. Il calcule en une passe ce que le rendu et la navigation
 * demanderaient sinon en boucle : quelles unités sont les miennes, où est le top
 * de chaque réplique, l'ordre de jeu, le sommaire.
 *
 * L'index dépend de **`mesRoles`, pas du rôle actif**. C'est la distinction du
 * §10.3 de l'architecture : mes rôles décident ce qui est une de mes scènes et où
 * sont les tops — c'est structurel ; le rôle actif décide seulement de ce qui est
 * masqué, et reste dans le CSS. Changer de rôle actif en cours de session ne
 * réindexe donc rien.
 */

import { repliques as toutesLesRepliques } from './schema.js';
import { contient, derniersMots } from './texte.js';

/** Nature du top d'une réplique. */
export const TOP = Object.freeze({
  /** Réplique d'un autre personnage. */
  REPLIQUE: 'replique',
  /** Didascalie ou indication de lieu : une porte qui claque est un top. */
  DIDASCALIE: 'didascalie',
  /** Aucun top — voir `MOTIF_SANS_TOP`. */
  AUCUN: 'aucun',
});

/** Pourquoi une réplique n'a pas de top. */
export const MOTIF_SANS_TOP = Object.freeze({
  /** Elle ouvre l'unité jouable. */
  DEBUT: 'debut_unite',
  /** La dernière réplique avant elle est une des miennes. */
  ENCHAINEMENT: 'enchainement',
});

/**
 * Construit l'index d'une pièce.
 *
 * @param {object} piece - document validé par `schema.valider`
 * @param {string[]} mesRoles - personnages que je joue dans cette pièce
 */
export function indexer(piece, mesRoles = []) {
  const miens = new Set(mesRoles);

  const unites = piece.unites.map((unite) => ({
    ...unite,
    mienne: unite.personnages.some((nom) => miens.has(nom)),
    nbMesRepliques: _compterMesRepliques(unite, miens),
  }));

  const repliques = new Map();
  const ordreRepliques = [];
  const mesRepliques = [];

  for (const replique of toutesLesRepliques(piece)) {
    const mienne = miens.has(replique.personnage);

    repliques.set(replique.id, {
      ...replique,
      mienne,
      position: ordreRepliques.length,
    });

    ordreRepliques.push(replique.id);

    if (mienne) {
      mesRepliques.push(replique.id);
    }
  }

  return {
    piece: piece.piece,
    mesRoles: [...miens],
    unites,
    repliques,
    ordreRepliques,
    mesRepliques,
    tops: _calculerTops(piece, miens),
    sommaire: unites.map(_entreeDeSommaire),
    personnages: piece.personnages,
  };
}

function _compterMesRepliques(unite, miens) {
  return unite.elements.filter(
    (element) => element.type === 'replique' && miens.has(element.personnage),
  ).length;
}

function _entreeDeSommaire(unite) {
  return {
    unite: unite.id,
    titre: titreDUnite(unite),
    acte: unite.acte,
    scene: unite.scene,
    mienne: unite.mienne,
    nbMesRepliques: unite.nbMesRepliques,
  };
}

/**
 * Titre affichable d'une unité jouable.
 *
 * Une unité implicite — ouverte par un `***` — n'a pas de titre propre : lui en
 * fabriquer un afficherait une scène qui n'existe pas dans le texte de l'auteur.
 * Elle se désigne par sa position, et le rendu peut choisir de ne rien montrer.
 *
 * @param {object} unite
 */
export function titreDUnite(unite) {
  if (unite.implicite) {
    return null;
  }

  return unite.scene ?? unite.acte ?? null;
}

// ============================================================
// LE TOP
// ============================================================

/**
 * Calcule le top de chacune de mes répliques.
 *
 * **Le top n'est pas « l'élément précédent ».** Le §10.1 de l'architecture pose
 * deux exigences qui paraissent se contredire : une didascalie *peut* être un top
 * (une porte qui claque en est un), mais deux de mes répliques séparées par une
 * didascalie n'ont *pas* de top. Une règle unique les réconcilie :
 *
 * 1. chercher la dernière **réplique** avant la mienne, en traversant les
 *    didascalies ;
 * 2. si c'est une des miennes → aucun top, `ENCHAINEMENT`. C'est moi qui parlais
 *    juste avant : il n'y a pas de signal à attendre ;
 * 3. sinon, le top est le **premier élément signalant** rencontré en remontant —
 *    la réplique de l'autre, ou la didascalie qui la suit si elle en est séparée
 *    par une ;
 * 4. s'il n'y a rien de signalant avant → aucun top, `DEBUT`.
 *
 * Le cas 3 traite aussi la scène qui ouvre sur une didascalie : « On frappe à la
 * porte » devient le top, puisqu'aucune réplique ne la précède.
 *
 * **Un `lieu` n'est jamais un top**, et c'est la seule subtilité de la règle.
 * « Un salon. Le soir tombe. » est un décor, pas un événement : on ne peut pas
 * attendre qu'il se produise pour parler. Le JSON en fait justement un type
 * distinct de `didascalie`, et l'exclure ici rend cette distinction utile. Une
 * réplique qui ouvre une scène derrière une indication de lieu relève donc du
 * cas 4 — elle ouvre la scène, ce qui est la vérité.
 *
 * Afficher un encadré vide, ou le top d'avant, induirait en erreur en
 * répétition : `AUCUN` est une information utile, pas une absence de donnée.
 */
function _calculerTops(piece, miens) {
  const tops = new Map();

  for (const unite of piece.unites) {
    for (let i = 0; i < unite.elements.length; i += 1) {
      const element = unite.elements[i];

      if (element.type !== 'replique' || !miens.has(element.personnage)) {
        continue;
      }

      tops.set(element.id, _topDe(unite.elements, i, miens));
    }
  }

  return tops;
}

/** Types d'élément qui ne signalent rien : ni réplique, ni événement. */
const MUETS = new Set(['lieu', 'texte_sans_personnage']);

function _topDe(elements, position, miens) {
  const derniere = _derniereRepliqueAvant(elements, position);

  if (derniere && miens.has(derniere.personnage)) {
    return { type: TOP.AUCUN, motif: MOTIF_SANS_TOP.ENCHAINEMENT };
  }

  const precedent = _premierSignalantAvant(elements, position);

  if (precedent === null) {
    return { type: TOP.AUCUN, motif: MOTIF_SANS_TOP.DEBUT };
  }

  if (precedent.type === 'replique') {
    return {
      type: TOP.REPLIQUE,
      personnage: precedent.personnage,
      texte: precedent.texte,
      id: precedent.id,
    };
  }

  return { type: TOP.DIDASCALIE, texte: precedent.texte };
}

function _derniereRepliqueAvant(elements, position) {
  for (let i = position - 1; i >= 0; i -= 1) {
    if (elements[i].type === 'replique') {
      return elements[i];
    }
  }

  return null;
}

function _premierSignalantAvant(elements, position) {
  for (let i = position - 1; i >= 0; i -= 1) {
    if (!MUETS.has(elements[i].type)) {
      return elements[i];
    }
  }

  return null;
}

/**
 * Texte du top, éventuellement réduit à ses derniers mots.
 *
 * @param {object} top - entrée de `index.tops`
 * @param {number|null} combienDeMots - `null` pour le texte entier
 * @returns {string|null} `null` quand il n'y a pas de top
 */
export function texteDuTop(top, combienDeMots = null) {
  if (!top || top.type === TOP.AUCUN) {
    return null;
  }

  if (combienDeMots === null) {
    return top.texte;
  }

  return derniersMots(top.texte, combienDeMots);
}

// ============================================================
// NAVIGATION ET RECHERCHE
// ============================================================

/**
 * Identifiant de ma réplique suivante ou précédente.
 *
 * Porte sur `mesRepliques` et non sur le DOM : le saut de top à top fonctionne
 * donc même vers une unité qui n'est pas montée.
 *
 * @param {object} index
 * @param {string|null} depuis - identifiant courant, `null` pour partir du début
 * @param {number} sens - +1 ou -1
 * @returns {string|null}
 */
export function repliqueVoisine(index, depuis, sens) {
  const liste = index.mesRepliques;

  if (liste.length === 0) {
    return null;
  }

  if (depuis === null) {
    return sens > 0 ? liste[0] : liste[liste.length - 1];
  }

  const position = liste.indexOf(depuis);

  if (position === -1) {
    return liste[0];
  }

  const cible = position + sens;

  return cible >= 0 && cible < liste.length ? liste[cible] : null;
}

/**
 * Cherche un fragment dans toute la pièce.
 *
 * Porte sur l'index, jamais sur le DOM : la recherche couvre donc la pièce
 * entière même si une seule unité est montée (§6.4).
 *
 * @param {object} index
 * @param {string} fragment
 * @returns {Array<{id: string, unite: string, personnage: string, texte: string}>}
 */
export function chercher(index, fragment) {
  const resultats = [];

  for (const id of index.ordreRepliques) {
    const replique = index.repliques.get(id);

    if (contient(replique.texte, fragment)) {
      resultats.push({
        id,
        unite: replique.unite,
        personnage: replique.personnage,
        texte: replique.texte,
      });
    }
  }

  return resultats;
}

// ============================================================
// PROGRESSION ET SPOT CHECK
// ============================================================

/** Statuts d'apprentissage, du moins au mieux su. */
export const STATUT = Object.freeze({
  A_APPRENDRE: 'a_apprendre',
  EN_COURS: 'en_cours',
  MAITRISEE: 'maitrisee',
});

const ORDRE_STATUTS = [STATUT.A_APPRENDRE, STATUT.EN_COURS, STATUT.MAITRISEE];

/**
 * Statut d'une unité, déduit de celui de mes répliques.
 *
 * Déduit et non stocké : un statut d'unité rangé à part deviendrait une seconde
 * source de vérité, qui se désynchroniserait au premier changement de réplique.
 *
 * Le statut retenu est **le plus faible**, jamais une moyenne : une scène dont
 * une réplique reste à apprendre n'est pas maîtrisée aux trois quarts, elle n'est
 * pas maîtrisée.
 *
 * @param {object} index
 * @param {string} idUnite
 * @param {Record<string, {statut?: string}>} progres
 * @returns {string|null} `null` si je n'ai aucune réplique dans cette unité
 */
export function statutDUnite(index, idUnite, progres) {
  const unite = index.unites.find((u) => u.id === idUnite);

  if (!unite || unite.nbMesRepliques === 0) {
    return null;
  }

  const miens = new Set(index.mesRoles);
  let pire = ORDRE_STATUTS.length - 1;

  for (const element of unite.elements) {
    if (element.type !== 'replique' || !miens.has(element.personnage)) {
      continue;
    }

    const statut = progres[element.id]?.statut ?? STATUT.A_APPRENDRE;
    const rang = ORDRE_STATUTS.indexOf(statut);

    pire = Math.min(pire, rang === -1 ? 0 : rang);
  }

  return ORDRE_STATUTS[pire];
}

/**
 * Candidats au spot check, pondérés par l'ancienneté de leur vérification.
 *
 * Un tirage uniforme parmi les répliques maîtrisées redemanderait souvent celles
 * qu'on vient de vérifier. Le poids croît avec le temps écoulé depuis la dernière
 * vérification : à maîtrise égale, la plus anciennement vue sort la première.
 * C'est le seul comportement qui teste réellement la mémoire à long terme, et il
 * ne coûte qu'un parcours.
 *
 * Une réplique jamais vérifiée reçoit le poids maximal : c'est la plus incertaine
 * de toutes.
 *
 * @param {object} index
 * @param {Record<string, {statut?: string, verifiee_le?: number}>} progres
 * @param {number} maintenant - horodatage, passé en argument pour rester pur
 */
export function candidatsSpotCheck(index, progres, maintenant) {
  const candidats = [];

  for (const id of index.mesRepliques) {
    const suivi = progres[id];

    if (suivi?.statut !== STATUT.MAITRISEE) {
      continue;
    }

    const depuis =
      typeof suivi.verifiee_le === 'number'
        ? Math.max(0, maintenant - suivi.verifiee_le)
        : Number.POSITIVE_INFINITY;

    // Le poids est en jours écoulés, plancher à 1 : sans plancher, une réplique
    // vérifiée à l'instant aurait un poids nul et deviendrait impossible à
    // tirer, alors qu'elle doit seulement être improbable.
    candidats.push({
      valeur: id,
      poids: Number.isFinite(depuis) ? Math.max(1, depuis / 86400000) : 1000,
    });
  }

  return candidats;
}

/**
 * Bilan chiffré, pour l'écran de progression.
 *
 * @param {object} index
 * @param {Record<string, {statut?: string}>} progres
 */
export function bilan(index, progres) {
  const compte = {
    [STATUT.A_APPRENDRE]: 0,
    [STATUT.EN_COURS]: 0,
    [STATUT.MAITRISEE]: 0,
  };

  for (const id of index.mesRepliques) {
    const statut = progres[id]?.statut ?? STATUT.A_APPRENDRE;

    if (statut in compte) {
      compte[statut] += 1;
    } else {
      // Un statut inconnu — venu d'un export plus récent — ne doit pas être
      // perdu du décompte : il compte comme « à apprendre », le plus prudent.
      compte[STATUT.A_APPRENDRE] += 1;
    }
  }

  return { total: index.mesRepliques.length, ...compte };
}
