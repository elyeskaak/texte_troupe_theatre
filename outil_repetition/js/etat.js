/**
 * L'état de session et ses transitions.
 *
 * Module **pur** : chaque transition prend un état et rend un **nouvel** état,
 * sans rien modifier sur place. Ni DOM, ni stockage, ni horloge.
 *
 * Deux choix de représentation méritent d'être expliqués.
 *
 * **Des tableaux, pas des `Set`.** Une partie de cet état est persistée dans
 * `localStorage`, et `JSON.stringify(new Set())` rend `{}` — silencieusement. Le
 * bug serait invisible à l'écriture et ne se manifesterait qu'au rechargement,
 * par un rôle actif vide. Les tableaux sérialisent tels quels.
 *
 * **Le volatile est séparé du persistant.** `revelees` — les répliques dévoilées
 * au doigt — ne doit jamais survivre à une session : sans quoi une réplique
 * révélée hier serait révélée demain, et le mode « masquage » paraîtrait cassé.
 * `partiePersistante()` marque cette frontière explicitement, plutôt que de la
 * laisser à la mémoire de celui qui écrira `stockage.js`.
 */

import { CONFIG } from './config.js';

/**
 * Les huit modes de masquage, du plus visible au moins visible.
 *
 * `ACRONYME` ne se range pas franchement sur cette échelle : il ne cache pas
 * *une part* du texte, il en garde le squelette entier. C'est ce qui en fait un
 * mode de révision plutôt qu'un mode d'apprentissage — on l'emploie quand la
 * réplique est presque sue et qu'il ne manque que le déclic.
 */
export const MODE = Object.freeze({
  LECTURE: 'lecture',
  MASQUAGE: 'masquage',
  AMORCE: 'amorce',
  TROUS: 'trous',
  ACRONYME: 'acronyme',
  AVEUGLE: 'aveugle',
  TOP: 'top',
  /** Récitation contrôlée : masquée comme au rideau, puis comparée au micro. */
  VOIX: 'voix',
});

const MODES = Object.freeze(Object.values(MODE));

/** Modes dans lesquels une réplique révélée a un sens. */
const MODES_MASQUANTS = Object.freeze([
  MODE.MASQUAGE,
  MODE.AMORCE,
  MODE.TROUS,
  MODE.ACRONYME,
  MODE.AVEUGLE,
  MODE.TOP,
  MODE.VOIX,
]);

/**
 * État de départ d'une session.
 *
 * @param {{pieceId?: string, mesRoles?: string[]}} depart
 */
export function etatInitial({ pieceId = null, mesRoles = [] } = {}) {
  const roles = _uniques(mesRoles);

  return Object.freeze({
    pieceId,
    mesRoles: roles,
    // Par défaut je répète tous mes rôles : c'est le cas le plus courant, et
    // cela évite un écran de choix obligatoire quand je n'en ai qu'un.
    roleActif: roles,
    mode: MODE.MASQUAGE,
    mesScenesSeules: false,
    difficulte: CONFIG.DIFFICULTE_DEFAUT,
    uniteCourante: null,
    repliqueCourante: null,
    reglages: Object.freeze({
      taillePolice: 1,
      vitesseDefilement: CONFIG.VITESSE_DEFILEMENT[0],
      sombre: true,
      topReduit: false,
    }),
    revelees: [],
    passageTrous: 0,
  });
}

// ============================================================
// TRANSITIONS
// ============================================================

/**
 * Change de mode.
 *
 * **Vide `revelees`**, et c'est le point important : passer en « amorce » puis
 * revenir en « masquage » doit remasquer. Conserver les révélations donnerait un
 * mode qui ne masque plus rien sans qu'on comprenne pourquoi.
 *
 * Un mode inconnu est **refusé** plutôt qu'appliqué : un `data-mode` sans règle
 * CSS afficherait tout le texte, c'est-à-dire exactement le contraire de ce qui
 * est demandé.
 */
export function changerMode(etat, mode) {
  if (!MODES.includes(mode)) {
    throw new Error(`mode inconnu : « ${mode} ». Modes : ${MODES.join(', ')}.`);
  }

  return _avec(etat, { mode, revelees: [] });
}

/**
 * Change le rôle répété dans cette session.
 *
 * L'invariant `roleActif ⊆ mesRoles` est **vérifié, pas corrigé en silence** : un
 * rôle actif hors de mes rôles masquerait les répliques de quelqu'un d'autre, ce
 * qui rendrait la scène incompréhensible sans rien signaler.
 *
 * Vide `revelees` pour la même raison que `changerMode` : les répliques
 * révélées ne concernaient pas ce rôle.
 */
export function changerRoleActif(etat, roles) {
  const demandes = _uniques(roles);

  if (demandes.length === 0) {
    throw new Error('le rôle actif ne peut pas être vide : rien ne serait masqué.');
  }

  const inconnus = demandes.filter((role) => !etat.mesRoles.includes(role));

  if (inconnus.length > 0) {
    throw new Error(
      `rôle actif hors de mes rôles : ${inconnus.join(', ')}. ` +
        `Mes rôles : ${etat.mesRoles.join(', ') || '(aucun)'}.`,
    );
  }

  return _avec(etat, { roleActif: demandes, revelees: [] });
}

/**
 * Change les personnages que je joue dans la pièce.
 *
 * C'est ici, et seulement ici, que corriger le rôle actif est légitime, puisque
 * c'est `mesRoles` qui vient de changer. Deux mouvements, et ils ne se traitent
 * pas de la même façon :
 *
 * - un rôle **retiré** de mes rôles quitte le rôle actif — l'invariant l'exige ;
 * - un rôle **ajouté** à mes rôles **rejoint** le rôle actif. Déclarer qu'on joue
 *   un personnage, c'est dire qu'on veut le répéter. Se contenter de conserver
 *   l'intersection le laisserait déclaré mais inactif, donc affiché en clair : on
 *   croirait l'outil cassé, alors qu'il aurait suivi la lettre d'une règle faite
 *   pour le retrait.
 *
 * Si le résultat est vide, le rôle actif repart de l'ensemble de mes rôles.
 *
 * Change aussi l'index (`modele.indexer`) : l'appelant doit réindexer.
 */
export function changerMesRoles(etat, roles) {
  const miens = _uniques(roles);
  const conserves = etat.roleActif.filter((role) => miens.includes(role));
  const ajoutes = miens.filter((role) => !etat.mesRoles.includes(role));
  const actif = [...new Set([...conserves, ...ajoutes])];

  return _avec(etat, {
    mesRoles: miens,
    roleActif: actif.length > 0 ? actif : miens,
    revelees: [],
  });
}

/** Replie ou déplie les scènes où je n'apparais pas. */
export function basculerMesScenesSeules(etat) {
  return _avec(etat, { mesScenesSeules: !etat.mesScenesSeules });
}

/**
 * Change le pourcentage de mots masqués.
 *
 * Borné à 0–100 sans erreur : la valeur vient d'un curseur, et un curseur ne
 * mérite pas une exception.
 */
export function changerDifficulte(etat, pourcentage) {
  const borne = Math.min(100, Math.max(0, Math.round(pourcentage)));

  return _avec(etat, { difficulte: borne });
}

/**
 * Demande un nouveau tirage des mots à trous.
 *
 * Incrémente le numéro de passage, qui entre dans la graine (`tirage.js`). C'est
 * ce qui rend les trous **stables par défaut** et changeables sur demande.
 */
export function nouveauTirage(etat) {
  return _avec(etat, { passageTrous: etat.passageTrous + 1 });
}

/** Révèle une réplique. Idempotent : révéler deux fois ne duplique rien. */
export function revelerReplique(etat, id) {
  if (etat.revelees.includes(id)) {
    return etat;
  }

  return _avec(etat, { revelees: [...etat.revelees, id] });
}

/** Remasque tout, sans changer de mode. */
export function toutRemasquer(etat) {
  return etat.revelees.length === 0 ? etat : _avec(etat, { revelees: [] });
}

/** La réplique est-elle actuellement révélée ? */
export function estRevelee(etat, id) {
  return etat.revelees.includes(id);
}

/** Le mode courant masque-t-il quelque chose ? */
export function masque(etat) {
  return MODES_MASQUANTS.includes(etat.mode);
}

/** Déplace la position courante. */
export function allerA(etat, { unite = undefined, replique = undefined } = {}) {
  const changements = {};

  if (unite !== undefined) {
    changements.uniteCourante = unite;
  }

  if (replique !== undefined) {
    changements.repliqueCourante = replique;
  }

  return Object.keys(changements).length === 0 ? etat : _avec(etat, changements);
}

/** Modifie un réglage d'affichage. */
export function changerReglage(etat, nom, valeur) {
  if (!(nom in etat.reglages)) {
    throw new Error(
      `réglage inconnu : « ${nom} ». Connus : ${Object.keys(etat.reglages).join(', ')}.`,
    );
  }

  return _avec(etat, {
    reglages: Object.freeze({ ...etat.reglages, [nom]: valeur }),
  });
}

// ============================================================
// PERSISTANCE
// ============================================================

/** Champs volatils, jamais écrits dans `localStorage`. */
const VOLATILS = Object.freeze(['revelees']);

/**
 * Part de l'état à persister.
 *
 * La frontière est déclarée ici, et non chez l'appelant : `stockage.js` n'a pas à
 * savoir ce qui est volatil, et un champ ajouté plus tard sera persisté par
 * défaut — le bon défaut, puisqu'oublier de persister un réglage est bénin alors
 * qu'oublier de vider `revelees` casse un mode.
 */
export function partiePersistante(etat) {
  const copie = { ...etat };

  for (const champ of VOLATILS) {
    delete copie[champ];
  }

  return copie;
}

/**
 * Reconstruit un état depuis des données persistées.
 *
 * Tolérant par construction : tout champ absent, inconnu ou invalide retombe sur
 * l'état initial. C'est le principe P4 — la progression et les réglages sont des
 * données d'agrément, et leur perte ne doit jamais empêcher de répéter. Un état
 * corrompu doit donc ouvrir une session neuve, jamais une page blanche.
 *
 * @param {unknown} donnees
 * @param {{pieceId?: string, mesRoles?: string[]}} depart
 */
export function restaurer(donnees, depart = {}) {
  const initial = etatInitial(depart);

  if (donnees === null || typeof donnees !== 'object' || Array.isArray(donnees)) {
    return initial;
  }

  let etat = initial;

  if (MODES.includes(donnees.mode)) {
    etat = _avec(etat, { mode: donnees.mode });
  }

  if (typeof donnees.mesScenesSeules === 'boolean') {
    etat = _avec(etat, { mesScenesSeules: donnees.mesScenesSeules });
  }

  if (typeof donnees.difficulte === 'number') {
    etat = changerDifficulte(etat, donnees.difficulte);
  }

  if (Number.isInteger(donnees.passageTrous) && donnees.passageTrous >= 0) {
    etat = _avec(etat, { passageTrous: donnees.passageTrous });
  }

  etat = _avec(etat, {
    uniteCourante: _chaineOuNull(donnees.uniteCourante),
    repliqueCourante: _chaineOuNull(donnees.repliqueCourante),
    reglages: Object.freeze({
      ..._reglagesValides(donnees.reglages, initial.reglages),
    }),
  });

  // Le rôle actif est restauré en dernier, et seulement s'il tient l'invariant :
  // un rôle disparu de la pièce après une réédition ne doit pas ouvrir une
  // session dans un état interdit.
  if (Array.isArray(donnees.roleActif)) {
    const valides = _uniques(donnees.roleActif).filter((role) =>
      etat.mesRoles.includes(role),
    );

    if (valides.length > 0) {
      etat = changerRoleActif(etat, valides);
    }
  }

  return etat;
}

function _reglagesValides(candidats, defauts) {
  if (candidats === null || typeof candidats !== 'object') {
    return defauts;
  }

  const resultat = { ...defauts };

  for (const [nom, valeur] of Object.entries(candidats)) {
    // Un réglage inconnu est ignoré, pas conservé : le garder ferait échouer
    // `changerReglage` plus tard sur un nom qui n'existe plus dans le code.
    if (nom in defauts && typeof valeur === typeof defauts[nom]) {
      resultat[nom] = valeur;
    }
  }

  return resultat;
}

// ============================================================
// OUTILS
// ============================================================

function _avec(etat, changements) {
  return Object.freeze({ ...etat, ...changements });
}

function _uniques(valeurs) {
  if (!Array.isArray(valeurs)) {
    return [];
  }

  return [...new Set(valeurs.filter((v) => typeof v === 'string' && v !== ''))];
}

function _chaineOuNull(valeur) {
  return typeof valeur === 'string' && valeur !== '' ? valeur : null;
}
