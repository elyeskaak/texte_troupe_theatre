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

import { CONFIG } from './config.js';
import { repliques as toutesLesRepliques } from './schema.js';
import { contient, derniersMots } from './texte.js';

/**
 * Un des noms de `personnages` est-il un des miens ?
 *
 * Centralise la seule subtilité du champ : `JOKER_TOUS` (« TOUS. » dans le
 * texte) ne nomme personne et vaut pourtant pour n'importe quel rôle choisi.
 * Sans ce point unique, chaque appelant devrait réinventer le cas particulier
 * — et l'oublier serait invisible tant qu'aucune pièce ne contient de réplique
 * collective.
 *
 * @param {string[]} personnages
 * @param {Set<string>} ensemble - mes rôles, ou le rôle actif
 */
export function estMienne(personnages, ensemble) {
  return (
    personnages.includes(CONFIG.JOKER_TOUS) ||
    personnages.some((nom) => ensemble.has(nom))
  );
}

/**
 * Libellé affichable des locuteurs d'une réplique.
 *
 * @param {string[]} personnages
 */
export function libelleLocuteurs(personnages) {
  if (personnages.includes(CONFIG.JOKER_TOUS)) {
    return 'TOUS';
  }

  return personnages.join(' / ');
}

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
    mienne: estMienne(unite.personnages, miens),
    nbMesRepliques: _compterMesRepliques(unite, miens),
  }));

  const repliques = new Map();
  const ordreRepliques = [];
  const mesRepliques = [];

  for (const replique of toutesLesRepliques(piece)) {
    const mienne = estMienne(replique.personnages, miens);

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
    (element) => element.type === 'replique' && estMienne(element.personnages, miens),
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

      if (element.type !== 'replique' || !estMienne(element.personnages, miens)) {
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

  if (derniere && estMienne(derniere.personnages, miens)) {
    return { type: TOP.AUCUN, motif: MOTIF_SANS_TOP.ENCHAINEMENT };
  }

  const precedent = _premierSignalantAvant(elements, position);

  if (precedent === null) {
    return { type: TOP.AUCUN, motif: MOTIF_SANS_TOP.DEBUT };
  }

  if (precedent.type === 'replique') {
    return {
      type: TOP.REPLIQUE,
      personnages: precedent.personnages,
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
 * @returns {Array<{id: string, unite: string, personnages: string[], texte: string}>}
 */
export function chercher(index, fragment) {
  const resultats = [];

  for (const id of index.ordreRepliques) {
    const replique = index.repliques.get(id);

    if (contient(replique.texte, fragment)) {
      resultats.push({
        id,
        unite: replique.unite,
        personnages: replique.personnages,
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
  /** Sue, mais la maîtrise a expiré : à revoir avant de la considérer acquise. */
  A_REVISER: 'a_reviser',
  MAITRISEE: 'maitrisee',
});

/**
 * Ordre de mérite, du moins au mieux su.
 *
 * `A_REVISER` se place **au-dessus** d'`EN_COURS` : une réplique sue trois fois
 * puis oubliée n'est pas au même point qu'une réplique jamais réussie. La
 * distinction compte pour le bilan, où l'une demande une révision et l'autre un
 * apprentissage.
 */
const ORDRE_STATUTS = [
  STATUT.A_APPRENDRE,
  STATUT.EN_COURS,
  STATUT.A_REVISER,
  STATUT.MAITRISEE,
];

const JOUR = 86400000;

/**
 * Déduit le statut d'une réplique de son historique de récitations.
 *
 * **Le statut n'est plus déclaré, il est mérité.** Cocher « su » à la main
 * mesurait la confiance, pas la mémoire — et la confiance est précisément ce qui
 * trompe. Ici, seul le micro fait avancer une réplique.
 *
 * La règle, en quatre temps :
 *
 * 1. **Une réussite** est une récitation à `SEUIL_REUSSITE` % ou plus, ou une
 *    récitation que j'ai validée à la main.
 * 2. **Sue** à partir de `REUSSITES_POUR_MAITRISE` réussites **consécutives**, à
 *    condition que la dernière soit assez récente.
 * 3. **Un échec rompt la série.** Une réplique sue trois fois puis ratée n'est
 *    plus sue : c'est la dernière récitation qui dit où en est la mémoire, pas la
 *    moyenne d'un passé flatteur. Il faut refaire les trois réussites.
 * 4. **Répétition espacée** : l'échéance croît avec la longueur de la série,
 *    selon `INTERVALLES_REVISION_JOURS`. Passé ce délai, la réplique devient
 *    `A_REVISER` — sue autrefois, à revoir maintenant.
 *
 * `A_REVISER` est un statut distinct d'`EN_COURS`, et c'est le point qui compte :
 * une réplique sue trois fois puis oubliée ne demande pas le même travail qu'une
 * réplique jamais réussie. Les confondre ferait réapprendre ce qu'il suffit de
 * rafraîchir.
 *
 * @param {{scores?: Array<{le: number, score: number}>}} suivi
 * @param {number} maintenant - horodatage, passé en argument pour rester pur
 * @param {object} reglages - `seuil`, `reussitesPourMaitrise`, `intervallesJours`
 */
export function statutDepuisScores(suivi, maintenant, reglages) {
  const { seuil, reussitesPourMaitrise, intervallesJours } = reglages;
  const scores = _parDateDecroissante(suivi);

  if (scores.length === 0) {
    return STATUT.A_APPRENDRE;
  }

  const serie = _serieDeReussites(scores, seuil);
  const dejaSue =
    scores.filter((entree) => _estReussite(entree, seuil)).length >=
    reussitesPourMaitrise;

  if (serie >= reussitesPourMaitrise) {
    const echeance = scores[0].le + _intervalle(serie, reglages) * JOUR;

    return maintenant <= echeance ? STATUT.MAITRISEE : STATUT.A_REVISER;
  }

  // La série est rompue. Distinguer ce qui a déjà été su de ce qui ne l'a jamais
  // été est le point utile : l'un se rafraîchit, l'autre s'apprend.
  return dejaSue ? STATUT.A_REVISER : STATUT.EN_COURS;
}

/** Entrées d'historique, la plus récente d'abord. */
function _parDateDecroissante(suivi) {
  return (Array.isArray(suivi?.scores) ? suivi.scores : [])
    .filter((entree) => entree !== null && typeof entree === 'object')
    .slice()
    .sort((a, b) => b.le - a.le);
}

/**
 * Réussites consécutives, en remontant depuis la plus récente.
 *
 * **C'est la série qui compte, non le total**, et cette distinction porte toute
 * la règle. Un échec rompt la série : une réplique sue trois fois puis ratée
 * n'est plus sue, quel que soit son passé. C'est aussi ce qui empêche une seule
 * réussite après un échec de restaurer instantanément une maîtrise — il faut
 * refaire le chemin.
 */
function _serieDeReussites(scoresTriesDesc, seuil) {
  let serie = 0;

  for (const entree of scoresTriesDesc) {
    if (!_estReussite(entree, seuil)) {
      return serie;
    }

    serie += 1;
  }

  return serie;
}

/**
 * Jours de validité d'une maîtrise, selon la longueur de la série.
 *
 * L'intervalle croît avec les réussites consécutives, puis plafonne : une pièce
 * se joue dans l'année, pas dans dix ans.
 */
function _intervalle(serie, { reussitesPourMaitrise, intervallesJours }) {
  const rang = Math.min(serie - reussitesPourMaitrise, intervallesJours.length - 1);

  return intervallesJours[Math.max(0, rang)];
}

/**
 * Cette récitation compte-t-elle comme réussie ?
 *
 * Deux façons de l'être, et la seconde existe parce que la transcription vocale
 * n'est pas fiable. Une élision avalée, un nom propre écorché par le moteur de
 * Safari, et une récitation parfaite est notée 70 %. Refuser d'en tenir compte
 * ferait mesurer la qualité de la transcription, non celle de la mémoire.
 *
 * `corrige: true` marque une entrée que j'ai validée à la main **sans effacer le
 * score mesuré**. L'historique conserve donc les deux informations : ce que
 * l'outil a entendu, et ce que j'ai jugé. Écrire 100 % à la place aurait été
 * plus simple et aurait détruit la trace.
 */
function _estReussite(entree, seuil) {
  if (entree === null || typeof entree !== 'object') {
    return false;
  }

  if (entree.corrige === true) {
    return true;
  }

  return typeof entree.score === 'number' && entree.score >= seuil;
}

/**
 * Valide à la main la récitation la plus récente.
 *
 * Ne touche ni au score mesuré ni aux entrées antérieures : elle ajoute un
 * drapeau sur la dernière, et sur elle seule. Idempotente.
 *
 * @returns {object} le suivi mis à jour, sans modifier l'original
 */
export function corrigerDerniereRecitation(suivi) {
  const scores = [...(suivi?.scores ?? [])].sort((a, b) => b.le - a.le);

  if (scores.length === 0) {
    return { ...suivi };
  }

  scores[0] = { ...scores[0], corrige: true };

  return { ...suivi, scores };
}

/**
 * Date de la prochaine révision, ou `null` si la réplique n'est pas encore sue.
 *
 * Sert à l'affichage : savoir *quand* une réplique redemandera du travail vaut
 * mieux que de la voir basculer sans prévenir.
 */
export function prochaineRevision(suivi, reglages) {
  const { seuil, reussitesPourMaitrise } = reglages;
  const scores = _parDateDecroissante(suivi);
  const serie = _serieDeReussites(scores, seuil);

  if (serie < reussitesPourMaitrise) {
    return null;
  }

  return scores[0].le + _intervalle(serie, reglages) * JOUR;
}

/**
 * Ajoute un score à l'historique d'une réplique.
 *
 * Les plus anciens sont sacrifiés au plafond, jamais le dernier obtenu : c'est
 * l'historique récent qui décide du statut.
 *
 * @returns {object} le suivi mis à jour, sans modifier l'original
 */
export function ajouterScore(suivi, score, maintenant, plafond) {
  const scores = [...(suivi?.scores ?? []), { le: maintenant, score }]
    .sort((a, b) => b.le - a.le)
    .slice(0, plafond);

  return { ...suivi, scores, verifiee_le: maintenant };
}

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
    if (element.type !== 'replique' || !estMienne(element.personnages, miens)) {
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
 * Réglages du calcul de difficulté.
 *
 * Exportés pour que les tests et l'interface parlent des mêmes nombres, et pour
 * qu'ils se corrigent en un seul endroit.
 */
export const REVISION = Object.freeze({
  /**
   * Au-delà de cet âge, une réplique est « aussi vieille que possible ».
   *
   * Sans plafond, une réplique vue il y a un an écraserait tout le reste et la
   * file ne parlerait plus que d'ancienneté. Trente jours est l'horizon au-delà
   * duquel l'oubli est de toute façon acquis : distinguer 40 de 300 jours
   * n'apprend plus rien.
   */
  HORIZON_JOURS: 30,

  /**
   * Un mauvais score compte plus que l'ancienneté.
   *
   * Le score est une **mesure directe** de la difficulté : je me suis trompé,
   * c'est un fait. L'ancienneté n'est qu'une **présomption** d'oubli, qui peut
   * être fausse — on n'oublie pas une réplique jouée cent fois. On pèse donc plus
   * lourdement ce que l'on sait que ce que l'on suppose.
   */
  POIDS_FAIBLESSE: 0.7,
  POIDS_ANCIENNETE: 0.3,
});

const JOUR_MS = 86400000;

/**
 * Difficulté d'une réplique, entre 0 (sue et fraîche) et 1 (au pire).
 *
 * Deux termes, et deux seulement, parce que ce sont les deux raisons qu'on a de
 * revoir une réplique : **je l'ai mal dite**, ou **il y a longtemps**.
 *
 * **Le score retenu est le plus récent, non la moyenne.** C'est la règle qui
 * gouverne déjà le statut : un échec récent défait une maîtrise. Une moyenne
 * absoudrait la faute d'hier au nom de trois réussites du mois dernier, alors que
 * c'est précisément la faute d'hier qu'il faut aller retravailler.
 *
 * **Jamais récitée vaut le maximum sur les deux termes**, donc 1. Ces répliques
 * passent devant celles qu'on récite mal, et c'est voulu : une réplique jamais
 * essayée est un trou noir, une réplique à 30 % est un chantier ouvert. Le premier
 * coûte plus cher en scène.
 *
 * @param {{scores?: Array<{le: number, score: number}>, verifiee_le?: number}} suivi
 * @param {number} maintenant - horodatage, injecté pour garder la fonction pure
 * @param {typeof REVISION} reglages
 * @returns {{difficulte: number, score: number|null, jours: number|null}}
 */
export function difficulte(suivi, maintenant, reglages = REVISION) {
  // `scores` est trié du plus récent au plus ancien par `ajouterScore`.
  const dernier = suivi?.scores?.[0] ?? null;
  const vueLe = suivi?.verifiee_le ?? dernier?.le ?? null;

  const score = dernier ? dernier.score : null;
  const jours =
    typeof vueLe === 'number' ? Math.max(0, (maintenant - vueLe) / JOUR_MS) : null;

  const faiblesse =
    score === null ? 1 : Math.min(1, Math.max(0, (100 - score) / 100));
  const anciennete = jours === null ? 1 : Math.min(1, jours / reglages.HORIZON_JOURS);

  return {
    difficulte:
      reglages.POIDS_FAIBLESSE * faiblesse + reglages.POIDS_ANCIENNETE * anciennete,
    score,
    jours,
  };
}

/**
 * Mes répliques, de la plus difficile à la moins difficile.
 *
 * Sert la file de révision : commencer par ce qui résiste, plutôt que de relire la
 * pièce du début à chaque fois — ce qui fait qu'on connaît très bien l'acte I et
 * mal le dernier.
 *
 * **L'ordre de jeu tranche les égalités.** Deux répliques d'égale difficulté
 * doivent sortir dans un ordre stable, sinon la file se réordonne à chaque
 * ouverture et l'on ne sait plus où l'on en était. `mesRepliques` étant déjà dans
 * l'ordre de la pièce, il suffit de ne pas le perdre : le tri de JS est stable
 * depuis ES2019, mais on l'assure explicitement par le rang — s'appuyer sur une
 * garantie qu'on n'énonce pas est le meilleur moyen de la voir disparaître au
 * prochain remaniement.
 *
 * @param {object} index
 * @param {Record<string, object>} progres
 * @param {number} maintenant
 * @param {{reglages?: typeof REVISION}} options
 * @returns {Array<{id: string, difficulte: number, score: number|null,
 *                  jours: number|null, statut: string}>}
 */
export function filePrioritaire(index, progres, maintenant, { reglages } = {}) {
  return index.mesRepliques
    .map((id, rang) => ({
      id,
      rang,
      statut: progres[id]?.statut ?? STATUT.A_APPRENDRE,
      ...difficulte(progres[id], maintenant, reglages),
    }))
    .sort((a, b) => b.difficulte - a.difficulte || a.rang - b.rang)
    .map(({ rang, ...reste }) => reste);
}

/**
 * Fusionne deux progressions — jamais d'écrasement.
 *
 * Appelée à l'import d'une sauvegarde. **L'import fusionne, il n'écrase pas** :
 * un import écrasant détruirait le travail fait sur l'appareil depuis l'export,
 * ce qui est exactement le geste qu'on ferait en croyant se protéger.
 *
 * Trois règles, une par champ :
 *
 * - `statut` : le **plus avancé** des deux l'emporte. Une réplique maîtrisée d'un
 *   côté et à apprendre de l'autre a bien été apprise une fois ;
 * - `scores` : **union** des deux historiques, dédoublonnée par date. Le cahier
 *   disait « l'historique le plus long gagne » ; l'union tient la même promesse
 *   et perd strictement moins ;
 * - `verifiee_le` : la date **la plus récente**.
 *
 * @param {Record<string, object>} local
 * @param {Record<string, object>} importe
 * @param {number} plafondScores - entrées d'historique conservées par réplique
 */
export function fusionnerProgres(local = {}, importe = {}, plafondScores = 10) {
  const resultat = {};

  for (const id of new Set([...Object.keys(local), ...Object.keys(importe)])) {
    resultat[id] = _fusionnerUne(local[id], importe[id], plafondScores);
  }

  return resultat;
}

function _fusionnerUne(a = {}, b = {}, plafondScores) {
  const fusion = {
    statut: _statutLePlusAvance(a.statut, b.statut),
    scores: _fusionnerScores(a.scores, b.scores, plafondScores),
  };

  const verifiee = Math.max(
    typeof a.verifiee_le === 'number' ? a.verifiee_le : -Infinity,
    typeof b.verifiee_le === 'number' ? b.verifiee_le : -Infinity,
  );

  if (Number.isFinite(verifiee)) {
    fusion.verifiee_le = verifiee;
  }

  return fusion;
}

function _statutLePlusAvance(...statuts) {
  let meilleur = 0;

  for (const statut of statuts) {
    const rang = ORDRE_STATUTS.indexOf(statut);

    if (rang > meilleur) {
      meilleur = rang;
    }
  }

  return ORDRE_STATUTS[meilleur];
}

function _fusionnerScores(a, b, plafond) {
  const parDate = new Map();

  for (const entree of [...(a ?? []), ...(b ?? [])]) {
    if (entree && typeof entree.le === 'number' && typeof entree.score === 'number') {
      parDate.set(entree.le, entree);
    }
  }

  // Les plus récents d'abord, puis on coupe : c'est l'historique ancien qu'on
  // sacrifie au plafond, jamais le dernier score obtenu.
  return [...parDate.values()].sort((x, y) => y.le - x.le).slice(0, plafond);
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
    [STATUT.A_REVISER]: 0,
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
