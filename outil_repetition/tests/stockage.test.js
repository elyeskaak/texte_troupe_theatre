/**
 * Tests de `js/stockage.js`.
 *
 * Le module est impur, mais son support est injectable : ces tests lui passent
 * une doublure en mémoire et tournent donc sous Node, sans navigateur.
 *
 * Le fil directeur est le défaut qu'ils existent pour empêcher : le prototype
 * appelait une API de stockage inexistante, entourée d'un `catch` qui rendait
 * `null`. Rien n'était jamais sauvegardé, et rien ne le signalait. D'où
 * l'insistance sur les **échecs visibles** et sur l'aller-retour réel.
 */

import { test, describe, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import {
  CLE,
  creerStockage,
  ErreurStockage,
  FORMAT_EXPORT,
  idDePiece,
  supportEnMemoire,
} from '../js/stockage.js';
import { STATUT } from '../js/modele.js';
import { CONFIG } from '../js/config.js';

const PIECE = {
  schema: CONFIG.SCHEMA_ACCEPTE,
  piece: 'Le Malentendu',
  personnages: [
    { nom: 'JAN', repliques: 2, mots: 8 },
    { nom: 'MARTHA', repliques: 1, mots: 3 },
  ],
  unites: [
    {
      id: 'u001',
      acte: null,
      scene: null,
      implicite: true,
      personnages: ['JAN'],
      elements: [
        { type: 'replique', id: 'r_a', personnage: 'JAN', texte: 'Un.', vers: false },
      ],
    },
  ],
};

let support;
let stockage;

beforeEach(() => {
  support = supportEnMemoire();
  stockage = creerStockage(support);
});

describe('identifiant de pièce', () => {
  test('dérivé du titre, en ASCII', () => {
    assert.equal(idDePiece('Le Malentendu'), 'le-malentendu');
    assert.equal(idDePiece('La Toile d’araignée'), 'la-toile-d-araignee');
  });

  test('stable : deux appels donnent le même identifiant', () => {
    // C'est ce qui permet de réimporter une pièce rééditée sans orpheliner ses
    // annotations.
    assert.equal(idDePiece('Le Malentendu'), idDePiece('Le Malentendu'));
  });

  test('un titre sans lettre latine ne donne pas une clé vide', () => {
    // Une clé vide collisionnerait avec toute autre pièce du même cas.
    const a = idDePiece('三人姉妹');
    const b = idDePiece('вишневый сад');

    assert.ok(a.length > 0);
    assert.notEqual(a, b);
  });

  test('un titre vide non plus', () => {
    assert.ok(idDePiece('').length > 0);
  });
});

describe('pièces', () => {
  test('enregistrer puis relire', () => {
    const id = stockage.enregistrerPiece(PIECE);
    const relue = stockage.lirePiece(id);

    assert.equal(relue.piece, 'Le Malentendu');
    assert.equal(relue.unites.length, 1);
  });

  test('la pièce apparaît dans l’index avec ses personnages', () => {
    stockage.enregistrerPiece(PIECE);
    const index = stockage.listerPieces();

    assert.equal(index.length, 1);
    assert.equal(index[0].titre, 'Le Malentendu');
    assert.deepEqual(index[0].personnages, ['JAN', 'MARTHA']);
  });

  test('réenregistrer la même pièce ne la duplique pas', () => {
    stockage.enregistrerPiece(PIECE);
    stockage.enregistrerPiece({ ...PIECE, piece: 'Le Malentendu' });

    assert.equal(stockage.listerPieces().length, 1);
  });

  test('une pièce rééditée conserve ses annotations', () => {
    // C'est la raison d'être de l'identifiant dérivé du titre.
    const id = stockage.enregistrerPiece(PIECE);
    stockage.ecrireAnnotations(id, { r_a: 'respirer ici' });

    stockage.enregistrerPiece({ ...PIECE, unites: [] });

    assert.deepEqual(stockage.lireAnnotations(id), { r_a: 'respirer ici' });
  });

  test('une pièce absente rend null, sans erreur', () => {
    assert.equal(stockage.lirePiece('inconnue'), null);
  });

  test('supprimer emporte la pièce, sa progression et ses annotations', () => {
    const id = stockage.enregistrerPiece(PIECE);
    stockage.ecrireProgres(id, 'JAN', { r_a: { statut: STATUT.MAITRISEE } });
    stockage.ecrireAnnotations(id, { r_a: 'note' });

    stockage.supprimerPiece(id);

    assert.equal(stockage.lirePiece(id), null);
    assert.deepEqual(stockage.listerPieces(), []);
    assert.deepEqual(stockage.lireProgres(id, 'JAN'), {});
    assert.deepEqual(stockage.lireAnnotations(id), {});
  });

  test('supprimer une pièce n’emporte pas les autres', () => {
    const a = stockage.enregistrerPiece(PIECE);
    const b = stockage.enregistrerPiece({ ...PIECE, piece: 'Les Justes' });

    stockage.ecrireProgres(b, 'JAN', { r_a: { statut: STATUT.EN_COURS } });
    stockage.supprimerPiece(a);

    assert.equal(stockage.lirePiece(b).piece, 'Les Justes');
    assert.equal(stockage.lireProgres(b, 'JAN').r_a.statut, STATUT.EN_COURS);
  });
});

describe('progression par personnage', () => {
  test('deux personnages ont des progressions indépendantes', () => {
    // Exigence du cahier : rien de partagé entre Henry et Oliver.
    const id = stockage.enregistrerPiece(PIECE);

    stockage.ecrireProgres(id, 'JAN', { r_a: { statut: STATUT.MAITRISEE } });
    stockage.ecrireProgres(id, 'MARTHA', { r_a: { statut: STATUT.A_APPRENDRE } });

    assert.equal(stockage.lireProgres(id, 'JAN').r_a.statut, STATUT.MAITRISEE);
    assert.equal(stockage.lireProgres(id, 'MARTHA').r_a.statut, STATUT.A_APPRENDRE);
  });

  test('écrire un statut ne réécrit pas la pièce', () => {
    // Sans clés séparées, chaque tape sur « maîtrisée » recopierait 200 Ko.
    const id = stockage.enregistrerPiece(PIECE);
    const avant = support.getItem(CLE.piece(id));

    stockage.ecrireProgres(id, 'JAN', { r_a: { statut: STATUT.EN_COURS } });

    assert.equal(support.getItem(CLE.piece(id)), avant);
  });

  test('sans progression enregistrée, un objet vide', () => {
    assert.deepEqual(stockage.lireProgres('x', 'JAN'), {});
  });
});

describe('erreurs visibles', () => {
  test('une écriture qui échoue lève, elle ne rend pas null', () => {
    const cassé = {
      ...supportEnMemoire(),
      setItem() {
        throw new Error('disque en lecture seule');
      },
    };

    assert.throws(
      () => creerStockage(cassé).ecrireReglages({ sombre: true }),
      ErreurStockage,
    );
  });

  test('la saturation est reconnue et dit quoi faire', () => {
    const saturé = {
      ...supportEnMemoire(),
      setItem() {
        const erreur = new Error('quota');
        erreur.name = 'QuotaExceededError';
        throw erreur;
      },
    };

    try {
      creerStockage(saturé).ecrireReglages({});
      assert.fail('aucune erreur levée');
    } catch (erreur) {
      assert.ok(erreur instanceof ErreurStockage);
      assert.ok(erreur.saturee, 'la saturation n’a pas été reconnue');
      assert.match(erreur.message, /Exportez/);
    }
  });

  test('le code 22 est aussi une saturation', () => {
    // Certaines versions de Safari ne renseignent que le code numérique.
    const saturé = {
      ...supportEnMemoire(),
      setItem() {
        const erreur = new Error('quota');
        erreur.code = 22;
        throw erreur;
      },
    };

    try {
      creerStockage(saturé).ecrireReglages({});
      assert.fail('aucune erreur levée');
    } catch (erreur) {
      assert.ok(erreur.saturee);
    }
  });

  test('une valeur illisible ne fait pas tomber la lecture d’une préférence', () => {
    // P4 : une donnée d'agrément abîmée ne doit pas empêcher de répéter.
    support.setItem(CLE.reglages(), '{ ceci n’est pas du JSON');

    assert.equal(stockage.lireReglages(), null);
  });

  test('un index illisible ne fait pas tomber la liste des pièces', () => {
    support.setItem(CLE.index(), 'cassé');

    assert.deepEqual(stockage.listerPieces(), []);
  });
});

describe('support en mémoire', () => {
  test('il se déclare non persistant', () => {
    // C'est ce qui permet à l'interface d'annoncer que rien ne sera conservé.
    assert.equal(creerStockage(supportEnMemoire()).persistant(), false);
  });

  test('un support fourni sans marque est tenu pour persistant', () => {
    const faux = { ...supportEnMemoire() };
    delete faux.enMemoire;

    assert.equal(creerStockage(faux).persistant(), true);
  });
});

describe('export', () => {
  test('contient progression, annotations et réglages', () => {
    const id = stockage.enregistrerPiece(PIECE);
    stockage.ecrireProgres(id, 'JAN', { r_a: { statut: STATUT.MAITRISEE } });
    stockage.ecrireAnnotations(id, { r_a: 'respirer' });
    stockage.ecrireReglages({ sombre: false });

    const sauvegarde = stockage.exporter(1000);

    assert.equal(sauvegarde.format, FORMAT_EXPORT);
    assert.equal(sauvegarde.exporte_le, 1000);
    assert.equal(sauvegarde.progres[`${id}:JAN`].r_a.statut, STATUT.MAITRISEE);
    assert.equal(sauvegarde.annotations[id].r_a, 'respirer');
    assert.equal(sauvegarde.reglages.sombre, false);
  });

  test('ne contient AUCUNE pièce', () => {
    // Un REPET.json est reproductible depuis outil_edition, et l'inclure
    // gonflerait le fichier de texte sous droits pour rien.
    stockage.enregistrerPiece(PIECE);
    const sauvegarde = stockage.exporter();

    assert.ok(!('pieces' in sauvegarde));
    assert.ok(!JSON.stringify(sauvegarde).includes('Le Malentendu'));
  });

  test('un export à vide reste valide', () => {
    const sauvegarde = stockage.exporter();

    assert.equal(sauvegarde.format, FORMAT_EXPORT);
    assert.deepEqual(sauvegarde.progres, {});
  });
});

describe('import', () => {
  test('un aller-retour restitue à l’identique', () => {
    const id = stockage.enregistrerPiece(PIECE);
    stockage.ecrireProgres(id, 'JAN', {
      r_a: { statut: STATUT.MAITRISEE, verifiee_le: 500, scores: [{ le: 500, score: 90 }] },
    });

    const sauvegarde = stockage.exporter();
    const neuf = creerStockage(supportEnMemoire());

    neuf.importer(sauvegarde);

    assert.deepEqual(neuf.lireProgres(id, 'JAN').r_a, {
      statut: STATUT.MAITRISEE,
      verifiee_le: 500,
      scores: [{ le: 500, score: 90 }],
    });
  });

  test('l’import fusionne, il n’écrase pas', () => {
    // Écraser détruirait le travail fait depuis l'export — le geste même qu'on
    // ferait en croyant se protéger.
    const id = idDePiece('Le Malentendu');

    stockage.ecrireProgres(id, 'JAN', {
      r_a: { statut: STATUT.MAITRISEE },
      r_local: { statut: STATUT.EN_COURS },
    });

    stockage.importer({
      format: FORMAT_EXPORT,
      progres: {
        [`${id}:JAN`]: {
          r_a: { statut: STATUT.A_APPRENDRE },
          r_importe: { statut: STATUT.MAITRISEE },
        },
      },
    });

    const apres = stockage.lireProgres(id, 'JAN');

    // Le statut le plus avancé gagne, et rien ne disparaît.
    assert.equal(apres.r_a.statut, STATUT.MAITRISEE);
    assert.equal(apres.r_local.statut, STATUT.EN_COURS);
    assert.equal(apres.r_importe.statut, STATUT.MAITRISEE);
  });

  test('les annotations locales gagnent sur les importées', () => {
    // Une note de jeu perdue est plus contrariante qu'une note en double.
    const id = idDePiece('Le Malentendu');
    stockage.ecrireAnnotations(id, { r_a: 'version locale' });

    stockage.importer({
      format: FORMAT_EXPORT,
      annotations: { [id]: { r_a: 'version importée', r_b: 'seulement importée' } },
    });

    const apres = stockage.lireAnnotations(id);

    assert.equal(apres.r_a, 'version locale');
    assert.equal(apres.r_b, 'seulement importée');
  });

  test('un format inconnu est refusé et le dit', () => {
    assert.throws(
      () => stockage.importer({ format: 'autre-chose/9', progres: {} }),
      /non reconnu/,
    );
  });

  test('un fichier sans format est refusé', () => {
    assert.throws(() => stockage.importer({ progres: {} }), ErreurStockage);
  });

  test('un import vide ne casse rien', () => {
    assert.deepEqual(stockage.importer({ format: FORMAT_EXPORT }), { repliques: 0 });
  });
});

describe('ancienneté de l’export', () => {
  const JOUR = 86400000;

  test('sans export, rend null', () => {
    assert.equal(stockage.joursDepuisExport(), null);
  });

  test('compte les jours écoulés', () => {
    stockage.marquerExport(1000);

    assert.equal(stockage.joursDepuisExport(1000 + 3 * JOUR), 3);
  });

  test('le seuil d’alerte précède les 7 jours de Safari', () => {
    // Alerter le jour de l'échéance serait alerter trop tard.
    assert.ok(CONFIG.JOURS_SANS_EXPORT_ALERTE < 7);
  });

  test('une date future ne rend pas un nombre négatif', () => {
    stockage.marquerExport(2000);

    assert.equal(stockage.joursDepuisExport(1000), 0);
  });
});

describe('session et réglages', () => {
  test('aller-retour de la session', () => {
    stockage.ecrireSession({ pieceId: 'p1', uniteCourante: 'u003' });

    assert.deepEqual(stockage.lireSession(), {
      pieceId: 'p1',
      uniteCourante: 'u003',
    });
  });

  test('sans session enregistrée, null', () => {
    assert.equal(stockage.lireSession(), null);
  });
});

describe('dossier Google Drive retenu (§3.3)', () => {
  test('aller-retour', () => {
    stockage.ecrireDossierDrive({ id: 'DOSSIER123', nom: 'Pièces Troupe 122' });

    assert.deepEqual(stockage.lireDossierDrive(), {
      id: 'DOSSIER123',
      nom: 'Pièces Troupe 122',
    });
  });

  test('sans dossier enregistré, null', () => {
    assert.equal(stockage.lireDossierDrive(), null);
  });
});

describe('rôles retenus par pièce', () => {
  test('aller-retour', () => {
    const id = stockage.enregistrerPiece(PIECE);

    stockage.ecrireRoles(id, { mesRoles: ['JAN', 'MARTHA'], roleActif: ['JAN'] });

    assert.deepEqual(stockage.lireRoles(id), {
      mesRoles: ['JAN', 'MARTHA'],
      roleActif: ['JAN'],
    });
  });

  test('sans rien d’enregistré, null', () => {
    // C'est ce qui distingue « pas encore choisi » de « choisi puis vidé ».
    assert.equal(stockage.lireRoles('inconnue'), null);
  });

  test('rangés par pièce, non par session', () => {
    // On répète Henry dans l'une et Clarissa dans l'autre : une clé unique
    // ferait perdre le choix à chaque changement de texte.
    const a = stockage.enregistrerPiece(PIECE);
    const b = stockage.enregistrerPiece({ ...PIECE, piece: 'Les Justes' });

    stockage.ecrireRoles(a, { mesRoles: ['JAN'], roleActif: ['JAN'] });
    stockage.ecrireRoles(b, { mesRoles: ['MARTHA'], roleActif: ['MARTHA'] });

    assert.deepEqual(stockage.lireRoles(a).mesRoles, ['JAN']);
    assert.deepEqual(stockage.lireRoles(b).mesRoles, ['MARTHA']);
  });

  test('supprimer la pièce emporte ses rôles', () => {
    const id = stockage.enregistrerPiece(PIECE);
    stockage.ecrireRoles(id, { mesRoles: ['JAN'], roleActif: ['JAN'] });

    stockage.supprimerPiece(id);

    assert.equal(stockage.lireRoles(id), null);
  });

  test('les rôles ne partent pas dans l’export', () => {
    // Un export sert à transporter la progression : les rôles se rechoisissent
    // en deux touches, et les imposer sur un autre appareil serait présumer.
    const id = stockage.enregistrerPiece(PIECE);
    stockage.ecrireRoles(id, { mesRoles: ['JAN'], roleActif: ['JAN'] });

    assert.ok(!('roles' in stockage.exporter()));
  });
});
