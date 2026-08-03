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
import * as rendu from './rendu.js';
import * as voix from './voix.js';
import { comparer } from './comparaison.js';
import { graineDepuis, tirerPondere } from './tirage.js';
import { creerStockage, ErreurStockage, idDePiece } from './stockage.js';

const $ = (id) => document.getElementById(id);

const stockage = creerStockage();

/** État courant de l'application. */
let piece = null;
let index = null;
let etat = etatSession.etatInitial();

/**
 * Progression et annotations de la session.
 *
 * La progression est indexée **par personnage actif** : le cahier exige que rien
 * ne soit partagé entre deux de mes rôles. Elle est donc rechargée quand le rôle
 * actif change (`chargerProgression`).
 */
let progres = {};
let annotations = {};

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

const ECRANS = ['ecran-accueil', 'ecran-roles', 'ecran-repetition', 'ecran-bilan'];

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

  // Le titre du REPET.json porte déjà « Auteur - Nom de la pièce » : la liste
  // des personnages en dessous n'ajoutait rien et occupait deux lignes par pièce.
  gauche.append(titre);

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
// ÉCRAN DE RÉPÉTITION
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

  $('repetition-surtitre').textContent =
    `${piece.piece} — ${etat.roleActif.join(' & ')}`;

  const miennes = index.unites.filter((u) => u.mienne).length;

  $('repetition-resume').textContent =
    `${index.mesRepliques.length} réplique(s) à apprendre, ` +
    `dans ${miennes} scène(s) sur ${index.unites.length}.`;

  // L'écran est montré **avant** de construire le squelette. Ce n'est pas
  // cosmétique : tant que la section est en `display:none`, ses cales ont une
  // hauteur nulle, l'`IntersectionObserver` ne voit rien d'intersectant, et
  // aucune unité ne se monte jamais. Le texte restait vide.
  montrer('ecran-repetition');

  chargerProgression();
  recalculerStatuts();
  monterToutLeTexte();
  rendu.declarerRoleActif(etat.roleActif);
  rendu.appliquerProgression($('app'), index, progres, annotations);
  appliquer();
  synchroniserCommandes();

  // On ouvre sur la première scène où j'ai du texte, plutôt qu'au début d'une
  // pièce où je n'entre qu'au deuxième acte.
  const premiere = index.unites.find((u) => u.mienne) ?? index.unites[0];

  if (premiere) {
    etat = etatSession.allerA(etat, { unite: premiere.id });
    document
      .querySelector(`.unite[data-id="${premiere.id}"]`)
      ?.scrollIntoView({ block: 'start' });
  }
}

/**
 * Monte toutes les unités de la pièce.
 *
 * **Un montage paresseux a été écrit, mesuré, puis retiré.** La conception le
 * prévoyait (§6.4), et l'expérience a montré que le remède coûtait plus que le
 * mal. Le principe était d'occuper la place d'une unité par une cale de hauteur
 * estimée, puis de la remplacer par le texte à l'approche. Trois défauts en sont
 * sortis, chacun réparable et le troisième insoluble sans mesure préalable :
 *
 * 1. l'ensemble monté partait en va-et-vient dès que la portée dépassait le
 *    plafond — deux groupes alternant à position de défilement fixe ;
 * 2. l'éviction par ancienneté sacrifiait des unités à l'écran ; il fallait
 *    évincer par distance ;
 * 3. **une cale ne fait jamais la hauteur du bloc qui la remplace.** La page se
 *    contractait à chaque montage, ce qui amenait d'autres cales dans la portée,
 *    et le contenu glissait sous une position inchangée.
 *
 * Or la mesure dit que le problème n'existait pas : « La toile d'araignée », trois
 * actes et 1196 répliques, tient dans quelques mégaoctets de mémoire JavaScript.
 * Un iPhone 15 en dispose largement. Le montage paresseux protégeait donc d'un
 * coût imaginaire, au prix de trois défauts réels et d'une classe entière de bugs
 * de position.
 *
 * À reprendre si une pièce se révélait un jour trop lourde — et alors avec des
 * hauteurs mesurées d'abord, jamais estimées.
 */
function monterToutLeTexte() {
  const contenant = $('texte-piece');
  const fragment = document.createDocumentFragment();

  for (const unite of index.unites) {
    const bloc = rendu.monterUnite(unite, { index, etat });

    cablerInteractions(bloc);
    appliquerMessagesSansTop(bloc);
    fragment.appendChild(bloc);
  }

  // Un seul rattachement au document : construire dans un fragment évite autant
  // de recalculs de mise en page qu'il y a d'unités.
  contenant.innerHTML = '';
  contenant.appendChild(fragment);
}

/**
 * Un seul écouteur par unité, par délégation.
 *
 * Poser un écouteur sur chaque mot d'une pièce en ferait des dizaines de
 * milliers.
 */
function cablerInteractions(bloc) {
  bloc.addEventListener('click', (evenement) => {
    const replique = evenement.target.closest('.replique.actif');

    if (!replique) {
      return;
    }

    // Les outils sont captés d'abord : sans cela le clic remonterait et
    // révélerait la réplique qu'on s'apprête justement à réciter de mémoire, ou
    // dont on voulait seulement cocher le statut.
    if (evenement.target.closest('.valider-recitation')) {
      evenement.stopPropagation();
      validerRecitation(replique.dataset.id);
      return;
    }

    if (evenement.target.closest('.reciter')) {
      evenement.stopPropagation();
      basculerRecitation(replique);
      return;
    }

    if (evenement.target.closest('.noter')) {
      evenement.stopPropagation();
      annoter(replique.dataset.id);
      return;
    }

    // En mode trous, un clic sur un trou ne dévoile que ce mot : c'est
    // l'exigence « révélables un à un ». Cliquer ailleurs révèle la réplique
    // entière.
    if (etat.mode === etatSession.MODE.TROUS) {
      const mot = evenement.target.closest('.mot[data-trou]');

      if (mot) {
        // Basculer, et non seulement dévoiler : on retouche le mot pour se
        // retester sans quitter la réplique.
        mot.classList.toggle('devoile');
        return;
      }
    }

    etat = etatSession.basculerRevelation(etat, replique.dataset.id);
    replique.classList.toggle(
      'revelee',
      etatSession.estRevelee(etat, replique.dataset.id),
    );
  });

  // Au clavier, pour la même action : la réplique porte `role="button"`.
  bloc.addEventListener('keydown', (evenement) => {
    if (evenement.key !== 'Enter' && evenement.key !== ' ') {
      return;
    }

    const replique = evenement.target.closest('.replique.actif');

    if (replique) {
      evenement.preventDefault();
      etat = etatSession.basculerRevelation(etat, replique.dataset.id);
      replique.classList.toggle(
        'revelee',
        etatSession.estRevelee(etat, replique.dataset.id),
      );
    }
  });
}

/**
 * Renseigne le message d'absence de top.
 *
 * Le texte vit dans un attribut, affiché par une règle `::before` : il ne peut
 * donc être ni sélectionné, ni copié, ni confondu avec du texte de la pièce.
 */
function appliquerMessagesSansTop(bloc) {
  for (const replique of bloc.querySelectorAll('.replique[data-sans-top]')) {
    replique.dataset.messageSansTop =
      replique.dataset.sansTop === 'debut'
        ? 'ouvre la scène — pas de top'
        : 'enchaînement — pas de top';
  }
}

// ============================================================
// COMMANDES DE RÉPÉTITION
// ============================================================

function appliquer() {
  rendu.appliquerPresentation($('app'), etat);
  rendu.appliquerRevelations($('app'), etat);
}

function synchroniserCommandes() {
  for (const pastille of $('choix-mode').children) {
    pastille.setAttribute('aria-pressed', String(pastille.dataset.mode === etat.mode));
  }


  $('bloc-difficulte').hidden = etat.mode !== etatSession.MODE.TROUS;
  $('curseur-difficulte').value = String(etat.difficulte);
  $('valeur-difficulte').textContent = String(etat.difficulte);
  $('btn-mes-scenes').setAttribute('aria-pressed', String(etat.mesScenesSeules));
  $('btn-top-court').setAttribute('aria-pressed', String(etat.reglages.topReduit));
}

function enregistrerReglages() {
  // Un réglage non conservé est un désagrément, pas une panne (P4). L'échec est
  // néanmoins affiché, jamais avalé.
  avecStockage(
    () => stockage.ecrireReglages(etatSession.partiePersistante(etat)),
    'bandeau-stockage',
  );
}

/** Amène à ma réplique suivante ou précédente, en montant son unité au besoin. */
function allerAReplique(sens) {
  const cible = modele.repliqueVoisine(index, etat.repliqueCourante, sens);

  if (cible === null) {
    return;
  }

  etat = etatSession.allerA(etat, { replique: cible });

  // L'écoute appartient à la réplique qu'on vient de quitter.
  reconnaissance.arreter();

  document
    .querySelector(`.replique[data-id="${cible}"]`)
    ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
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

  if (!resultat.ok) {
    return;
  }

  afficherMessage(
    'message-accueil',
    `Progression fusionnée : ${resultat.valeur.repliques} réplique(s) connues. ` +
      'Rien n’a été écrasé.',
    'succes',
  );

  // L'import a modifié le stockage : sans rechargement, l'écran continuerait
  // d'afficher les statuts d'avant, et l'import paraîtrait sans effet.
  if (index !== null) {
    chargerProgression();
    rendu.appliquerProgression($('app'), index, progres, annotations);
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

// --- commandes de répétition ---------------------------------

for (const pastille of $('choix-mode').children) {
  pastille.addEventListener('click', () => {
    etat = etatSession.changerMode(etat, pastille.dataset.mode);
    appliquer();
    synchroniserCommandes();
    enregistrerReglages();
  });
}

$('curseur-difficulte').addEventListener('input', (evenement) => {
  etat = etatSession.changerDifficulte(etat, Number(evenement.target.value));
  $('valeur-difficulte').textContent = String(etat.difficulte);

  // Seuls les attributs des répliques montées changent : aucun nœud n'est
  // reconstruit, même en glissant le curseur d'un bout à l'autre.
  rendu.rafraichirTrous($('app'), etat);
});

$('curseur-difficulte').addEventListener('change', enregistrerReglages);

$('btn-nouveau-tirage').addEventListener('click', () => {
  etat = etatSession.nouveauTirage(etat);
  rendu.rafraichirTrous($('app'), etat);
  enregistrerReglages();
});

$('btn-mes-scenes').addEventListener('click', () => {
  etat = etatSession.basculerMesScenesSeules(etat);
  appliquer();
  synchroniserCommandes();
  enregistrerReglages();
});

$('btn-top-court').addEventListener('click', () => {
  etat = etatSession.changerReglage(etat, 'topReduit', !etat.reglages.topReduit);
  appliquer();
  synchroniserCommandes();
  enregistrerReglages();
});

$('btn-tout-remasquer').addEventListener('click', () => {
  etat = etatSession.toutRemasquer(etat);
  appliquer();
});

$('btn-top-suivant').addEventListener('click', () => allerAReplique(1));
$('btn-top-precedent').addEventListener('click', () => allerAReplique(-1));

// --- bandeau repliable ---------------------------------------
// Replié, il tient sur une ligne et laisse tout l'écran au texte. L'état n'est
// pas persisté : on le replie pour une session de récitation, pas pour toujours.
$('btn-barre').addEventListener('click', () => {
  const barre = $('barre');
  const ouverte = barre.dataset.ouverte === '1';

  barre.dataset.ouverte = ouverte ? '0' : '1';
  $('btn-barre').textContent = ouverte ? 'Réglages' : 'Réduire';
  $('btn-barre').setAttribute('aria-expanded', String(!ouverte));
});

// --- récitation contrôlée ------------------------------------

/** Réplique dont la récitation est en cours d'écoute, s'il y en a une. */
let repliqueEcoutee = null;

function messageMicro(texte) {
  $('message-micro').textContent = texte;
  $('message-micro').hidden = texte === '';
}

/**
 * Contrôleur de reconnaissance, unique pour la session.
 *
 * Les rappels visent `repliqueEcoutee` : c'est ce qui tient la règle « une
 * réplique à la fois » du §8.1, sans quoi une transcription tardive viendrait se
 * poser sous la mauvaise réplique.
 */
const reconnaissance = voix.creerReconnaissance(
  {
    surDecompte: (secondes) => {
      if (repliqueEcoutee) {
        rendu.afficherEtatControle(
          repliqueEcoutee,
          secondes > 0 ? `à vous dans ${secondes}…` : 'je vous écoute',
        );
      }
    },
    surIntermediaire: (texte) => {
      if (repliqueEcoutee) {
        rendu.afficherEtatControle(repliqueEcoutee, `« ${texte} »`);
      }
    },
    surTranscription: (texte) => {
      if (!repliqueEcoutee) {
        return;
      }

      const id = repliqueEcoutee.dataset.id;
      const attendu = index.repliques.get(id)?.texte ?? '';
      const resultat = comparer(attendu, texte);

      rendu.afficherComparaison(repliqueEcoutee, resultat, CONFIG.SEUIL_REUSSITE);
      rendu.afficherEtatControle(repliqueEcoutee, '');

      // Le score entre dans l'historique, et c'est lui — et lui seul — qui fait
      // avancer le statut. Voir `modele.statutDepuisScores`.
      enregistrerScore(id, resultat.score);
    },
    surEchec: (motif) => {
      // Un échec est un non-événement : aucun score, aucune modale. Le message
      // reste dans le bandeau d'aide, et la réplique garde son bouton.
      messageMicro(voix.MESSAGES[motif] ?? 'La reconnaissance vocale a échoué.');

      if (repliqueEcoutee) {
        rendu.afficherEtatControle(repliqueEcoutee, '');
      }
    },
    surFin: () => {
      if (repliqueEcoutee) {
        repliqueEcoutee.querySelector('.reciter').textContent = '🎙 Réciter';
        repliqueEcoutee = null;
      }
    },
  },
  {
    langue: CONFIG.LANGUE_RECONNAISSANCE,
    delaiAvantEcouteMs: CONFIG.DELAI_AVANT_ECOUTE_MS,
    ecouteMaxMs: CONFIG.ECOUTE_MAX_MS,
  },
);

function basculerRecitation(replique) {
  if (repliqueEcoutee === replique) {
    reconnaissance.arreter();
    return;
  }

  if (repliqueEcoutee !== null) {
    reconnaissance.arreter();
  }

  messageMicro('');
  repliqueEcoutee = replique;
  replique.querySelector('.reciter').textContent = '■ Arrêter';
  reconnaissance.demarrer();
}

// ============================================================
// DÉMARRAGE
// ============================================================

rafraichirBandeaux();
rafraichirListePieces();

// Le bandeau d'inertie est visible dans le HTML : l'atteindre prouve que les
// modules se sont chargés et que les écouteurs sont posés. C'est donc la
// dernière ligne du démarrage, et non la première — une erreur survenue
// entre-temps doit le laisser affiché.
$('bandeau-inerte').hidden = true;

// ============================================================
// PROGRESSION — étape 8
// ============================================================

/**
 * Personnage sous lequel la progression est rangée.
 *
 * Le cahier exige que rien ne soit partagé entre deux de mes rôles. Quand je
 * répète plusieurs personnages ensemble, la progression est rangée sous une clé
 * composée : c'est ce couple-là que je travaille, et le mélanger avec les
 * sessions à un seul rôle brouillerait les deux.
 */
/** Réglages de la règle de répétition espacée, tirés de `config.js`. */
const REGLES = Object.freeze({
  seuil: CONFIG.SEUIL_REUSSITE,
  reussitesPourMaitrise: CONFIG.REUSSITES_POUR_MAITRISE,
  intervallesJours: CONFIG.INTERVALLES_REVISION_JOURS,
});

/**
 * Recalcule le statut de toutes mes répliques.
 *
 * Le statut n'est pas stocké : il est **dérivé** de l'historique des scores à
 * chaque affichage. C'est ce qui fait fonctionner la répétition espacée sans
 * minuterie — une maîtrise expire toute seule, simplement parce que le temps a
 * passé entre deux ouvertures de l'outil.
 */
function recalculerStatuts(maintenant = Date.now()) {
  for (const id of index.mesRepliques) {
    const suivi = progres[id];

    if (suivi === undefined) {
      continue;
    }

    progres[id] = {
      ...suivi,
      statut: modele.statutDepuisScores(suivi, maintenant, REGLES),
    };
  }
}

function clePersonnage() {
  return [...etat.roleActif].sort().join('+');
}

function chargerProgression() {
  progres = stockage.lireProgres(etat.pieceId, clePersonnage());
  annotations = stockage.lireAnnotations(etat.pieceId);
}

let ecritureDifferee = null;

/**
 * Écriture différée.
 *
 * Cocher trois statuts d'affilée ne doit pas provoquer trois écritures. Le délai
 * vient de `CONFIG.DELAI_ECRITURE_MS`.
 */
function enregistrerProgression() {
  clearTimeout(ecritureDifferee);

  ecritureDifferee = setTimeout(() => {
    avecStockage(
      () => stockage.ecrireProgres(etat.pieceId, clePersonnage(), progres),
      'bandeau-stockage',
    );
    avecStockage(
      () => stockage.ecrireAnnotations(etat.pieceId, annotations),
      'bandeau-stockage',
    );
  }, CONFIG.DELAI_ECRITURE_MS);
}

/**
 * Écriture forcée au passage en arrière-plan.
 *
 * Sur iOS, `beforeunload` n'est pas fiable : c'est `visibilitychange` qui
 * attrape la fermeture réelle, et une progression cochée dans les dernières
 * secondes serait sinon perdue.
 */
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'hidden' || !etat.pieceId) {
    return;
  }

  clearTimeout(ecritureDifferee);

  try {
    stockage.ecrireProgres(etat.pieceId, clePersonnage(), progres);
    stockage.ecrireAnnotations(etat.pieceId, annotations);
  } catch (erreur) {
    // Plus rien ne peut être affiché à ce stade. L'échec se verra au retour,
    // par le bandeau de stockage.
    console.warn('écriture en arrière-plan impossible', erreur);
  }
});

/**
 * Enregistre un score et en déduit le nouveau statut.
 *
 * @param {string} id
 * @param {number} score
 */
function enregistrerScore(id, score, maintenant = Date.now()) {
  progres[id] = modele.ajouterScore(
    progres[id],
    score,
    maintenant,
    CONFIG.SCORES_PAR_REPLIQUE,
  );

  recalculerStatuts(maintenant);
  rendu.appliquerProgression($('app'), index, progres, annotations);
  enregistrerProgression();

  const suivi = progres[id];
  const echeance = modele.prochaineRevision(suivi, REGLES);

  // Annoncer la prochaine révision plutôt que de laisser une maîtrise expirer
  // sans prévenir : c'est l'information qui rend la règle compréhensible.
  if (suivi.statut === modele.STATUT.MAITRISEE && echeance !== null) {
    const jours = Math.max(1, Math.round((echeance - maintenant) / 86400000));

    rendu.afficherEtatControle(
      document.querySelector(`.replique[data-id="${id}"]`),
      `sue — à revoir dans ${jours} jour(s)`,
    );
  }
}

/**
 * Compte la dernière récitation comme réussie, malgré son score.
 *
 * La transcription vocale n'est pas fiable : une élision avalée ou un nom propre
 * écorché par le moteur de Safari suffit à noter 70 % une récitation parfaite.
 * Sans ce recours, l'outil mesurerait la qualité de la transcription plutôt que
 * celle de la mémoire.
 *
 * Le score mesuré est **conservé** dans l'historique, avec un drapeau. Écrire
 * 100 % à la place aurait été plus simple et aurait effacé la trace de ce que
 * l'outil avait réellement entendu.
 */
function validerRecitation(id, maintenant = Date.now()) {
  if (progres[id]?.scores?.length === undefined) {
    return;
  }

  progres[id] = modele.corrigerDerniereRecitation(progres[id]);

  recalculerStatuts(maintenant);
  rendu.marquerRecitationValidee(document.querySelector(`.replique[data-id="${id}"]`));
  rendu.appliquerProgression($('app'), index, progres, annotations);
  enregistrerProgression();
}

function annoter(id) {
  // `window.prompt` plutôt qu'un champ dans la page : c'est fruste, mais cela
  // fonctionne au doigt sur iOS sans réclamer un clavier à positionner sous une
  // réplique déjà masquée. À remplacer si l'usage le demande.
  const actuel = annotations[id]?.texte ?? '';
  const saisi = window.prompt('Note de jeu (respiration, déplacement…)', actuel);

  if (saisi === null) {
    return;
  }

  annotations[id] = { ...annotations[id], texte: saisi.trim() };
  rendu.appliquerProgression($('app'), index, progres, annotations);
  enregistrerProgression();
}

// ============================================================
// BILAN ET SPOT CHECK
// ============================================================

function ouvrirBilan() {
  const compte = modele.bilan(index, progres);

  $('bilan-titre').textContent = piece.piece;
  $('bilan-resume').textContent =
    `${compte.maitrisee} sue(s), ${compte.a_reviser} à réviser, ` +
    `${compte.en_cours} en cours, ${compte.a_apprendre} à apprendre — ` +
    `sur ${compte.total}, pour ${etat.roleActif.join(' & ')}.`;

  const liste = $('bilan-scenes');
  liste.innerHTML = '';

  for (const entree of index.sommaire) {
    if (!entree.mienne) {
      continue;
    }

    const statut = modele.statutDUnite(index, entree.unite, progres);
    const ligne = document.createElement('li');

    const gauche = document.createElement('span');
    const puce = document.createElement('span');
    puce.className = 'puce-statut';
    puce.dataset.statut = statut ?? 'a_apprendre';
    gauche.append(puce, document.createTextNode(entree.titre ?? 'Suite'));

    const droite = document.createElement('span');
    droite.className = 'compte';
    droite.textContent = `${entree.nbMesRepliques} répl.`;

    ligne.append(gauche, droite);
    ligne.style.cursor = 'pointer';
    ligne.addEventListener('click', () => allerAUnite(entree.unite));
    liste.appendChild(ligne);
  }

  montrer('ecran-bilan');
}

/**
 * Pioche une réplique parmi celles que je sais.
 *
 * Le tirage est **pondéré par l'ancienneté** (§10.7) : un tirage uniforme
 * redemanderait souvent celle qu'on vient de vérifier. La graine dérive de
 * l'horloge, parce qu'ici on veut précisément que deux spot checks diffèrent —
 * c'est le seul endroit du projet où la reproductibilité n'est pas souhaitable.
 */
function spotCheck() {
  const candidats = modele.candidatsSpotCheck(index, progres, Date.now());

  if (candidats.length === 0) {
    afficherMessage(
      'message-bilan',
      'Aucune réplique marquée « su » pour l’instant : le spot check n’a rien à ' +
        'piocher. Cochez d’abord ce que vous savez.',
      'avertissement',
    );
    return;
  }

  const choisie = tirerPondere(candidats, graineDepuis(String(Date.now())));

  effacerMessage('message-bilan');
  etat = etatSession.changerMode(etat, etatSession.MODE.AVEUGLE);
  etat = etatSession.allerA(etat, { replique: choisie });

  appliquer();
  synchroniserCommandes();
  montrer('ecran-repetition');

  document
    .querySelector(`.replique[data-id="${choisie}"]`)
    ?.scrollIntoView({ block: 'center' });
}

// ============================================================
// SOMMAIRE, RECHERCHE, DÉFILEMENT — étape 9
// ============================================================

function allerAUnite(idUnite) {
  montrer('ecran-repetition');
  etat = etatSession.allerA(etat, { unite: idUnite });

  document
    .querySelector(`.unite[data-id="${idUnite}"]`)
    ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function rechercher(fragment) {
  const zone = $('resultats-recherche');
  zone.innerHTML = '';

  if (fragment.trim().length < 2) {
    return;
  }

  // La recherche porte sur l'index, jamais sur le DOM : elle couvre donc la pièce
  // entière, y compris ce que le mode courant masque.
  const trouves = modele.chercher(index, fragment).slice(0, 30);

  if (trouves.length === 0) {
    const rien = document.createElement('p');
    rien.className = 'aide';
    rien.textContent = 'Rien trouvé.';
    zone.appendChild(rien);
    return;
  }

  for (const trouve of trouves) {
    const carte = document.createElement('div');
    carte.className = 'resultat';

    const qui = document.createElement('div');
    qui.className = 'qui';
    qui.textContent = trouve.personnage;

    const extrait = document.createElement('div');
    extrait.textContent =
      trouve.texte.length > 90 ? `${trouve.texte.slice(0, 89)}…` : trouve.texte;

    carte.append(qui, extrait);
    carte.addEventListener('click', () => {
      document
        .querySelector(`.replique[data-id="${trouve.id}"]`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });

    zone.appendChild(carte);
  }
}

// ============================================================
// ÉCOUTEURS DES ÉTAPES 8 ET 9
// ============================================================

$('btn-sommaire').addEventListener('click', ouvrirBilan);
$('btn-bilan').addEventListener('click', ouvrirBilan);
$('btn-spot-check').addEventListener('click', spotCheck);
$('btn-retour-texte').addEventListener('click', () => montrer('ecran-repetition'));

$('recherche').addEventListener('input', (evenement) => {
  rechercher(evenement.target.value);
});

$('curseur-police').addEventListener('input', (evenement) => {
  etat = etatSession.changerReglage(
    etat,
    'taillePolice',
    Number(evenement.target.value) / 100,
  );
  rendu.appliquerPresentation($('app'), etat);
});

$('curseur-police').addEventListener('change', enregistrerReglages);

$('btn-exporter-2').addEventListener('click', exporterProgression);
$('btn-exporter-3').addEventListener('click', exporterProgression);
$('fichier-sauvegarde-2').addEventListener('change', (evenement) =>
  lireFichier(evenement.target, importerProgression),
);

// ============================================================
// SERVICE WORKER
// ============================================================

/**
 * Enregistrement du service worker.
 *
 * Différé après le chargement : sur une première visite, l'installation
 * précharge quinze fichiers, et le faire pendant l'affichage retarderait
 * l'apparition de la page.
 *
 * L'échec est consigné, jamais affiché : sans service worker, l'outil fonctionne
 * exactement pareil — il exige simplement le réseau à l'ouverture.
 */
if ('serviceWorker' in navigator && location.protocol !== 'file:') {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('./sw.js')
      .catch((erreur) => console.warn('service worker non enregistré', erreur));
  });
}
