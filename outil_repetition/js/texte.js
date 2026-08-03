/**
 * Normalisation et découpage du texte français.
 *
 * Module **pur**. C'est la brique la plus discrètement dangereuse du projet : une
 * normalisation approximative ne casse rien de visible, elle produit seulement
 * des scores de fidélité absurdes qu'on finit par ne plus regarder.
 *
 * Deux notions de « mot » cohabitent, et il ne faut pas les confondre :
 *
 * - `mots()` découpe le texte **tel qu'il est écrit**. C'est l'espace de mots de
 *   l'affichage : amorce, mots à trous, et les positions `avant_mot` des
 *   didascalies internes calculées par `repet_export.py`.
 * - `motsNormalises()` découpe le texte **normalisé**. C'est l'espace de mots de
 *   la comparaison avec une récitation.
 *
 * L'apostrophe est **conservée** par la normalisation, précisément pour que les
 * deux découpages comptent « t'attendais » comme un seul mot. La transformer en
 * espace ferait diverger les deux espaces, et les positions calculées en Python ne
 * désigneraient plus le bon mot à l'écran.
 */

/** Apostrophes typographiques, ramenées à l'apostrophe droite. */
const APOSTROPHES = /[’‘‛`´]/g;

/** Ponctuation retirée pour la comparaison. L'apostrophe n'en fait pas partie. */
const PONCTUATION = /[.,;:!?…«»"“”()[\]{}—–\-*]/g;

const ESPACES = /\s+/g;

/** Diacritiques, après décomposition Unicode. */
const DIACRITIQUES = /[̀-ͯ]/g;

/**
 * Retire les accents (« SCÈNE » → « SCENE »).
 *
 * @param {string} texte
 */
export function sansAccents(texte) {
  return texte.normalize('NFD').replace(DIACRITIQUES, '');
}

/**
 * Découpe un texte en mots, tel qu'il est écrit.
 *
 * Les retours à la ligne comptent comme des séparateurs, mais ne sont pas
 * perdus pour autant : c'est `lignes()` qui préserve la structure d'un vers.
 *
 * @param {string} texte
 * @returns {string[]}
 */
export function mots(texte) {
  return texte.split(ESPACES).filter((mot) => mot.length > 0);
}

/**
 * Lignes d'un texte, une par vers.
 *
 * @param {string} texte
 */
export function lignes(texte) {
  return texte.split('\n');
}

/**
 * Le jeton porte-t-il du texte à retenir ?
 *
 * Le français typographique place une espace avant `!`, `?`, `;` et `:` : le
 * découpage sur les espaces produit donc des jetons de pure ponctuation.
 * « Alors ? » compte deux jetons, dont un seul est un mot.
 *
 * Sans ce filtre, deux modes se dérèglent. Les mots à trous masquent un « ! »,
 * ce qui ne demande aucun effort de mémoire et gaspille un trou. Et l'amorce
 * « les trois premiers mots » n'en montre que deux dès qu'une ponctuation
 * s'intercale.
 *
 * @param {string} jeton
 */
export function estMot(jeton) {
  return /[\p{L}\p{N}]/u.test(jeton);
}

/**
 * Positions, dans `mots(texte)`, des jetons qui sont de vrais mots.
 *
 * Rend des positions plutôt que les mots eux-mêmes : le rendu a besoin de
 * retrouver le bon `<span>` pour y poser un trou.
 *
 * @param {string} texte
 * @returns {number[]}
 */
export function positionsDesMots(texte) {
  const positions = [];

  mots(texte).forEach((jeton, rang) => {
    if (estMot(jeton)) {
      positions.push(rang);
    }
  });

  return positions;
}

/**
 * Normalise un texte pour le comparer à une récitation.
 *
 * Appliquée au texte attendu **comme** au texte récité, par un chemin unique :
 * deux fonctions de normalisation finiraient par diverger au premier correctif.
 *
 * Ce que la transcription iOS impose de neutraliser : elle rend un texte sans
 * ponctuation, avec des apostrophes typographiques, et des nombres parfois en
 * chiffres.
 *
 * @param {string} texte
 */
export function normaliser(texte) {
  let resultat = texte.replace(APOSTROPHES, "'");

  resultat = sansAccents(resultat).toLowerCase();
  resultat = resultat.replace(PONCTUATION, ' ');
  resultat = resultat.replace(ESPACES, ' ').trim();

  return resultat
    .split(' ')
    .map((mot) => (/^\d+$/.test(mot) ? nombreEnMots(mot) : mot))
    .join(' ')
    .replace(ESPACES, ' ')
    .trim();
}

/**
 * Mots normalisés d'un texte.
 *
 * @param {string} texte
 */
export function motsNormalises(texte) {
  const normalise = normaliser(texte);

  return normalise.length === 0 ? [] : normalise.split(' ');
}

// ============================================================
// NOMBRES
// ============================================================

/**
 * Zéro à dix-neuf.
 *
 * La table va jusqu'à 19 et non 16, bien que « dix-sept » soit composé : les
 * dizaines irrégulières s'appuient dessus (« soixante-dix-sept » = soixante +
 * dix-sept, « quatre-vingt-dix-neuf » = quatre-vingt + dix-neuf). S'arrêter à
 * seize débordait de la table sur 17, 18, 19, 77 à 79 et 97 à 99.
 */
const PETITS = [
  'zero', 'un', 'deux', 'trois', 'quatre', 'cinq', 'six', 'sept', 'huit',
  'neuf', 'dix', 'onze', 'douze', 'treize', 'quatorze', 'quinze', 'seize',
  'dix-sept', 'dix-huit', 'dix-neuf',
];

const DIZAINES = {
  20: 'vingt',
  30: 'trente',
  40: 'quarante',
  50: 'cinquante',
  60: 'soixante',
};

/**
 * Écrit un nombre entier en mots français.
 *
 * **Limité à 0–999, et c'est assumé.** Au-delà, les chiffres sont rendus tels
 * quels. Le besoin réel est étroit : le texte de la pièce écrit ses nombres en
 * lettres (l'édition imprimée le fait), et c'est la *transcription vocale* qui
 * rend « 20 » quand on dit « vingt ». Les nombres ainsi prononcés dans un
 * dialogue dépassent rarement la centaine. Au-delà, la lecture est de surcroît
 * ambiguë — « 1789 » se dit « mille sept cent quatre-vingt-neuf » ou
 * « dix-sept cent quatre-vingt-neuf » — et deviner mal serait pire que de ne
 * rien faire : la comparaison signalerait alors un mot faux au lieu d'un mot
 * absent.
 *
 * @param {string|number} valeur
 * @returns {string}
 */
export function nombreEnMots(valeur) {
  const nombre = Number(valeur);

  if (!Number.isInteger(nombre) || nombre < 0 || nombre > 999) {
    return String(valeur);
  }

  if (nombre < 20) {
    return PETITS[nombre];
  }

  if (nombre < 100) {
    return _dizaines(nombre);
  }

  return _centaines(nombre);
}

function _dizaines(nombre) {
  const dizaine = Math.floor(nombre / 10) * 10;
  const unite = nombre % 10;

  // 70 à 79 et 90 à 99 se composent sur la dizaine inférieure : « soixante-dix »,
  // « quatre-vingt-dix-neuf ». C'est la particularité qui interdit une simple
  // table, et c'est là que la version précédente débordait de PETITS.
  if (dizaine === 70 || dizaine === 90) {
    const base = dizaine === 70 ? 'soixante' : 'quatre-vingt';

    return `${base}-${PETITS[10 + unite]}`;
  }

  if (dizaine === 80) {
    return unite === 0 ? 'quatre-vingts' : `quatre-vingt-${PETITS[unite]}`;
  }

  const nom = DIZAINES[dizaine];

  if (unite === 0) {
    return nom;
  }

  // « vingt et un », mais « vingt-deux ».
  if (unite === 1) {
    return `${nom} et un`;
  }

  return `${nom}-${PETITS[unite]}`;
}

function _centaines(nombre) {
  const centaine = Math.floor(nombre / 100);
  const reste = nombre % 100;

  // « cent » et non « un cent » ; « deux cents » mais « deux cent trois ».
  let debut;

  if (centaine === 1) {
    debut = 'cent';
  } else if (reste === 0) {
    debut = `${PETITS[centaine]} cents`;
  } else {
    debut = `${PETITS[centaine]} cent`;
  }

  return reste === 0 ? debut : `${debut} ${nombreEnMots(reste)}`;
}

// ============================================================
// EXTRAITS
// ============================================================

/**
 * Premiers mots d'un texte — le mode « amorce seule ».
 *
 * Compte les **mots**, pas les jetons : « Alors ? Vraiment ? Bien. » doit donner
 * trois mots, non « Alors ? Vraiment ». La ponctuation qui les accompagne est
 * néanmoins rendue, puisqu'elle fait partie du texte.
 *
 * @param {string} texte
 * @param {number} combien
 */
export function amorce(texte, combien) {
  const jetons = mots(texte);
  const positions = positionsDesMots(texte);

  if (positions.length === 0) {
    return '';
  }

  const dernier = positions[Math.min(combien, positions.length) - 1];

  return jetons.slice(0, dernier + 1).join(' ');
}

/**
 * L'amorce dévoilerait-elle toute la réplique ?
 *
 * Une réplique de trois mots ou moins n'a pas de suite à cacher : le mode
 * « amorce » l'afficherait en entier, sans rien demander à la mémoire. Le rendu
 * la masque alors complètement (§ mode amorce dans `index.html`).
 *
 * @param {string} texte
 * @param {number} combien - mots d'amorce
 */
export function amorceCouvreTout(texte, combien) {
  return positionsDesMots(texte).length <= combien;
}

/**
 * Derniers mots d'un texte — le top en affichage réduit.
 *
 * @param {string} texte
 * @param {number} combien
 */
export function derniersMots(texte, combien) {
  const tous = mots(texte);

  return tous.slice(Math.max(0, tous.length - combien)).join(' ');
}

/**
 * Suite de lettres : la première avec ses diacritiques, puis le reste.
 *
 * `\p{M}*` après la lettre initiale n'est pas une précaution vaine : si le texte
 * arrive en forme décomposée, « être » est `e` + accent circonflexe combinant.
 * Sans ce groupe, l'acronyme rendrait « e » au lieu de « ê » — une faute
 * invisible dans le code et bien visible à l'écran.
 */
const SUITE_DE_LETTRES = /(\p{L}\p{M}*)[\p{L}\p{M}]*/gu;

/**
 * Réduit chaque mot à son initiale — le mode « acronyme géant ».
 *
 * Tout ce qui n'est pas une lettre est **conservé tel quel** : ponctuation,
 * apostrophes, tirets, espaces et retours à la ligne. C'est ce qui fait
 * l'intérêt du mode : le squelette rythmique de la réplique reste lisible, et
 * c'est lui qui rappelle le texte.
 *
 *     « Ai-je ?... Oui... Comme moi... »  →  « A-j ?... O... C m... »
 *
 * L'apostrophe étant conservée, elle borne deux mots : « qu'elle » donne
 * « q'e ». C'est la seule lecture cohérente de la règle — préserver
 * l'apostrophe tout en ne gardant qu'une initiale pour l'ensemble donnerait
 * « q' », qui laisse une apostrophe pendante. Et l'élision est en pratique un
 * excellent rappel.
 *
 * La casse et les accents de l'initiale sont préservés : « Être » donne « Ê ».
 *
 * **Les chiffres sont conservés entiers**, faute d'initiale : « 20 » reste
 * « 20 ». Le cas est rare — l'édition imprimée écrit ses nombres en lettres —
 * et le préserver reste plus fidèle à la règle que d'inventer une troncature.
 *
 * @param {string} texte
 * @returns {string}
 */
export function acronyme(texte) {
  return texte.replace(SUITE_DE_LETTRES, '$1');
}

/**
 * Le texte contient-il le fragment cherché ? Recherche insensible à la casse et
 * aux accents.
 *
 * Passe par `normaliser()` pour que chercher « repondre » trouve
 * « répondre » — c'est le comportement attendu d'une recherche tapée au pouce
 * sur un clavier de téléphone.
 *
 * @param {string} texte
 * @param {string} fragment
 */
export function contient(texte, fragment) {
  const cherche = normaliser(fragment);

  if (cherche.length === 0) {
    return false;
  }

  return normaliser(texte).includes(cherche);
}
