/**
 * Construction du DOM.
 *
 * Module **impur** : le seul du projet à toucher au document. Une erreur
 * d'affichage ne peut donc se trouver qu'ici.
 *
 * Deux principes gouvernent tout le module.
 *
 * **Le masquage est du CSS.** Une réplique est montée une seule fois, découpée de
 * façon à ce que les sept modes soient exprimables en règles. Changer de mode, de
 * rôle actif ou replier les scènes coûte une écriture d'attribut — jamais un
 * re-rendu. C'est ce que le prototype faisait à l'envers : `renderScript()`
 * vidait et reconstruisait tout le DOM à chaque bascule.
 *
 * **Le DOM est borné.** Une pièce de trois actes fait 1200 répliques ; les monter
 * toutes ferait des dizaines de milliers de nœuds sur un téléphone. L'unité
 * jouable est l'unité de montage, et au-delà de `UNITES_MONTEES_MAX` les plus
 * lointaines sont démontées, leur hauteur remplacée par une cale pour ne pas
 * faire sauter le défilement.
 */

import { CONFIG } from './config.js';
import { acronyme, amorce as premiersMots, derniersMots, mots } from './texte.js';
import { graineReplique, motsAMasquer } from './tirage.js';
import { MOTIF_SANS_TOP, TOP } from './modele.js';

/** Feuille de style dédiée au rôle actif, réécrite sans reconstruire le DOM. */
let feuilleRoleActif = null;

/**
 * Déclare quelles répliques sont celles du rôle actif.
 *
 * Une seule règle CSS injectée, plutôt qu'un parcours du DOM pour poser une
 * classe : changer de rôle actif reste ainsi une opération à coût constant, même
 * sur une pièce entière.
 *
 * @param {string[]} roles
 */
export function declarerRoleActif(roles) {
  if (feuilleRoleActif === null) {
    feuilleRoleActif = document.createElement('style');
    document.head.appendChild(feuilleRoleActif);
  }

  if (roles.length === 0) {
    feuilleRoleActif.textContent = '';
    return;
  }

  const selecteurs = roles
    .map((role) => `.replique[data-perso="${_echapper(role)}"]`)
    .join(',');

  feuilleRoleActif.textContent = `${selecteurs}{--actif:1}\n${selecteurs}{}`;

  // La classe `.actif` reste nécessaire : CSS ne permet pas de sélectionner sur
  // une variable personnalisée. On la pose donc, mais seulement sur les nœuds
  // montés — soit au plus quelques centaines.
  const attendus = new Set(roles);

  for (const replique of document.querySelectorAll('.replique')) {
    replique.classList.toggle('actif', attendus.has(replique.dataset.perso));
  }
}

function _echapper(valeur) {
  return String(valeur).replace(/["\\]/g, '\\$&');
}

// ============================================================
// MONTAGE D'UNE UNITÉ
// ============================================================

/**
 * Construit le DOM d'une unité jouable.
 *
 * @param {object} unite - entrée de `index.unites`
 * @param {object} contexte
 * @param {object} contexte.index - index de `modele.indexer`
 * @param {object} contexte.etat - état de session
 * @returns {HTMLElement}
 */
export function monterUnite(unite, { index, etat }) {
  const bloc = document.createElement('section');
  bloc.className = 'unite';
  bloc.dataset.id = unite.id;
  bloc.classList.toggle('mienne', unite.mienne);

  bloc.appendChild(_enTeteUnite(unite));

  const contenu = document.createElement('div');
  contenu.className = 'elements';

  // Les nœuds sont conservés dans l'ordre des éléments : la passe de marquage
  // des tops en a besoin, et elle ne peut pas se faire pendant la construction
  // puisqu'un top se trouve *avant* la réplique qui le désigne.
  const noeuds = unite.elements.map((element) =>
    _monterElement(element, { index, etat }),
  );

  for (const noeud of noeuds) {
    contenu.appendChild(noeud);
  }

  _marquerTops(unite, noeuds, index, etat);

  bloc.appendChild(contenu);

  return bloc;
}

function _enTeteUnite(unite) {
  const entete = document.createElement('header');
  entete.className = 'entete-unite';

  const titre = document.createElement('h2');

  // Une unité implicite est ouverte par un `***` : elle n'a pas de titre dans le
  // texte de l'auteur, et lui en inventer un afficherait une scène qui n'existe
  // pas.
  titre.textContent = unite.implicite
    ? `${unite.scene ?? unite.acte ?? 'Scène'} — suite`
    : (unite.scene ?? unite.acte ?? 'Scène');

  const marque = document.createElement('span');
  marque.className = 'marque-unite';
  marque.textContent = unite.mienne
    ? `${unite.nbMesRepliques} répl.`
    : 'absent';

  entete.append(titre, marque);

  // Une scène où je n'apparais pas se déplie au doigt : la replier ne doit pas
  // la rendre inaccessible.
  entete.addEventListener('click', () => {
    entete.parentElement.classList.toggle('depliee');
  });

  return entete;
}

function _monterElement(element, { index, etat }) {
  if (element.type === 'replique') {
    return _monterReplique(element, { index, etat });
  }

  const bloc = document.createElement('p');
  bloc.className = `element ${element.type}`;
  bloc.textContent = element.texte;

  return bloc;
}

/**
 * Monte une réplique.
 *
 * Les répliques des **autres** reçoivent une structure minimale : elles ne sont
 * jamais masquées, donc ni découpage en mots, ni acronyme. C'est ce qui garde le
 * DOM raisonnable, mes répliques ne représentant qu'une part de la pièce.
 */
function _monterReplique(replique, { index, etat }) {
  const bloc = document.createElement('div');
  bloc.className = 'element replique';
  bloc.dataset.id = replique.id;
  bloc.dataset.perso = replique.personnage;

  const mienne = index.repliques.get(replique.id)?.mienne ?? false;
  bloc.classList.toggle('mienne', mienne);
  bloc.classList.toggle('actif', etat.roleActif.includes(replique.personnage));

  const qui = document.createElement('div');
  qui.className = 'qui';

  // Le nom n'est **jamais** masqué : je joue plusieurs rôles, et un bloc anonyme
  // rendrait illisible une scène entre deux de mes personnages.
  qui.textContent = replique.personnage;
  bloc.appendChild(qui);

  const texte = document.createElement('div');
  texte.className = 'texte';

  if (!mienne) {
    texte.textContent = replique.texte;
    bloc.appendChild(texte);

    return bloc;
  }

  texte.appendChild(_formePleine(replique, etat));
  texte.appendChild(_formeAcronyme(replique));
  bloc.appendChild(texte);

  const rideau = document.createElement('button');
  rideau.type = 'button';
  rideau.className = 'rideau';
  rideau.textContent = 'toucher pour révéler';
  bloc.appendChild(rideau);

  return bloc;
}

/**
 * Forme complète : mots individualisés, amorce séparée de la suite.
 *
 * Ce découpage sert **trois** modes d'un coup — amorce seule, mots à trous, et
 * les deux masquages complets — sans qu'aucun ne demande de re-rendu.
 */
function _formePleine(replique, etat) {
  const plein = document.createElement('span');
  plein.className = 'plein';

  const listeMots = mots(replique.texte);
  const trous = new Set(
    motsAMasquer(
      listeMots.length,
      etat.difficulte,
      graineReplique(replique.id, etat.difficulte, etat.passageTrous),
    ),
  );

  // Positions des jeux de scène, en nombre de mots parlés qui les précèdent.
  const jeux = new Map();

  for (const didascalie of replique.didascalies_internes ?? []) {
    if (!jeux.has(didascalie.avant_mot)) {
      jeux.set(didascalie.avant_mot, []);
    }

    jeux.get(didascalie.avant_mot).push(didascalie.texte);
  }

  const amorce = document.createElement('span');
  amorce.className = 'amorce';

  const suite = document.createElement('span');
  suite.className = 'suite';

  const nbAmorce = Math.min(CONFIG.MOTS_AMORCE, listeMots.length);

  // Le texte d'origine est parcouru caractère par mot afin de conserver ses
  // séparateurs : un vers doit garder ses retours à la ligne, et les espaces
  // multiples portent le rythme (§ mode acronyme).
  let reste = replique.texte;

  listeMots.forEach((mot, rang) => {
    const cible = rang < nbAmorce ? amorce : suite;
    const position = reste.indexOf(mot);
    const separateur = reste.slice(0, position);

    if (separateur) {
      cible.appendChild(document.createTextNode(separateur));
    }

    reste = reste.slice(position + mot.length);

    for (const jeu of jeux.get(rang) ?? []) {
      cible.appendChild(_jeuDeScene(jeu));
    }

    const noeud = document.createElement('span');
    noeud.className = 'mot';
    noeud.textContent = mot;

    if (trous.has(rang)) {
      noeud.dataset.trou = '1';
    }

    cible.appendChild(noeud);
  });

  // Un jeu de scène en fin de réplique porte l'index du dernier mot + 1.
  for (const jeu of jeux.get(listeMots.length) ?? []) {
    suite.appendChild(_jeuDeScene(jeu));
  }

  if (reste) {
    suite.appendChild(document.createTextNode(reste));
  }

  plein.append(amorce, suite);

  return plein;
}

function _jeuDeScene(texte) {
  const noeud = document.createElement('span');
  noeud.className = 'jeu';
  noeud.textContent = `(${texte})`;

  return noeud;
}

/**
 * Forme réduite aux initiales — le mode « acronyme géant ».
 *
 * Calculée **une fois, au montage**, et montée à côté de la forme pleine. Aucune
 * règle CSS ne réduit un mot à son initiale : c'est le seul mode qui change le
 * contenu, et monter les deux formes est ce qui lui permet de rester un simple
 * échange d'attribut.
 */
function _formeAcronyme(replique) {
  const noeud = document.createElement('span');
  noeud.className = 'acronyme';
  noeud.textContent = acronyme(replique.texte);

  return noeud;
}

// ============================================================
// LE TOP
// ============================================================

function _marquerTops(unite, noeuds, index, etat) {
  const actifs = new Set(etat.roleActif);

  unite.elements.forEach((element, rang) => {
    if (element.type !== 'replique' || !actifs.has(element.personnage)) {
      return;
    }

    const top = index.tops.get(element.id);

    if (!top) {
      return;
    }

    if (top.type === TOP.AUCUN) {
      // « Enchaînement » est une information utile, pas une absence de donnée :
      // afficher un encadré vide ferait attendre un signal qui ne viendra pas.
      noeuds[rang].dataset.sansTop =
        top.motif === MOTIF_SANS_TOP.DEBUT ? 'debut' : 'enchainement';
      return;
    }

    const rangDuTop = _rangDuTop(unite.elements, rang, top);

    if (rangDuTop === null) {
      return;
    }

    const noeud = noeuds[rangDuTop];
    noeud.classList.add('top');

    // Version courte, pour le réglage « n'afficher que les derniers mots ».
    if (!noeud.querySelector('.top-court')) {
      const court = document.createElement('span');
      court.className = 'top-court';
      court.textContent = derniersMots(top.texte, CONFIG.MOTS_TOP);
      noeud.appendChild(court);
    }
  });
}

/**
 * Retrouve la position du top dans les éléments de l'unité.
 *
 * `modele.tops` rend le **contenu** du top, pas sa position : l'index est calculé
 * une fois pour toute la pièce, alors que les positions n'ont de sens qu'à
 * l'intérieur d'une unité. On remonte donc jusqu'à lui, en sautant ce qui ne
 * signale rien — exactement comme `modele._topDe` l'avait fait.
 */
function _rangDuTop(elements, rangReplique, top) {
  for (let i = rangReplique - 1; i >= 0; i -= 1) {
    const element = elements[i];

    if (top.type === TOP.REPLIQUE && element.id === top.id) {
      return i;
    }

    if (
      top.type === TOP.DIDASCALIE &&
      element.type === 'didascalie' &&
      element.texte === top.texte
    ) {
      return i;
    }
  }

  return null;
}

// ============================================================
// PRÉSENTATION — tout se joue en attributs
// ============================================================

/**
 * Applique le mode, les réglages et le repli des scènes.
 *
 * **Aucun nœud n'est reconstruit.** C'est la promesse du §6 de l'architecture, et
 * la raison pour laquelle tout le découpage précédent existe.
 *
 * @param {HTMLElement} racine
 * @param {object} etat
 */
export function appliquerPresentation(racine, etat) {
  racine.dataset.mode = etat.mode;
  racine.dataset.mesScenes = etat.mesScenesSeules ? '1' : '0';
  racine.dataset.topReduit = etat.reglages.topReduit ? '1' : '0';

  racine.style.setProperty('--taille-texte', `${etat.reglages.taillePolice}rem`);
}

/**
 * Met à jour les mots masqués après un changement de difficulté.
 *
 * Seuls les attributs `data-trou` des répliques **montées** changent : quelques
 * centaines d'écritures au pire, contre un re-rendu complet dans le prototype.
 *
 * @param {HTMLElement} racine
 * @param {object} etat
 */
export function rafraichirTrous(racine, etat) {
  for (const replique of racine.querySelectorAll('.replique.mienne')) {
    const noeuds = replique.querySelectorAll('.mot');
    const trous = new Set(
      motsAMasquer(
        noeuds.length,
        etat.difficulte,
        graineReplique(replique.dataset.id, etat.difficulte, etat.passageTrous),
      ),
    );

    noeuds.forEach((noeud, rang) => {
      if (trous.has(rang)) {
        noeud.dataset.trou = '1';
      } else {
        delete noeud.dataset.trou;
      }
    });
  }
}

/**
 * Reflète l'ensemble des répliques révélées.
 *
 * Efface aussi les **mots** dévoilés un à un en mode trous, sur toute réplique
 * qui n'est pas révélée. Les mots dévoilés vivent dans le DOM et non dans l'état :
 * ils sont volatils par nature, et `etat.revelees` étant vidé à chaque changement
 * de mode, cette fonction suffit à les remettre en place au bon moment. Sans
 * cela, revenir au mode trous retrouverait les mots dévoilés d'avant.
 */
export function appliquerRevelations(racine, etat) {
  const revelees = new Set(etat.revelees);

  for (const replique of racine.querySelectorAll('.replique.mienne')) {
    const revelee = revelees.has(replique.dataset.id);

    replique.classList.toggle('revelee', revelee);

    if (!revelee) {
      for (const mot of replique.querySelectorAll('.mot.devoile')) {
        mot.classList.remove('devoile');
      }
    }
  }
}
