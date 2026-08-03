/**
 * Persistance dans `localStorage`.
 *
 * Module **impur**, et le seul à toucher au stockage. Il est néanmoins testable
 * sans navigateur : le support est **injectable**, et les tests lui passent une
 * doublure en mémoire.
 *
 * Ce module existe en réaction directe à un défaut réel. Le prototype de cet
 * outil appelait `window.storage.get/set` — une API de bac à sable qui n'existe
 * pas dans un navigateur — entourée d'un `catch { return null }`. Chaque appel
 * échouait donc en silence : le bouton « Sauvegarder » ne sauvegardait rien, la
 * liste des pièces enregistrées ne s'affichait jamais, et rien ne le signalait.
 *
 * D'où deux règles, qui sont l'application du principe P3 :
 *
 * - **aucun `catch` ne rend `null`.** Une écriture qui échoue lève une
 *   `ErreurStockage` portant un message affichable ;
 * - **l'indisponibilité se détecte, elle ne se devine pas.** `disponible()` fait
 *   un aller-retour réel, parce que Safari en navigation privée expose bien un
 *   `localStorage` dont toute écriture échoue.
 */

import { CONFIG } from './config.js';
import { fusionnerProgres } from './modele.js';

/** Version du format d'export. Refusée si inconnue, jamais devinée. */
export const FORMAT_EXPORT = 'repetition-sauvegarde/1';

const P = CONFIG.PREFIXE_STOCKAGE;

/** Toutes les clés, en un seul endroit. */
export const CLE = Object.freeze({
  index: () => `${P}:index`,
  piece: (idPiece) => `${P}:piece:${idPiece}`,
  progres: (idPiece, personnage) => `${P}:progres:${idPiece}:${personnage}`,
  annotations: (idPiece) => `${P}:annotations:${idPiece}`,
  roles: (idPiece) => `${P}:roles:${idPiece}`,
  reglages: () => `${P}:reglages`,
  session: () => `${P}:session`,
  dernierExport: () => `${P}:dernier-export`,
});

/** Erreur de stockage, porteuse d'un message affichable tel quel. */
export class ErreurStockage extends Error {
  constructor(message, { saturee = false, cause = undefined } = {}) {
    super(message);
    this.name = 'ErreurStockage';
    this.saturee = saturee;
    this.cause = cause;
  }
}

/**
 * Identifiant stable d'une pièce, dérivé de son titre.
 *
 * Dérivé du titre et non tiré au hasard, pour une raison qui compte : réimporter
 * une pièce **rééditée** doit remplacer son texte tout en **conservant ses
 * annotations**, qui vivent sous une autre clé indexée par ce même identifiant
 * (§7.1). Un identifiant aléatoire créerait une seconde pièce et laisserait les
 * annotations orphelines.
 *
 * @param {string} titre
 */
export function idDePiece(titre) {
  const ascii = String(titre)
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');

  // Un titre entièrement non latin — ou vide — ne doit pas produire une clé
  // vide, qui collisionnerait avec toute autre pièce du même cas.
  return ascii || `piece-${_empreinte(String(titre))}`;
}

function _empreinte(texte) {
  let valeur = 0x811c9dc5;

  for (let i = 0; i < texte.length; i += 1) {
    valeur ^= texte.charCodeAt(i);
    valeur = Math.imul(valeur, 0x01000193);
  }

  return (valeur >>> 0).toString(36);
}

/**
 * Support en mémoire, conforme à l'interface de `localStorage`.
 *
 * Sert de repli quand le stockage du navigateur est absent ou refusé : l'outil
 * fonctionne alors normalement pour la session en cours, et l'interface annonce
 * que rien ne sera conservé. C'est le principe P4 — la progression est une donnée
 * d'agrément, sa perte n'empêche jamais de répéter.
 */
export function supportEnMemoire() {
  const donnees = new Map();

  return {
    enMemoire: true,
    get length() {
      return donnees.size;
    },
    key: (rang) => [...donnees.keys()][rang] ?? null,
    getItem: (cle) => (donnees.has(cle) ? donnees.get(cle) : null),
    setItem: (cle, valeur) => donnees.set(cle, String(valeur)),
    removeItem: (cle) => donnees.delete(cle),
  };
}

function _supportDuNavigateur() {
  try {
    const support = globalThis.localStorage;

    if (!support) {
      return null;
    }

    // Aller-retour réel : Safari en navigation privée expose un localStorage
    // dont toute écriture lève. Le tester par sa seule présence mentirait.
    const temoin = `${P}:témoin`;
    support.setItem(temoin, '1');
    support.removeItem(temoin);

    return support;
  } catch {
    return null;
  }
}

/**
 * Crée l'accès au stockage.
 *
 * @param {object} [support] - injecté par les tests ; `localStorage` par défaut,
 *   avec repli en mémoire s'il est absent ou refusé
 */
export function creerStockage(support = undefined) {
  const socle = support ?? _supportDuNavigateur() ?? supportEnMemoire();

  function lire(cle) {
    const brut = socle.getItem(cle);

    if (brut === null) {
      return null;
    }

    try {
      return JSON.parse(brut);
    } catch (erreur) {
      // Une valeur illisible est signalée, jamais silencieusement remplacée :
      // c'est le seul moyen de distinguer « rien d'enregistré » de « quelque
      // chose d'abîmé ».
      throw new ErreurStockage(
        `la valeur enregistrée sous « ${cle} » est illisible.`,
        { cause: erreur },
      );
    }
  }

  function ecrire(cle, valeur) {
    try {
      socle.setItem(cle, JSON.stringify(valeur));
    } catch (erreur) {
      const saturee = _estSaturation(erreur);

      throw new ErreurStockage(
        saturee
          ? 'la mémoire du navigateur est pleine. Exportez votre progression, ' +
            'puis supprimez une pièce dont vous n’avez plus besoin.'
          : `impossible d’enregistrer (${erreur?.message ?? erreur}).`,
        { saturee, cause: erreur },
      );
    }
  }

  function lireTolerant(cle, defaut) {
    try {
      return lire(cle) ?? defaut;
    } catch {
      // P4 : une donnée d'agrément abîmée ne doit pas empêcher de répéter. Le
      // défaut est rendu, et l'appelant reste libre de purger la clé.
      return defaut;
    }
  }

  return {
    /** Le stockage survivra-t-il à la fermeture de l'onglet ? */
    persistant: () => socle.enMemoire !== true,

    // --- pièces --------------------------------------------------
    listerPieces: () => lireTolerant(CLE.index(), []),

    /**
     * Enregistre une pièce validée.
     *
     * Le texte est écrit **une fois** sous sa propre clé et n'est jamais modifié
     * ensuite : un statut coché ne réécrit donc pas les 200 Ko de la pièce.
     */
    enregistrerPiece(piece) {
      const id = idDePiece(piece.piece);

      ecrire(CLE.piece(id), piece);

      const index = lireTolerant(CLE.index(), []).filter((e) => e.id !== id);

      index.push({
        id,
        titre: piece.piece,
        personnages: piece.personnages.map((p) => p.nom),
        enregistree_le: Date.now(),
      });

      ecrire(CLE.index(), index);

      return id;
    },

    lirePiece: (id) => lireTolerant(CLE.piece(id), null),

    supprimerPiece(id) {
      socle.removeItem(CLE.piece(id));
      socle.removeItem(CLE.annotations(id));
      socle.removeItem(CLE.roles(id));

      for (const cle of _clesCommencantPar(socle, `${P}:progres:${id}:`)) {
        socle.removeItem(cle);
      }

      ecrire(
        CLE.index(),
        lireTolerant(CLE.index(), []).filter((e) => e.id !== id),
      );
    },

    // --- progression ---------------------------------------------
    lireProgres: (id, personnage) =>
      lireTolerant(CLE.progres(id, personnage), {}),

    ecrireProgres(id, personnage, progres) {
      ecrire(CLE.progres(id, personnage), progres);
    },

    // --- annotations, réglages, session --------------------------
    /**
     * Rôles retenus pour une pièce.
     *
     * Rangés **par pièce**, et non dans la session : on répète Henry dans l'une et
     * Clarissa dans l'autre, et une clé unique ferait perdre le choix à chaque
     * changement de texte.
     */
    lireRoles: (id) => lireTolerant(CLE.roles(id), null),

    ecrireRoles(id, roles) {
      ecrire(CLE.roles(id), roles);
    },

    lireAnnotations: (id) => lireTolerant(CLE.annotations(id), {}),
    ecrireAnnotations(id, annotations) {
      ecrire(CLE.annotations(id), annotations);
    },

    lireReglages: () => lireTolerant(CLE.reglages(), null),
    ecrireReglages(reglages) {
      ecrire(CLE.reglages(), reglages);
    },

    lireSession: () => lireTolerant(CLE.session(), null),
    ecrireSession(session) {
      ecrire(CLE.session(), session);
    },

    // --- export / import -----------------------------------------
    /**
     * Sauvegarde de tout **sauf les pièces**.
     *
     * Un `REPET.json` est reproductible depuis `outil_edition` ; une progression
     * ne l'est pas. L'inclure gonflerait le fichier de plusieurs centaines de
     * kilo-octets de texte sous droits, pour rien.
     */
    exporter(maintenant = Date.now()) {
      const progres = {};

      for (const cle of _clesCommencantPar(socle, `${P}:progres:`)) {
        progres[cle.slice(`${P}:progres:`.length)] = lireTolerant(cle, {});
      }

      const annotations = {};

      for (const cle of _clesCommencantPar(socle, `${P}:annotations:`)) {
        annotations[cle.slice(`${P}:annotations:`.length)] = lireTolerant(cle, {});
      }

      return {
        format: FORMAT_EXPORT,
        exporte_le: maintenant,
        progres,
        annotations,
        reglages: lireTolerant(CLE.reglages(), null),
      };
    },

    /**
     * Importe une sauvegarde, en **fusionnant**.
     *
     * Écraser détruirait le travail fait sur l'appareil depuis l'export — le
     * geste même qu'on ferait en croyant se protéger. Voir
     * `modele.fusionnerProgres`.
     */
    importer(donnees) {
      if (donnees?.format !== FORMAT_EXPORT) {
        throw new ErreurStockage(
          `format de sauvegarde non reconnu : « ${donnees?.format ?? '(absent)'} ». ` +
            `Cette page attend « ${FORMAT_EXPORT} ».`,
        );
      }

      let repliques = 0;

      for (const [suffixe, importe] of Object.entries(donnees.progres ?? {})) {
        const cle = `${P}:progres:${suffixe}`;
        const fusion = fusionnerProgres(
          lireTolerant(cle, {}),
          importe,
          CONFIG.SCORES_PAR_REPLIQUE,
        );

        ecrire(cle, fusion);
        repliques += Object.keys(fusion).length;
      }

      for (const [id, importees] of Object.entries(donnees.annotations ?? {})) {
        const cle = `${P}:annotations:${id}`;

        // Les annotations locales gagnent : elles ont été écrites plus tard, et
        // une note de jeu perdue est plus contrariante qu'une note en double.
        ecrire(cle, { ...importees, ...lireTolerant(cle, {}) });
      }

      return { repliques };
    },

    marquerExport(maintenant = Date.now()) {
      ecrire(CLE.dernierExport(), maintenant);
    },

    dernierExport: () => lireTolerant(CLE.dernierExport(), null),

    /**
     * Jours écoulés depuis le dernier export, `null` s'il n'y en a jamais eu.
     *
     * Safari purge le stockage après sept jours d'inactivité :
     * `CONFIG.JOURS_SANS_EXPORT_ALERTE` vaut 5, parce qu'alerter le jour de
     * l'échéance serait alerter trop tard.
     */
    joursDepuisExport(maintenant = Date.now()) {
      const date = lireTolerant(CLE.dernierExport(), null);

      if (typeof date !== 'number') {
        return null;
      }

      return Math.max(0, (maintenant - date) / 86400000);
    },
  };
}

function _estSaturation(erreur) {
  if (!erreur) {
    return false;
  }

  // Safari lève `QuotaExceededError`, les autres moteurs varient, et certaines
  // versions ne renseignent que le code numérique 22.
  return (
    erreur.name === 'QuotaExceededError' ||
    erreur.name === 'NS_ERROR_DOM_QUOTA_REACHED' ||
    erreur.code === 22
  );
}

function _clesCommencantPar(socle, prefixe) {
  const trouvees = [];

  for (let rang = 0; rang < socle.length; rang += 1) {
    const cle = socle.key(rang);

    if (typeof cle === 'string' && cle.startsWith(prefixe)) {
      trouvees.push(cle);
    }
  }

  return trouvees;
}
