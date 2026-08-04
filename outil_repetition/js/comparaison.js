/**
 * Comparaison d'une récitation au texte attendu.
 *
 * Module **pur**, et le plus délicat du lot : c'est ici qu'un score absurde se
 * fabrique sans rien casser de visible.
 *
 * Trois décisions gouvernent le résultat.
 *
 * **La normalisation passe par `texte.normaliser()`, des deux côtés.** La
 * transcription iOS rend un texte sans ponctuation, avec des apostrophes
 * typographiques et des nombres parfois en chiffres : comparer sans normaliser
 * donnerait un score proche de zéro sur une récitation parfaite.
 *
 * **Un oubli et un ajout adjacents forment une substitution.** Sans cette
 * fusion, « chaise » dit à la place de « chaire » compterait deux fautes au lieu
 * d'une, et le score chuterait deux fois plus vite que la mémoire ne défaille.
 *
 * **Les mots en trop pèsent sur le score.** Ce module a d'abord fait l'inverse,
 * au motif qu'un « eh bien » glissé n'est pas une faute de mémoire. À l'usage
 * c'était faux, et pour une raison qui n'a rien à voir avec le confort : au
 * théâtre, broder est une faute réelle. Un mot ajouté décale le rythme, mange le
 * top du partenaire, et se paie en répétition. Le score doit dire ce que dirait
 * un metteur en scène, non ce qui ménage l'amour-propre.
 *
 * Le dénominateur est donc le nombre de mots **jugés** : les attendus, plus les
 * ajoutés. Chaque écart compte une fois et une seule — un oubli, une
 * substitution ou un ajout. Réciter exactement le texte donne 100 %, et rien
 * d'autre ne le donne.
 *
 * La contrepartie est réelle : la transcription iOS insère parfois un mot
 * fantôme, et le score en souffre alors sans faute du récitant. C'est ce que le
 * bouton « c'était juste » existe pour rattraper, et c'est aussi pourquoi il
 * n'est pas un aveu de faiblesse mais une pièce du dispositif.
 */

import { CONFIG } from './config.js';
import {
  clePhonetique,
  estMot,
  motsNormalises,
  mots as decouperMots,
} from './texte.js';

/** États possibles d'un mot dans le résultat d'une comparaison. */
export const ETAT = Object.freeze({
  CORRECT: 'correct',
  OUBLIE: 'oublie',
  AJOUTE: 'ajoute',
  SUBSTITUE: 'substitue',
});

/**
 * Compare une récitation au texte attendu.
 *
 * @param {string} attendu - texte parlé de la réplique, didascalies exclues
 * @param {string} recite - transcription de la récitation
 * @returns {{
 *   score: number,
 *   attendus: number,
 *   corrects: number,
 *   ajoutes: number,
 *   juges: number,
 *   tronque: boolean,
 *   details: Array<{mot: string, etat: string, dit?: string}>
 * }}
 */
export function comparer(attendu, recite) {
  const attendusNormalises = motsNormalises(attendu);
  const recitesNormalises = motsNormalises(recite);

  // Correspondance mot normalisé → forme affichée, établie jeton par jeton.
  const formes = _formesAffichees(attendu, attendusNormalises.length);

  const limite = CONFIG.MOTS_MAX_ALIGNEMENT;
  const tronque =
    attendusNormalises.length > limite || recitesNormalises.length > limite;

  const gauche = attendusNormalises.slice(0, limite);
  const droite = recitesNormalises.slice(0, limite);

  if (gauche.length === 0) {
    // Rien à réciter, donc rien à scorer. Ne se produit pas sur un REPET.json
    // valide — `repet_export` n'écrit pas de réplique vide — mais un score de
    // 100 % sur du vide serait un mensonge commode.
    return {
      score: 0,
      attendus: 0,
      corrects: 0,
      ajoutes: 0,
      juges: 0,
      tronque,
      details: [],
    };
  }

  // La comparaison porte sur les **sons**, non sur les lettres. Réciter est un
  // acte parlé : la transcription convertit du son en texte, et son choix
  // d'orthographe n'est pas le mien. Entendre « L'eau » là où le texte porte
  // « Lo » n’est pas une faute de mémoire, c’est une décision du moteur de
  // Safari — la pénaliser revenait à noter la transcription.
  const operations = _fusionnerSubstitutions(
    _aligner(gauche.map(clePhonetique), droite.map(clePhonetique), droite),
  );

  const details = [];
  let corrects = 0;
  let ajoutes = 0;
  let index = 0;

  for (const operation of operations) {
    if (operation.etat === ETAT.AJOUTE) {
      ajoutes += 1;
      details.push({ mot: operation.dit, etat: ETAT.AJOUTE });
      continue;
    }

    const affiche = formes[index] ?? gauche[index];
    index += 1;

    if (operation.etat === ETAT.CORRECT) {
      corrects += 1;
      details.push({ mot: affiche, etat: ETAT.CORRECT });
    } else if (operation.etat === ETAT.SUBSTITUE) {
      details.push({ mot: affiche, etat: ETAT.SUBSTITUE, dit: operation.dit });
    } else {
      details.push({ mot: affiche, etat: ETAT.OUBLIE });
    }
  }

  // Les mots jugés : ceux du texte, plus ceux que j'ai ajoutés. Un ajout n'a pas
  // de place dans le texte, il s'en crée une — et le dénominateur doit la compter,
  // sinon broder resterait gratuit.
  const juges = gauche.length + ajoutes;

  return {
    score: Math.round((corrects / juges) * 100),
    attendus: gauche.length,
    corrects,
    ajoutes,
    juges,
    tronque,
    details,
  };
}

/**
 * Pour chaque mot normalisé, la forme du texte de l'auteur qui l'a produit.
 *
 * Une comparaison naïve suppose autant de mots des deux côtés, et cette
 * supposition est fausse trois fois :
 *
 * - la ponctuation détachée — le « ? » que le français fait précéder d'une
 *   espace — est un jeton affiché qui ne donne aucun mot normalisé ;
 * - un mot composé en donne **plusieurs** : « Hailsham-Brown » devient
 *   « hailsham brown » ;
 * - un nombre en chiffres aussi : « 203 » devient « deux cent trois ».
 *
 * La version précédente comparait les deux longueurs et, en cas d'écart,
 * renonçait à afficher le texte de l'auteur pour montrer sa forme normalisée —
 * en minuscules et sans accents. Comme l'écart survenait sur la plupart des
 * répliques françaises, le détail était presque toujours dégradé, et personne ne
 * pouvait le voir puisque le résultat restait plausible.
 *
 * Établir la correspondance jeton par jeton supprime le cas particulier : un mot
 * composé partiellement oublié montre alors sa forme d'origine deux fois, ce qui
 * est exact — chaque moitié a son propre verdict.
 *
 * @param {string} attendu
 * @param {number} attendus - nombre de mots normalisés, pour contrôle
 * @returns {string[]}
 */
function _formesAffichees(attendu, attendus) {
  const formes = [];

  for (const jeton of decouperMots(attendu).filter(estMot)) {
    const parts = Math.max(1, motsNormalises(jeton).length);

    for (let k = 0; k < parts; k += 1) {
      formes.push(jeton);
    }
  }

  // Un désaccord signifierait que la normalisation d'un jeton isolé diffère de
  // celle du texte entier. On renonce alors, plutôt que de surligner de travers.
  return formes.length === attendus ? formes : [];
}

/**
 * Aligne deux suites de mots par plus longue sous-séquence commune.
 *
 * Programmation dynamique classique. Le coût est quadratique, ce qui est sans
 * objet aux longueurs en jeu : une réplique fait quelques dizaines de mots, et
 * `CONFIG.MOTS_MAX_ALIGNEMENT` borne le cas pathologique d'une transcription
 * partie en boucle.
 *
 * @param {string[]} attendus
 * @param {string[]} recites
 * @returns {Array<{etat: string, dit?: string}>}
 */
/*
 * L'alignement porte sur les clés phonétiques, mais `dit` rapporte le mot
 * réellement transcrit : afficher « troi » à la place de « trois » n'aiderait
 * personne à comprendre ce qui a été entendu.
 */
function _aligner(attendus, recites, motsRecites = recites) {
  const n = attendus.length;
  const m = recites.length;

  // table[i][j] = longueur de la plus longue sous-séquence commune des suffixes.
  const table = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));

  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      table[i][j] =
        attendus[i] === recites[j]
          ? table[i + 1][j + 1] + 1
          : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }

  const operations = [];
  let i = 0;
  let j = 0;

  while (i < n && j < m) {
    if (attendus[i] === recites[j]) {
      operations.push({ etat: ETAT.CORRECT });
      i += 1;
      j += 1;
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      operations.push({ etat: ETAT.OUBLIE });
      i += 1;
    } else {
      operations.push({ etat: ETAT.AJOUTE, dit: motsRecites[j] ?? recites[j] });
      j += 1;
    }
  }

  while (i < n) {
    operations.push({ etat: ETAT.OUBLIE });
    i += 1;
  }

  while (j < m) {
    operations.push({ etat: ETAT.AJOUTE, dit: motsRecites[j] ?? recites[j] });
    j += 1;
  }

  return operations;
}

/**
 * Fusionne chaque couple oubli / ajout adjacent en une substitution.
 *
 * L'ordre des deux ne présume de rien : selon le chemin choisi dans la table
 * d'alignement, un mot substitué se présente tantôt comme « oublié puis
 * ajouté », tantôt l'inverse. Les deux sens sont donc traités.
 *
 * @param {Array<{etat: string, dit?: string}>} operations
 */
function _fusionnerSubstitutions(operations) {
  const resultat = [];

  for (let i = 0; i < operations.length; i += 1) {
    const courante = operations[i];
    const suivante = operations[i + 1];

    if (!suivante) {
      resultat.push(courante);
      continue;
    }

    const oubliPuisAjout =
      courante.etat === ETAT.OUBLIE && suivante.etat === ETAT.AJOUTE;
    const ajoutPuisOubli =
      courante.etat === ETAT.AJOUTE && suivante.etat === ETAT.OUBLIE;

    if (oubliPuisAjout || ajoutPuisOubli) {
      resultat.push({
        etat: ETAT.SUBSTITUE,
        dit: oubliPuisAjout ? suivante.dit : courante.dit,
      });
      i += 1;
      continue;
    }

    resultat.push(courante);
  }

  return resultat;
}
