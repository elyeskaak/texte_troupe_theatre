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

/**
 * Ce qu'il y a à faire quand un fichier est refusé.
 *
 * Un code, et non une phrase, pour que l'interface puisse **proposer le geste**
 * plutôt que le décrire. Un bouton qui purge le cache vaut mieux qu'un paragraphe
 * expliquant comment fouiller les réglages de Safari — et incomparablement mieux
 * que l'ancien message, qui conseillait de mettre la page à jour alors que le
 * service worker était précisément ce qui l'en empêchait.
 */
export const REMEDE = Object.freeze({
  /** Rien de particulier : le fichier est abîmé ou mal formé. */
  AUCUN: 'aucun',
  /** La page est en retard sur le fichier. Purger le cache et recharger. */
  PAGE_PERIMEE: 'page_perimee',
  /** Le fichier est en retard sur la page. Le régénérer depuis outil_edition. */
  FICHIER_PERIME: 'fichier_perime',
  /** Ce fichier ne vient pas d'outil_edition. */
  FICHIER_ETRANGER: 'fichier_etranger',
});

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

  const problemeDeVersion = _validerVersion(donnees.schema);

  if (problemeDeVersion) {
    return _refus(problemeDeVersion.erreur, problemeDeVersion.remede);
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

/** Numéro d'une version de schéma, ou `null` si la forme est inconnue. */
function _numeroDeSchema(schema) {
  const trouve = /^repetition\/(\d+)$/.exec(schema);

  return trouve ? Number(trouve[1]) : null;
}

/**
 * Contrôle la version du schéma.
 *
 * Une version **supérieure est refusée**, jamais interprétée au mieux : un champ
 * dont le sens a changé produirait sinon un outil qui fonctionne en apparence et
 * masque la mauvaise réplique.
 *
 * **Le message doit dire qui est en retard, et l'ancien ne le faisait pas.** Il
 * disait « Mettez la page à jour, ou régénérez le fichier » — les deux remèdes à
 * la fois, sans trancher, donc en laissant le lecteur choisir au hasard. Or les
 * deux sens ont des causes opposées :
 *
 * - **fichier plus récent que la page** : la page est périmée. Sur un téléphone,
 *   c'est presque toujours le service worker qui sert un ancien `config.js`, et
 *   « mettre la page à jour » est précisément ce que le cache empêche. Conseiller
 *   cette action était donc envoyer vers la seule chose qui ne pouvait pas
 *   marcher ;
 * - **fichier plus ancien que la page** : c'est le fichier qu'il faut régénérer,
 *   et vider le cache n'y changerait rien.
 *
 * Le remède est rendu sous forme de **code**, non de prose, pour que l'interface
 * puisse proposer le geste au lieu de le décrire — un bouton qui purge le cache
 * vaut mieux qu'un paragraphe expliquant comment fouiller les réglages de Safari.
 * Ce module reste pur : il nomme le remède, il ne l'applique pas.
 */
function _validerVersion(schema) {
  if (typeof schema !== 'string') {
    return {
      erreur: 'le champ « schema » est absent : ce fichier ne vient pas d’outil_edition.',
      remede: REMEDE.FICHIER_ETRANGER,
    };
  }

  if (schema === CONFIG.SCHEMA_ACCEPTE) {
    return null;
  }

  const duFichier = _numeroDeSchema(schema);
  const attendu = _numeroDeSchema(CONFIG.SCHEMA_ACCEPTE);

  if (duFichier === null || attendu === null) {
    return {
      erreur:
        `schéma « ${schema} » inconnu : cette page attend ` +
        `« ${CONFIG.SCHEMA_ACCEPTE} ». Ce fichier ne semble pas venir d’outil_edition.`,
      remede: REMEDE.FICHIER_ETRANGER,
    };
  }

  if (duFichier > attendu) {
    return {
      erreur:
        `Ce fichier est plus récent que cette page : il est au schéma « ${schema} », ` +
        `la page en est restée à « ${CONFIG.SCHEMA_ACCEPTE} ». C’est la page qui ` +
        'est en retard, pas le fichier — l’outil doit être mis à jour.',
      remede: REMEDE.PAGE_PERIMEE,
    };
  }

  return {
    erreur:
      `Ce fichier est plus ancien que cette page : il est au schéma « ${schema} », ` +
      `la page attend « ${CONFIG.SCHEMA_ACCEPTE} ». Régénérez-le depuis ` +
      'outil_edition ; rien ne peut être corrigé de ce côté-ci.',
    remede: REMEDE.FICHIER_PERIME,
  };
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

function _refus(erreur, remede = REMEDE.AUCUN) {
  return { valide: false, erreur, remede };
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
