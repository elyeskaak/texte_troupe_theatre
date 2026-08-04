/**
 * Validation d'un `REPET.json`.
 *
 * Module **pur**. Il porte à lui seul le principe P3 (« aucune erreur
 * silencieuse ») à l'entrée du système : un fichier non conforme est **refusé
 * avant tout chargement**, avec un message nommant le champ fautif — jamais
 * accepté puis interprété au mieux.
 *
 * Un `REPET.json` est produit par une machine, `repet_export.py`, et non tapé à
 * la main. Le rôle de cette validation n'est donc pas de rattraper une faute de
 * frappe, c'est de détecter une **désynchronisation de version** entre les deux
 * outils, ou un fichier tronqué par un transfert. Ces deux cas se manifestent
 * exactement comme un champ manquant.
 */

import { CONFIG } from './config.js';

/** Types d'élément reconnus dans une unité jouable. */
export const TYPES_ELEMENT = Object.freeze([
  'replique',
  'didascalie',
  'lieu',
  'texte_sans_personnage',
]);

/**
 * Valide un objet issu de `JSON.parse`.
 *
 * @param {unknown} donnees
 * @returns {{valide: true, piece: object} | {valide: false, erreur: string}}
 */
export function valider(donnees) {
  if (donnees === null || typeof donnees !== 'object' || Array.isArray(donnees)) {
    return _refus('le fichier ne contient pas un objet JSON.');
  }

  const erreurDeVersion = _validerVersion(donnees.schema);

  if (erreurDeVersion) {
    return _refus(erreurDeVersion);
  }

  if (typeof donnees.piece !== 'string' || donnees.piece.trim() === '') {
    return _refus('le champ « piece » est absent ou vide.');
  }

  if (!Array.isArray(donnees.unites) || donnees.unites.length === 0) {
    return _refus('le champ « unites » est absent ou vide : aucun texte à répéter.');
  }

  if (!Array.isArray(donnees.personnages)) {
    return _refus('le champ « personnages » est absent.');
  }

  for (let i = 0; i < donnees.unites.length; i += 1) {
    const erreur = _validerUnite(donnees.unites[i], i);

    if (erreur) {
      return _refus(erreur);
    }
  }

  const erreurDeCoherence = _validerCoherence(donnees);

  if (erreurDeCoherence) {
    return _refus(erreurDeCoherence);
  }

  return { valide: true, piece: donnees };
}

/**
 * Contrôle la version du schéma.
 *
 * Une version **supérieure est refusée**, jamais interprétée au mieux : un champ
 * dont le sens a changé produirait sinon un outil qui fonctionne en apparence et
 * masque la mauvaise réplique. Le message dit quoi faire, parce que la cause est
 * toujours la même — un `outil_edition` plus récent que la page.
 */
function _validerVersion(schema) {
  if (typeof schema !== 'string') {
    return 'le champ « schema » est absent : ce fichier ne vient pas d’outil_edition.';
  }

  if (schema === CONFIG.SCHEMA_ACCEPTE) {
    return null;
  }

  return (
    `schéma « ${schema} » non reconnu — cette page attend ` +
    `« ${CONFIG.SCHEMA_ACCEPTE} ». Mettez la page à jour, ou régénérez le ` +
    'fichier avec la version d’outil_edition correspondante.'
  );
}

function _validerUnite(unite, position) {
  const ou = `unité ${position + 1}`;

  if (unite === null || typeof unite !== 'object' || Array.isArray(unite)) {
    return `${ou} : ce n’est pas un objet.`;
  }

  if (typeof unite.id !== 'string' || unite.id === '') {
    return `${ou} : champ « id » absent.`;
  }

  if (!Array.isArray(unite.personnages)) {
    return `${ou} (${unite.id}) : champ « personnages » absent.`;
  }

  if (!Array.isArray(unite.elements)) {
    return `${ou} (${unite.id}) : champ « elements » absent.`;
  }

  for (let i = 0; i < unite.elements.length; i += 1) {
    const erreur = _validerElement(unite.elements[i], `${ou} (${unite.id})`, i);

    if (erreur) {
      return erreur;
    }
  }

  return null;
}

function _validerElement(element, ou, position) {
  const situe = `${ou}, élément ${position + 1}`;

  if (element === null || typeof element !== 'object' || Array.isArray(element)) {
    return `${situe} : ce n’est pas un objet.`;
  }

  if (typeof element.type !== 'string') {
    return `${situe} : champ « type » absent.`;
  }

  if (!TYPES_ELEMENT.includes(element.type)) {
    return `${situe} : type « ${element.type} » inconnu.`;
  }

  if (element.type !== 'replique') {
    return typeof element.texte === 'string'
      ? null
      : `${situe} : champ « texte » absent.`;
  }

  for (const champ of ['id', 'texte']) {
    if (typeof element[champ] !== 'string' || element[champ] === '') {
      return `${situe} : réplique sans « ${champ} ».`;
    }
  }

  const erreurPersonnages = _validerPersonnagesDeReplique(element, situe);

  if (erreurPersonnages) {
    return erreurPersonnages;
  }

  return _validerDidascaliesInternes(element, situe);
}

/**
 * Une réplique peut être dite par plusieurs personnages : « personnages » est
 * donc une liste, jamais vide et jamais un nom seul en dehors d'une liste.
 */
function _validerPersonnagesDeReplique(element, situe) {
  if (!Array.isArray(element.personnages) || element.personnages.length === 0) {
    return `${situe} : réplique sans « personnages ».`;
  }

  for (const nom of element.personnages) {
    if (typeof nom !== 'string' || nom === '') {
      return `${situe} : « personnages » contient un nom vide.`;
    }
  }

  return null;
}

function _validerDidascaliesInternes(replique, situe) {
  if (replique.didascalies_internes === undefined) {
    return null;
  }

  if (!Array.isArray(replique.didascalies_internes)) {
    return `${situe} : « didascalies_internes » n’est pas une liste.`;
  }

  for (const didascalie of replique.didascalies_internes) {
    if (
      didascalie === null ||
      typeof didascalie !== 'object' ||
      typeof didascalie.texte !== 'string' ||
      !Number.isInteger(didascalie.avant_mot) ||
      didascalie.avant_mot < 0
    ) {
      return `${situe} : didascalie interne mal formée.`;
    }
  }

  return null;
}

/**
 * Contrôles qui portent sur l'ensemble du document.
 *
 * Deux identifiants de réplique identiques seraient le pire défaut possible :
 * les statuts, annotations et scores étant indexés par identifiant, deux
 * répliques homonymes partageraient silencieusement une progression. C'est
 * exactement ce que le suffixe d'occurrence de `repet_export` évite — et donc
 * exactement ce qu'il faut vérifier ici.
 */
function _validerCoherence(donnees) {
  const vus = new Set();

  for (const unite of donnees.unites) {
    for (const element of unite.elements) {
      if (element.type !== 'replique') {
        continue;
      }

      if (vus.has(element.id)) {
        return (
          `identifiant de réplique en double : « ${element.id} ». ` +
          'Deux répliques partageraient la même progression.'
        );
      }

      vus.add(element.id);
    }
  }

  if (vus.size === 0) {
    return 'aucune réplique dans le fichier : rien à répéter.';
  }

  return null;
}

function _refus(erreur) {
  return { valide: false, erreur };
}

/**
 * Répliques de la pièce, dans l'ordre de jeu, chacune sachant d'où elle vient.
 *
 * Fourni ici plutôt que dans `modele.js` parce que la validation vient de
 * parcourir la même structure : c'est le seul endroit du code qui connaît déjà
 * la forme exacte du fichier.
 *
 * Le paramètre s'appelle `piece` et non `document` : dans une page web,
 * `document` est un global du navigateur, et le masquer dans une fonction est
 * une source de confusion — c'est aussi ce qui faisait échouer le contrôle de
 * pureté, à juste titre.
 *
 * @param {object} piece
 */
export function repliques(piece) {
  const resultat = [];

  for (const unite of piece.unites) {
    for (const element of unite.elements) {
      if (element.type === 'replique') {
        resultat.push({ ...element, unite: unite.id });
      }
    }
  }

  return resultat;
}
