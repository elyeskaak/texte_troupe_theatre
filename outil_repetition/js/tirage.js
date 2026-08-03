/**
 * Aléatoire reproductible.
 *
 * Module **pur** : ni `Math.random`, ni horloge. C'est tout l'intérêt.
 *
 * Le prototype de l'outil appelait `Math.random()` à chaque rendu, ce qui
 * produisait deux défauts jumeaux : les trous se déplaçaient à chaque bascule de
 * mode, et une réplique travaillée trois fois de suite masquait trois fois des
 * mots différents — empêchant exactement le travail qu'on cherche à faire.
 *
 * Ici, la graine dérive de `(identifiant de réplique, difficulté, numéro de
 * passage)`. Les trous sont donc stables tant qu'on ne demande pas un nouveau
 * tirage, et « nouveau tirage » n'est qu'un incrément du numéro de passage.
 */

/**
 * Réduit une chaîne à un entier 32 bits.
 *
 * Variante de FNV-1a. Le choix d'un hachage non cryptographique est délibéré :
 * on veut une dispersion correcte et un résultat identique sur tous les moteurs
 * JavaScript, pas de la résistance aux collisions.
 *
 * @param {string} texte
 * @returns {number} entier non signé sur 32 bits
 */
export function graineDepuis(texte) {
  let valeur = 0x811c9dc5;

  for (let i = 0; i < texte.length; i += 1) {
    valeur ^= texte.charCodeAt(i);
    // Multiplication par le nombre premier FNV, en arithmétique 32 bits.
    valeur = Math.imul(valeur, 0x01000193);
  }

  // `>>> 0` ramène dans les entiers non signés : sans cela, la valeur peut être
  // négative et la reproductibilité dépendrait de la façon de la consommer.
  return valeur >>> 0;
}

/**
 * Graine d'une réplique, pour un réglage et un passage donnés.
 *
 * @param {string} idReplique
 * @param {number} difficulte
 * @param {number} passage - incrémenté par « nouveau tirage »
 */
export function graineReplique(idReplique, difficulte, passage = 0) {
  return graineDepuis(`${idReplique}|${difficulte}|${passage}`);
}

/**
 * Générateur pseudo-aléatoire déterministe (mulberry32).
 *
 * @param {number} graine
 * @returns {() => number} suite de flottants dans [0, 1)
 */
export function generateur(graine) {
  let etat = graine >>> 0;

  return function suivant() {
    etat = (etat + 0x6d2b79f5) >>> 0;

    let melange = etat;
    melange = Math.imul(melange ^ (melange >>> 15), melange | 1);
    melange ^= melange + Math.imul(melange ^ (melange >>> 7), melange | 61);

    return ((melange ^ (melange >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Choisit `combien` indices distincts parmi `total`, de façon reproductible.
 *
 * Mélange partiel de Fisher-Yates plutôt que des tirages répétés avec rejet :
 * le prototype bouclait jusqu'à 500 fois en espérant tomber sur des indices
 * neufs, ce qui rendait le résultat dépendant du nombre d'essais — donc non
 * reproductible dès que la difficulté approchait 100 %.
 *
 * @param {number} total - nombre d'éléments disponibles
 * @param {number} combien - nombre d'indices voulus
 * @param {number} graine
 * @returns {number[]} indices triés par ordre croissant
 */
export function tirerIndices(total, combien, graine) {
  if (total <= 0 || combien <= 0) {
    return [];
  }

  const voulus = Math.min(combien, total);
  const suivant = generateur(graine);
  const indices = Array.from({ length: total }, (_, i) => i);

  for (let i = 0; i < voulus; i += 1) {
    const j = i + Math.floor(suivant() * (total - i));
    [indices[i], indices[j]] = [indices[j], indices[i]];
  }

  return indices.slice(0, voulus).sort((a, b) => a - b);
}

/**
 * Indices des mots à masquer dans une réplique.
 *
 * Au moins un mot est toujours masqué dès qu'il y en a un : une difficulté à
 * 5 % sur une réplique de trois mots donnerait sinon zéro trou, et le mode
 * paraîtrait cassé.
 *
 * @param {number} nombreDeMots
 * @param {number} pourcentage - 0 à 100
 * @param {number} graine
 */
export function motsAMasquer(nombreDeMots, pourcentage, graine) {
  if (nombreDeMots <= 0) {
    return [];
  }

  const combien = Math.max(1, Math.round((nombreDeMots * pourcentage) / 100));

  return tirerIndices(nombreDeMots, combien, graine);
}

/**
 * Choisit un élément parmi des candidats pondérés, de façon reproductible.
 *
 * Sert au spot check : à maîtrise égale, la réplique vue le plus anciennement
 * doit sortir la première. Un tirage uniforme redemanderait souvent celle qu'on
 * vient de vérifier, ce qui ne teste pas la mémoire à long terme.
 *
 * @param {Array<{valeur: T, poids: number}>} candidats
 * @param {number} graine
 * @returns {T | null}
 * @template T
 */
export function tirerPondere(candidats, graine) {
  const valides = candidats.filter((c) => c.poids > 0);

  if (valides.length === 0) {
    return null;
  }

  const total = valides.reduce((somme, c) => somme + c.poids, 0);
  let curseur = generateur(graine)() * total;

  for (const candidat of valides) {
    curseur -= candidat.poids;

    if (curseur < 0) {
      return candidat.valeur;
    }
  }

  // Atteignable seulement par une erreur d'arrondi sur le dernier élément.
  return valides[valides.length - 1].valeur;
}
