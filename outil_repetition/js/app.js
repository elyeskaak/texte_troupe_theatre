/**
 * Câblage de l'interface.
 *
 * Module **impur** avec `rendu.js` : c'est ici que vivent les écouteurs, le cycle
 * de vie et les appels au stockage. Toute la logique est ailleurs, dans les sept
 * modules purs.
 *
 * À l'étape 6 du plan, cette coque couvre l'accueil, le chargement d'une pièce et
 * le choix des rôles. L'écran de répétition proprement dit — les sept modes en
 * CSS, le top, le montage paresseux — arrive à l'étape 7 avec `rendu.js`.
 */

import { CONFIG } from './config.js';
import * as schema from './schema.js';
import * as modele from './modele.js';
import * as etatSession from './etat.js';
import { creerStockage, ErreurStockage, idDePiece } from './stockage.js';

const $ = (id) => document.getElementById(id);

const stockage = creerStockage();

/** État courant de l'application. */
let piece = null;
let index = null;
let etat = etatSession.etatInitial();

// ============================================================
// MESSAGES — P3 : rien n'échoue en silence
// ============================================================

function afficherMessage(idElement, texte, genre = 'erreur') {
  const element = $(idElement);

  element.textContent = texte;
  element.className = `message ${genre}`;
  element.hidden = false;
}

function effacerMessage(idElement) {
  $(idElement).hidden = true;
}

/**
 * Exécute une action de stockage en rendant ses échecs visibles.
 *
 * C'est le contraire exact du prototype, où chaque échec d'écriture était avalé
 * par un `catch` qui rendait `null` : le bouton « Sauvegarder » ne sauvegardait
 * rien, et rien ne le signalait.
 */
function avecStockage(action, idMessage) {
  try {
    return { ok: true, valeur: action() };
  } catch (erreur) {
    if (erreur instanceof ErreurStockage) {
      afficherMessage(idMessage, erreur.message);
    } else {
      afficherMessage(idMessage, `erreur inattendue : ${erreur.message}`);
      console.error(erreur);
    }

    return { ok: false };
  }
}

// ============================================================
// NAVIGATION ENTRE ÉCRANS
// ============================================================

const ECRANS = ['ecran-accueil', 'ecran-roles', 'ecran-repetition'];

function montrer(idEcran) {
  for (const id of ECRANS) {
    $(id).classList.toggle('active', id === idEcran);
  }

  window.scrollTo(0, 0);
}

// ============================================================
// BANDEAUX D'ÉTAT
// ============================================================

function rafraichirBandeaux() {
  if (!stockage.persistant()) {
    afficherMessage(
      'bandeau-stockage',
      'Le navigateur refuse d’enregistrer sur cet appareil : votre progression ' +
        'ne sera pas conservée après la fermeture. En navigation privée, ' +
        'ouvrez cette page dans un onglet normal.',
      'avertissement',
    );
  } else {
    effacerMessage('bandeau-stockage');
  }

  const jours = stockage.joursDepuisExport();

  if (jours !== null && jours >= CONFIG.JOURS_SANS_EXPORT_ALERTE) {
    afficherMessage(
      'bandeau-export',
      `Dernier export il y a ${Math.floor(jours)} jours. Safari efface les ` +
        'données après sept jours sans visite : exportez votre progression.',
      'avertissement',
    );
  } else {
    effacerMessage('bandeau-export');
  }
}

// ============================================================
// ACCUEIL — liste des pièces
// ============================================================

function rafraichirListePieces() {
  const liste = $('liste-pieces');
  const enregistrees = stockage.listerPieces();

  liste.innerHTML = '';
  $('bloc-pieces').hidden = enregistrees.length === 0;

  const parDate = [...enregistrees].sort(
    (a, b) => (b.enregistree_le ?? 0) - (a.enregistree_le ?? 0),
  );

  for (const entree of parDate) {
    liste.appendChild(carteDePiece(entree));
  }
}

function carteDePiece(entree) {
  const carte = document.createElement('div');
  carte.className = 'carte';

  const gauche = document.createElement('div');
  const titre = document.createElement('div');
  titre.className = 'titre';
  titre.textContent = entree.titre;

  const meta = document.createElement('div');
  meta.className = 'meta';
  meta.textContent = (entree.personnages ?? []).join(' · ') || 'aucun rôle parlant';

  gauche.append(titre, meta);

  const ouvrir = document.createElement('button');
  ouvrir.className = 'btn btn-fantome btn-mini';
  ouvrir.textContent = 'Ouvrir';
  ouvrir.addEventListener('click', () => ouvrirPiece(entree.id));

  const supprimer = document.createElement('button');
  supprimer.className = 'btn btn-danger btn-mini';
  supprimer.textContent = 'Retirer';
  supprimer.setAttribute('aria-label', `Retirer ${entree.titre}`);
  supprimer.addEventListener('click', () => {
    // Une pièce se recharge depuis outil_edition, mais sa progression non :
    // c'est pourquoi la suppression demande confirmation.
    const message =
      `Retirer « ${entree.titre} » de cet appareil ?\n\n` +
      'Sa progression et ses annotations seront perdues.';

    if (!window.confirm(message)) {
      return;
    }

    if (avecStockage(() => stockage.supprimerPiece(entree.id), 'message-accueil').ok) {
      rafraichirListePieces();
    }
  });

  const droite = document.createElement('div');
  droite.className = 'rangee';
  droite.append(ouvrir, supprimer);

  carte.append(gauche, droite);

  return carte;
}

// ============================================================
// CHARGEMENT D'UNE PIÈCE
// ============================================================

/**
 * Charge une pièce depuis son texte JSON.
 *
 * La validation précède **tout** enregistrement : un fichier non conforme ne doit
 * pas laisser de trace, sinon la liste des pièces se remplirait d'entrées
 * inouvrables.
 */
function chargerDepuisTexte(texte) {
  effacerMessage('message-accueil');

  let donnees;

  try {
    donnees = JSON.parse(texte);
  } catch (erreur) {
    afficherMessage(
      'message-accueil',
      `Ce n’est pas du JSON valide (${erreur.message}). Vérifiez que le fichier ` +
        'a été copié en entier.',
    );
    return;
  }

  const verdict = schema.valider(donnees);

  if (!verdict.valide) {
    afficherMessage('message-accueil', verdict.erreur);
    return;
  }

  const enregistrement = avecStockage(
    () => stockage.enregistrerPiece(verdict.piece),
    'message-accueil',
  );

  // Même si l'enregistrement échoue — mémoire pleine, navigation privée — la
  // pièce est utilisable pour la session en cours. P4 : la persistance est un
  // agrément, pas une condition.
  const id = enregistrement.ok ? enregistrement.valeur : idDePiece(verdict.piece.piece);

  $('saisie-piece').value = '';
  rafraichirListePieces();
  ouvrirPiece(id, verdict.piece);
}

function ouvrirPiece(id, dejaValidee = null) {
  const chargee = dejaValidee ?? stockage.lirePiece(id);

  if (!chargee) {
    afficherMessage(
      'message-accueil',
      'Cette pièce est introuvable sur l’appareil — elle a peut-être été effacée ' +
        'par le navigateur. Rechargez son fichier _REPET.json.',
    );
    rafraichirListePieces();
    return;
  }

  // Une pièce relue du stockage repasse par la validation : le navigateur a pu
  // tronquer la valeur, et un champ manquant se verrait sinon à la première
  // réplique affichée.
  const verdict = schema.valider(chargee);

  if (!verdict.valide) {
    afficherMessage(
      'message-accueil',
      `La pièce enregistrée est inutilisable : ${verdict.erreur}`,
    );
    return;
  }

  piece = verdict.piece;
  etat = etatSession.etatInitial({ pieceId: id, mesRoles: [] });

  preparerEcranRoles();
  montrer('ecran-roles');
}

// ============================================================
// CHOIX DES RÔLES
// ============================================================

function preparerEcranRoles() {
  effacerMessage('message-roles');

  $('titre-piece').textContent = piece.piece;
  $('resume-piece').textContent =
    `${piece.unites.length} scène(s) · ` +
    `${schema.repliques(piece).length} réplique(s) · ` +
    `${piece.personnages.length} rôle(s) parlant(s)`;

  const choix = $('choix-mes-roles');
  choix.innerHTML = '';

  for (const personnage of piece.personnages) {
    choix.appendChild(
      pastilleDeRole(personnage, () => basculerMonRole(personnage.nom)),
    );
  }

  rafraichirChoixDesRoles();
}

function pastilleDeRole(personnage, auClic) {
  const pastille = document.createElement('button');
  pastille.type = 'button';
  pastille.className = 'pastille';
  pastille.dataset.nom = personnage.nom;
  pastille.setAttribute('aria-pressed', 'false');

  const nom = document.createElement('span');
  nom.textContent = personnage.nom;

  const compte = document.createElement('span');
  compte.className = 'compte';
  compte.textContent = `${personnage.repliques} répl.`;

  pastille.append(nom, compte);
  pastille.addEventListener('click', auClic);

  return pastille;
}

function basculerMonRole(nom) {
  const dejaChoisis = new Set(etat.mesRoles);

  if (dejaChoisis.has(nom)) {
    dejaChoisis.delete(nom);
  } else {
    dejaChoisis.add(nom);
  }

  etat = etatSession.changerMesRoles(etat, [...dejaChoisis]);
  rafraichirChoixDesRoles();
}

function basculerRoleActif(nom) {
  const actifs = new Set(etat.roleActif);

  if (actifs.has(nom)) {
    actifs.delete(nom);
  } else {
    actifs.add(nom);
  }

  if (actifs.size === 0) {
    // L'invariant d'`etat.js` interdit un rôle actif vide : rien ne serait
    // masqué. On l'explique plutôt que de laisser l'exception remonter.
    afficherMessage(
      'message-roles',
      'Il faut au moins un rôle actif : sans lui, aucune réplique ne serait masquée.',
      'avertissement',
    );
    return;
  }

  effacerMessage('message-roles');
  etat = etatSession.changerRoleActif(etat, [...actifs]);
  rafraichirChoixDesRoles();
}

function rafraichirChoixDesRoles() {
  const miens = new Set(etat.mesRoles);

  for (const pastille of $('choix-mes-roles').children) {
    pastille.setAttribute('aria-pressed', String(miens.has(pastille.dataset.nom)));
  }

  // Le rôle actif ne se choisit que s'il y a un choix à faire : avec un seul
  // rôle, un second écran de sélection serait une formalité inutile.
  const plusieurs = etat.mesRoles.length > 1;
  $('bloc-role-actif').hidden = !plusieurs;

  if (plusieurs) {
    const actifs = new Set(etat.roleActif);
    const zone = $('choix-role-actif');
    zone.innerHTML = '';

    for (const nom of etat.mesRoles) {
      const personnage = piece.personnages.find((p) => p.nom === nom);
      const pastille = pastilleDeRole(personnage, () => basculerRoleActif(nom));

      pastille.setAttribute('aria-pressed', String(actifs.has(nom)));
      zone.appendChild(pastille);
    }
  }

  $('btn-commencer').disabled = etat.mesRoles.length === 0;
}

// ============================================================
// ÉCRAN DE RÉPÉTITION (coque de l'étape 6)
// ============================================================

function commencer() {
  index = modele.indexer(piece, etat.mesRoles);

  avecStockage(
    () =>
      stockage.ecrireSession({
        pieceId: etat.pieceId,
        mesRoles: etat.mesRoles,
        roleActif: etat.roleActif,
      }),
    'message-roles',
  );

  $('repetition-titre').textContent = piece.piece;
  $('repetition-surtitre').textContent = etat.roleActif.join(' & ');

  const miennes = index.unites.filter((u) => u.mienne).length;

  $('repetition-resume').textContent =
    `${index.mesRepliques.length} réplique(s) à apprendre, ` +
    `dans ${miennes} scène(s) sur ${index.unites.length}.`;

  remplirSommaire();
  montrer('ecran-repetition');
}

function remplirSommaire() {
  const liste = $('sommaire');
  liste.innerHTML = '';

  index.sommaire.forEach((entree) => {
    const ligne = document.createElement('li');

    const titre = document.createElement('span');

    // Une unité implicite est ouverte par un `***` : elle n'a pas de titre dans
    // le texte de l'auteur, et lui en inventer un afficherait une scène qui
    // n'existe pas. Elle se désigne donc comme la suite de la précédente.
    titre.textContent =
      entree.titre ?? `${entree.scene ?? entree.acte ?? 'Scène'} — suite`;

    const compte = document.createElement('span');

    if (entree.mienne) {
      compte.className = 'compte';
      compte.textContent = `${entree.nbMesRepliques} répl.`;
    } else {
      ligne.classList.add('absent');
      compte.textContent = 'absent';
    }

    ligne.append(titre, compte);
    liste.appendChild(ligne);
  });
}

// ============================================================
// EXPORT / IMPORT DE LA PROGRESSION
// ============================================================

function exporterProgression() {
  const sauvegarde = stockage.exporter();
  const nom = `repetition-progression-${new Date().toISOString().slice(0, 10)}.json`;

  const lien = document.createElement('a');
  lien.href = URL.createObjectURL(
    new Blob([JSON.stringify(sauvegarde, null, 2)], { type: 'application/json' }),
  );
  lien.download = nom;
  lien.click();
  URL.revokeObjectURL(lien.href);

  // La date n'est marquée qu'après la création du fichier : marquer d'abord
  // ferait croire à un export qui n'a pas eu lieu.
  avecStockage(() => stockage.marquerExport(), 'message-accueil');
  rafraichirBandeaux();

  afficherMessage('message-accueil', `Export enregistré sous « ${nom} ».`, 'succes');
}

function importerProgression(texte) {
  let donnees;

  try {
    donnees = JSON.parse(texte);
  } catch (erreur) {
    afficherMessage('message-accueil', `Sauvegarde illisible (${erreur.message}).`);
    return;
  }

  const resultat = avecStockage(() => stockage.importer(donnees), 'message-accueil');

  if (resultat.ok) {
    afficherMessage(
      'message-accueil',
      `Progression fusionnée : ${resultat.valeur.repliques} réplique(s) connues. ` +
        'Rien n’a été écrasé.',
      'succes',
    );
  }
}

// ============================================================
// LECTURE DE FICHIER
// ============================================================

function lireFichier(input, suite) {
  const fichier = input.files?.[0];

  if (!fichier) {
    return;
  }

  const lecteur = new FileReader();

  lecteur.onload = () => suite(String(lecteur.result));
  lecteur.onerror = () =>
    afficherMessage('message-accueil', 'La lecture du fichier a échoué.');
  lecteur.readAsText(fichier);

  // Remise à zéro : sans elle, réimporter le même fichier ne déclenche pas
  // `change` et l'interface paraît sourde.
  input.value = '';
}

// ============================================================
// ÉCOUTEURS
// ============================================================

$('btn-charger').addEventListener('click', () => {
  const texte = $('saisie-piece').value.trim();

  if (texte === '') {
    afficherMessage('message-accueil', 'Collez d’abord le contenu du fichier.');
    return;
  }

  chargerDepuisTexte(texte);
});

$('fichier-piece').addEventListener('change', (evenement) =>
  lireFichier(evenement.target, chargerDepuisTexte),
);

$('fichier-sauvegarde').addEventListener('change', (evenement) =>
  lireFichier(evenement.target, importerProgression),
);

$('btn-exporter').addEventListener('click', exporterProgression);
$('btn-commencer').addEventListener('click', commencer);
$('btn-retour-accueil').addEventListener('click', () => {
  rafraichirListePieces();
  montrer('ecran-accueil');
});
$('btn-retour-roles').addEventListener('click', () => montrer('ecran-roles'));

/**
 * Journal des erreurs inattendues.
 *
 * P3 : c'est ce qui aurait révélé le défaut `window.storage` en dix secondes au
 * lieu de le laisser vivre indéfiniment.
 */
window.addEventListener('error', (evenement) => {
  console.error('erreur non rattrapée', evenement.error ?? evenement.message);
});

window.addEventListener('unhandledrejection', (evenement) => {
  console.error('promesse rejetée', evenement.reason);
});

// ============================================================
// DÉMARRAGE
// ============================================================

rafraichirBandeaux();
rafraichirListePieces();
