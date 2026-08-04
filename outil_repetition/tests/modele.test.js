/**
 * Tests de `js/modele.js`.
 *
 * L'essentiel porte sur **le top**, parce que c'est là qu'une erreur ne se voit
 * pas : un top faux ne casse rien, il fait seulement répéter sur le mauvais
 * signal. Les trois cas du §10.1 de l'architecture y sont couverts un par un.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import {
  ajouterScore,
  corrigerDerniereRecitation,
  bilan,
  candidatsSpotCheck,
  difficulte,
  filePrioritaire,
  chercher,
  fusionnerProgres,
  indexer,
  MOTIF_SANS_TOP,
  repliqueVoisine,
  prochaineRevision,
  REVISION,
  statutDepuisScores,
  statutDUnite,
  STATUT,
  texteDuTop,
  titreDUnite,
  TOP,
} from '../js/modele.js';

let compteur = 0;

/**
 * Réplique minimale, identifiant automatique.
 *
 * @param {string|string[]} personnages - un nom, ou plusieurs pour une
 *   réplique collective.
 */
function r(personnages, texte) {
  compteur += 1;

  return {
    type: 'replique',
    id: `r_${compteur}`,
    personnages: Array.isArray(personnages) ? personnages : [personnages],
    texte,
    vers: false,
  };
}

function d(texte) {
  return { type: 'didascalie', texte };
}

function unite(id, elements, extra = {}) {
  return {
    id,
    acte: 'ACTE PREMIER',
    scene: null,
    implicite: false,
    personnages: [
      ...new Set(
        elements
          .filter((e) => e.type === 'replique')
          .flatMap((e) => e.personnages),
      ),
    ],
    elements,
    ...extra,
  };
}

function piece(unites, personnages = []) {
  return { schema: 'repetition/2', piece: 'Essai', personnages, unites };
}

describe('mes unités', () => {
  test('une unité où je parle est mienne', () => {
    const index = indexer(
      piece([unite('u1', [r('JAN', 'Un.')]), unite('u2', [r('AUTRE', 'Deux.')])]),
      ['JAN'],
    );

    assert.equal(index.unites[0].mienne, true);
    assert.equal(index.unites[1].mienne, false);
  });

  test('le compte de mes répliques est précalculé', () => {
    const index = indexer(
      piece([unite('u1', [r('JAN', 'Un.'), r('AUTRE', 'Deux.'), r('JAN', 'Trois.')])]),
      ['JAN'],
    );

    assert.equal(index.unites[0].nbMesRepliques, 2);
  });

  test('sans rôle déclaré, aucune unité n’est mienne', () => {
    const index = indexer(piece([unite('u1', [r('JAN', 'Un.')])]), []);

    assert.equal(index.unites[0].mienne, false);
    assert.deepEqual(index.mesRepliques, []);
  });

  test('deux de mes rôles rendent l’unité mienne une seule fois', () => {
    const index = indexer(
      piece([unite('u1', [r('HENRY', 'Un.'), r('OLIVER', 'Deux.')])]),
      ['HENRY', 'OLIVER'],
    );

    assert.equal(index.unites[0].mienne, true);
    assert.equal(index.mesRepliques.length, 2);
  });
});

describe('le top — cas 1 : réplique d’un autre', () => {
  test('la réplique précédente est le top', () => {
    const mienne = r('JAN', 'Ma réplique.');
    const index = indexer(
      piece([unite('u1', [r('AUTRE', 'Le signal.'), mienne])]),
      ['JAN'],
    );

    const top = index.tops.get(mienne.id);

    assert.equal(top.type, TOP.REPLIQUE);
    assert.deepEqual(top.personnages, ['AUTRE']);
    assert.equal(top.texte, 'Le signal.');
  });
});

describe('le top — cas 2 : didascalie', () => {
  test('une didascalie après la réplique d’un autre est le top', () => {
    // « Une porte qui claque est un top. »
    const mienne = r('JAN', 'Ma réplique.');
    const index = indexer(
      piece([
        unite('u1', [r('AUTRE', 'Le signal.'), d('On frappe à la porte.'), mienne]),
      ]),
      ['JAN'],
    );

    const top = index.tops.get(mienne.id);

    assert.equal(top.type, TOP.DIDASCALIE);
    assert.equal(top.texte, 'On frappe à la porte.');
  });

  test('une didascalie ouvrant la scène est le top', () => {
    const mienne = r('JAN', 'Ma réplique.');
    const index = indexer(
      piece([unite('u1', [d('On frappe à la porte.'), mienne])]),
      ['JAN'],
    );

    assert.equal(index.tops.get(mienne.id).type, TOP.DIDASCALIE);
  });

  test('un lieu n’est jamais un top', () => {
    // « Un salon. Le soir tombe. » est un décor, pas un événement : on ne peut
    // pas attendre qu'il se produise pour parler.
    const mienne = r('JAN', 'Ma réplique.');
    const index = indexer(
      piece([
        unite('u1', [{ type: 'lieu', texte: 'Un salon. Le soir tombe.' }, mienne]),
      ]),
      ['JAN'],
    );

    const top = index.tops.get(mienne.id);

    assert.equal(top.type, TOP.AUCUN);
    assert.equal(top.motif, MOTIF_SANS_TOP.DEBUT);
  });

  test('un lieu est traversé pour trouver le vrai top', () => {
    const mienne = r('JAN', 'Ma réplique.');
    const index = indexer(
      piece([
        unite('u1', [
          r('AUTRE', 'Le signal.'),
          { type: 'lieu', texte: 'Le décor change.' },
          mienne,
        ]),
      ]),
      ['JAN'],
    );

    const top = index.tops.get(mienne.id);

    assert.equal(top.type, TOP.REPLIQUE);
    assert.deepEqual(top.personnages, ['AUTRE']);
  });
});

describe('le top — cas 3 : aucun top', () => {
  test('une réplique qui ouvre l’unité n’a pas de top', () => {
    const mienne = r('JAN', 'J’ouvre la scène.');
    const index = indexer(piece([unite('u1', [mienne, r('AUTRE', 'Suite.')])]), [
      'JAN',
    ]);

    const top = index.tops.get(mienne.id);

    assert.equal(top.type, TOP.AUCUN);
    assert.equal(top.motif, MOTIF_SANS_TOP.DEBUT);
  });

  test('deux de mes répliques d’affilée : enchaînement', () => {
    const seconde = r('JAN', 'Et je continue.');
    const index = indexer(
      piece([unite('u1', [r('JAN', 'Je parle.'), seconde])]),
      ['JAN'],
    );

    const top = index.tops.get(seconde.id);

    assert.equal(top.type, TOP.AUCUN);
    assert.equal(top.motif, MOTIF_SANS_TOP.ENCHAINEMENT);
  });

  test('deux de mes répliques séparées par une didascalie : enchaînement', () => {
    // C'est le cas qu'on oublie. La didascalie ne fait pas d'elle un top :
    // c'est moi qui parlais juste avant, il n'y a pas de signal à attendre.
    const seconde = r('JAN', 'Et je continue.');
    const index = indexer(
      piece([unite('u1', [r('JAN', 'Je parle.'), d('Pause.'), seconde])]),
      ['JAN'],
    );

    const top = index.tops.get(seconde.id);

    assert.equal(top.type, TOP.AUCUN);
    assert.equal(top.motif, MOTIF_SANS_TOP.ENCHAINEMENT);
  });

  test('deux de mes rôles en dialogue : enchaînement', () => {
    // Je joue Henry et Oliver : quand Henry donne la réplique à Oliver, c'est
    // encore moi qui parle.
    const oliver = r('OLIVER', 'À moi.');
    const index = indexer(
      piece([unite('u1', [r('HENRY', 'À toi.'), oliver])]),
      ['HENRY', 'OLIVER'],
    );

    assert.equal(index.tops.get(oliver.id).motif, MOTIF_SANS_TOP.ENCHAINEMENT);
  });

  test('mais si un tiers s’intercale, le top revient', () => {
    const oliver = r('OLIVER', 'À moi.');
    const index = indexer(
      piece([
        unite('u1', [r('HENRY', 'À toi.'), r('TIERS', 'Attendez.'), oliver]),
      ]),
      ['HENRY', 'OLIVER'],
    );

    const top = index.tops.get(oliver.id);

    assert.equal(top.type, TOP.REPLIQUE);
    assert.deepEqual(top.personnages, ['TIERS']);
  });
});

describe('le top — portée', () => {
  test('les répliques des autres n’ont pas de top calculé', () => {
    const autre = r('AUTRE', 'Pas la mienne.');
    const index = indexer(
      piece([unite('u1', [r('JAN', 'Un.'), autre])]),
      ['JAN'],
    );

    assert.equal(index.tops.has(autre.id), false);
  });

  test('le top ne traverse pas les unités', () => {
    // Une scène commence : le dernier mot de la scène précédente n'est pas un
    // signal, il y a eu un noir entre les deux.
    const mienne = r('JAN', 'J’ouvre.');
    const index = indexer(
      piece([unite('u1', [r('AUTRE', 'Fin de scène.')]), unite('u2', [mienne])]),
      ['JAN'],
    );

    assert.equal(index.tops.get(mienne.id).motif, MOTIF_SANS_TOP.DEBUT);
  });
});

describe('texteDuTop', () => {
  test('rend le texte entier par défaut', () => {
    const top = { type: TOP.REPLIQUE, texte: 'Un deux trois quatre cinq six.' };

    assert.equal(texteDuTop(top), 'Un deux trois quatre cinq six.');
  });

  test('réduit aux derniers mots quand on le demande', () => {
    const top = { type: TOP.REPLIQUE, texte: 'Un deux trois quatre cinq six.' };

    assert.equal(texteDuTop(top, 2), 'cinq six.');
  });

  test('rend null quand il n’y a pas de top', () => {
    // Le rendu doit pouvoir distinguer « pas de top » d'un top vide.
    assert.equal(texteDuTop({ type: TOP.AUCUN, motif: 'debut_unite' }), null);
    assert.equal(texteDuTop(undefined), null);
  });
});

describe('titreDUnite', () => {
  test('la scène primes sur l’acte', () => {
    assert.equal(
      titreDUnite({ acte: 'ACTE PREMIER', scene: 'SCÈNE 2', implicite: false }),
      'SCÈNE 2',
    );
  });

  test('sans scène, l’acte fait le titre', () => {
    assert.equal(
      titreDUnite({ acte: 'ACTE PREMIER', scene: null, implicite: false }),
      'ACTE PREMIER',
    );
  });

  test('une unité implicite n’a pas de titre', () => {
    // Lui en fabriquer un afficherait une scène qui n'existe pas dans le texte.
    assert.equal(
      titreDUnite({ acte: 'ACTE PREMIER', scene: 'SCÈNE 2', implicite: true }),
      null,
    );
  });
});

describe('navigation', () => {
  const jan1 = r('JAN', 'Un.');
  const jan2 = r('JAN', 'Deux.');
  const jan3 = r('JAN', 'Trois.');
  const index = indexer(
    piece([
      unite('u1', [jan1, r('AUTRE', 'a'), jan2]),
      unite('u2', [r('AUTRE', 'b'), jan3]),
    ]),
    ['JAN'],
  );

  test('avance de ma réplique à la suivante, en traversant les unités', () => {
    assert.equal(repliqueVoisine(index, jan2.id, 1), jan3.id);
  });

  test('recule', () => {
    assert.equal(repliqueVoisine(index, jan2.id, -1), jan1.id);
  });

  test('sans position, part du début ou de la fin', () => {
    assert.equal(repliqueVoisine(index, null, 1), jan1.id);
    assert.equal(repliqueVoisine(index, null, -1), jan3.id);
  });

  test('aux extrémités, rend null', () => {
    assert.equal(repliqueVoisine(index, jan3.id, 1), null);
    assert.equal(repliqueVoisine(index, jan1.id, -1), null);
  });

  test('un identifiant inconnu ramène au début plutôt que de casser', () => {
    assert.equal(repliqueVoisine(index, 'r_inexistant', 1), jan1.id);
  });

  test('sans réplique à moi, rend null', () => {
    const vide = indexer(piece([unite('u1', [r('AUTRE', 'x')])]), ['JAN']);

    assert.equal(repliqueVoisine(vide, null, 1), null);
  });
});

describe('recherche', () => {
  const index = indexer(
    piece([
      unite('u1', [r('JAN', 'Je ne crois pas qu’elle réponde.')]),
      unite('u2', [r('AUTRE', 'Une auberge, le soir.')]),
    ]),
    ['JAN'],
  );

  test('trouve malgré accents et casse', () => {
    const trouves = chercher(index, 'REPONDE');

    assert.equal(trouves.length, 1);
    assert.deepEqual(trouves[0].personnages, ['JAN']);
    assert.equal(trouves[0].unite, 'u1');
  });

  test('cherche aussi dans les répliques des autres', () => {
    // On cherche dans la pièce, pas seulement dans son rôle.
    assert.equal(chercher(index, 'auberge').length, 1);
  });

  test('un fragment absent ne rend rien', () => {
    assert.deepEqual(chercher(index, 'zzz'), []);
  });

  test('un fragment vide ne rend rien', () => {
    assert.deepEqual(chercher(index, '  '), []);
  });
});

describe('statut d’une unité', () => {
  const jan1 = r('JAN', 'Un.');
  const jan2 = r('JAN', 'Deux.');
  const index = indexer(
    piece([unite('u1', [jan1, r('AUTRE', 'a'), jan2]), unite('u2', [r('AUTRE', 'b')])]),
    ['JAN'],
  );

  test('sans progression, tout est à apprendre', () => {
    assert.equal(statutDUnite(index, 'u1', {}), STATUT.A_APPRENDRE);
  });

  test('le statut le plus faible l’emporte', () => {
    // Une scène dont une réplique reste à apprendre n'est pas maîtrisée aux
    // trois quarts : elle n'est pas maîtrisée.
    const progres = {
      [jan1.id]: { statut: STATUT.MAITRISEE },
      [jan2.id]: { statut: STATUT.EN_COURS },
    };

    assert.equal(statutDUnite(index, 'u1', progres), STATUT.EN_COURS);
  });

  test('tout maîtrisé donne maîtrisée', () => {
    const progres = {
      [jan1.id]: { statut: STATUT.MAITRISEE },
      [jan2.id]: { statut: STATUT.MAITRISEE },
    };

    assert.equal(statutDUnite(index, 'u1', progres), STATUT.MAITRISEE);
  });

  test('le statut des autres personnages est ignoré', () => {
    const progres = {
      [jan1.id]: { statut: STATUT.MAITRISEE },
      [jan2.id]: { statut: STATUT.MAITRISEE },
      r_autre: { statut: STATUT.A_APPRENDRE },
    };

    assert.equal(statutDUnite(index, 'u1', progres), STATUT.MAITRISEE);
  });

  test('une unité sans réplique à moi n’a pas de statut', () => {
    assert.equal(statutDUnite(index, 'u2', {}), null);
  });

  test('une unité inconnue n’a pas de statut', () => {
    assert.equal(statutDUnite(index, 'u404', {}), null);
  });

  test('un statut inconnu est traité comme « à apprendre »', () => {
    const progres = { [jan1.id]: { statut: 'inventé' } };

    assert.equal(statutDUnite(index, 'u1', progres), STATUT.A_APPRENDRE);
  });
});

describe('spot check', () => {
  const jan1 = r('JAN', 'Un.');
  const jan2 = r('JAN', 'Deux.');
  const jan3 = r('JAN', 'Trois.');
  const index = indexer(piece([unite('u1', [jan1, jan2, jan3])]), ['JAN']);

  const MAINTENANT = 1_000_000_000_000;
  const JOUR = 86_400_000;

  test('seules les répliques maîtrisées sont candidates', () => {
    const progres = {
      [jan1.id]: { statut: STATUT.MAITRISEE, verifiee_le: MAINTENANT },
      [jan2.id]: { statut: STATUT.EN_COURS },
    };

    const candidats = candidatsSpotCheck(index, progres, MAINTENANT);

    assert.deepEqual(
      candidats.map((c) => c.valeur),
      [jan1.id],
    );
  });

  test('la plus anciennement vérifiée pèse le plus lourd', () => {
    const progres = {
      [jan1.id]: { statut: STATUT.MAITRISEE, verifiee_le: MAINTENANT - JOUR },
      [jan2.id]: { statut: STATUT.MAITRISEE, verifiee_le: MAINTENANT - 30 * JOUR },
    };

    const parId = Object.fromEntries(
      candidatsSpotCheck(index, progres, MAINTENANT).map((c) => [c.valeur, c.poids]),
    );

    assert.ok(parId[jan2.id] > parId[jan1.id]);
  });

  test('une réplique vérifiée à l’instant reste tirable', () => {
    // Un poids nul la rendrait impossible à tirer, alors qu'elle doit seulement
    // être improbable.
    const progres = {
      [jan1.id]: { statut: STATUT.MAITRISEE, verifiee_le: MAINTENANT },
    };

    assert.ok(candidatsSpotCheck(index, progres, MAINTENANT)[0].poids > 0);
  });

  test('jamais vérifiée pèse plus que vérifiée il y a un mois', () => {
    // C'est la plus incertaine de toutes.
    const progres = {
      [jan1.id]: { statut: STATUT.MAITRISEE },
      [jan2.id]: { statut: STATUT.MAITRISEE, verifiee_le: MAINTENANT - 30 * JOUR },
    };

    const parId = Object.fromEntries(
      candidatsSpotCheck(index, progres, MAINTENANT).map((c) => [c.valeur, c.poids]),
    );

    assert.ok(parId[jan1.id] > parId[jan2.id]);
  });

  test('aucune réplique maîtrisée : aucun candidat', () => {
    assert.deepEqual(candidatsSpotCheck(index, {}, MAINTENANT), []);
  });
});

describe('fusionner deux progressions', () => {
  test('le statut le plus avancé gagne, dans les deux sens', () => {
    const a = { r_1: { statut: STATUT.MAITRISEE } };
    const b = { r_1: { statut: STATUT.A_APPRENDRE } };

    assert.equal(fusionnerProgres(a, b).r_1.statut, STATUT.MAITRISEE);
    assert.equal(fusionnerProgres(b, a).r_1.statut, STATUT.MAITRISEE);
  });

  test('rien ne disparaît', () => {
    const fusion = fusionnerProgres(
      { r_local: { statut: STATUT.EN_COURS } },
      { r_importe: { statut: STATUT.MAITRISEE } },
    );

    assert.deepEqual(Object.keys(fusion).sort(), ['r_importe', 'r_local']);
  });

  test('les historiques sont réunis, pas remplacés', () => {
    // Le cahier disait « le plus long gagne » ; l'union tient la même promesse
    // et perd strictement moins.
    const fusion = fusionnerProgres(
      { r_1: { scores: [{ le: 100, score: 60 }] } },
      { r_1: { scores: [{ le: 200, score: 90 }] } },
    );

    assert.equal(fusion.r_1.scores.length, 2);
  });

  test('les doublons de date sont écartés', () => {
    const fusion = fusionnerProgres(
      { r_1: { scores: [{ le: 100, score: 60 }] } },
      { r_1: { scores: [{ le: 100, score: 60 }] } },
    );

    assert.equal(fusion.r_1.scores.length, 1);
  });

  test('l’historique est trié du plus récent au plus ancien', () => {
    const fusion = fusionnerProgres(
      { r_1: { scores: [{ le: 100, score: 60 }] } },
      { r_1: { scores: [{ le: 300, score: 90 }, { le: 200, score: 70 }] } },
    );

    assert.deepEqual(
      fusion.r_1.scores.map((s) => s.le),
      [300, 200, 100],
    );
  });

  test('le plafond sacrifie l’ancien, jamais le dernier score', () => {
    const scores = [1, 2, 3, 4, 5].map((n) => ({ le: n * 100, score: n }));
    const fusion = fusionnerProgres({ r_1: { scores } }, {}, 2);

    assert.deepEqual(
      fusion.r_1.scores.map((s) => s.le),
      [500, 400],
    );
  });

  test('la date de vérification la plus récente gagne', () => {
    const fusion = fusionnerProgres(
      { r_1: { verifiee_le: 100 } },
      { r_1: { verifiee_le: 500 } },
    );

    assert.equal(fusion.r_1.verifiee_le, 500);
  });

  test('sans date de vérification, le champ est absent', () => {
    // Plutôt qu'un -Infinity qui ne survivrait pas à JSON.stringify.
    const fusion = fusionnerProgres({ r_1: { statut: STATUT.EN_COURS } }, {});

    assert.ok(!('verifiee_le' in fusion.r_1));
  });

  test('une entrée de score mal formée est écartée', () => {
    const fusion = fusionnerProgres(
      { r_1: { scores: [null, { le: 'hier' }, { score: 90 }, { le: 1, score: 50 }] } },
      {},
    );

    assert.deepEqual(fusion.r_1.scores, [{ le: 1, score: 50 }]);
  });

  test('fusionner avec rien rend une progression normalisée', () => {
    const fusion = fusionnerProgres({ r_1: { statut: STATUT.MAITRISEE } });

    assert.equal(fusion.r_1.statut, STATUT.MAITRISEE);
    assert.deepEqual(fusion.r_1.scores, []);
  });

  test('deux vides donnent un vide', () => {
    assert.deepEqual(fusionnerProgres(), {});
  });
});

describe('bilan', () => {
  const jan1 = r('JAN', 'Un.');
  const jan2 = r('JAN', 'Deux.');
  const index = indexer(piece([unite('u1', [jan1, jan2, r('AUTRE', 'x')])]), ['JAN']);

  test('compte par statut, sur mes seules répliques', () => {
    const progres = { [jan1.id]: { statut: STATUT.MAITRISEE } };

    assert.deepEqual(bilan(index, progres), {
      total: 2,
      [STATUT.A_APPRENDRE]: 1,
      [STATUT.EN_COURS]: 0,
      [STATUT.A_REVISER]: 0,
      [STATUT.MAITRISEE]: 1,
    });
  });

  test('la somme des statuts fait le total', () => {
    const resultat = bilan(index, {});
    const somme =
      resultat[STATUT.A_APPRENDRE] +
      resultat[STATUT.EN_COURS] +
      resultat[STATUT.A_REVISER] +
      resultat[STATUT.MAITRISEE];

    assert.equal(somme, resultat.total);
  });
});


describe('répétition espacée — statut déduit des scores', () => {
  const JOUR = 86400000;
  const T = 1_800_000_000_000;
  const REGLES = { seuil: 90, reussitesPourMaitrise: 3, intervallesJours: [7, 16, 35] };

  const scores = (...entrees) => ({
    scores: entrees.map(([jours, score]) => ({ le: T - jours * JOUR, score })),
  });

  test('sans historique, à apprendre', () => {
    assert.equal(statutDepuisScores({}, T, REGLES), STATUT.A_APPRENDRE);
    assert.equal(statutDepuisScores(undefined, T, REGLES), STATUT.A_APPRENDRE);
  });

  test('des tentatives sans réussite : en cours', () => {
    const suivi = scores([1, 40], [2, 70], [3, 89]);

    assert.equal(statutDepuisScores(suivi, T, REGLES), STATUT.EN_COURS);
  });

  test('le seuil est inclusif', () => {
    // 90 exactement est une réussite : un seuil qu'on n'atteint jamais tout à
    // fait serait décourageant sans raison.
    const suivi = scores([1, 90], [2, 90], [3, 90]);

    assert.equal(statutDepuisScores(suivi, T, REGLES), STATUT.MAITRISEE);
  });

  test('deux réussites ne suffisent pas', () => {
    const suivi = scores([1, 95], [2, 92]);

    assert.equal(statutDepuisScores(suivi, T, REGLES), STATUT.EN_COURS);
  });

  test('trois réussites récentes : sue', () => {
    const suivi = scores([0, 95], [1, 92], [2, 99]);

    assert.equal(statutDepuisScores(suivi, T, REGLES), STATUT.MAITRISEE);
  });

  test('passé l’échéance, la maîtrise expire en « à réviser »', () => {
    // C'est le ressort de la règle : sue autrefois n'est pas sue aujourd'hui.
    const suivi = scores([8, 95], [9, 92], [10, 99]);

    assert.equal(statutDepuisScores(suivi, T, REGLES), STATUT.A_REVISER);
  });

  test('« à réviser » se distingue d’« en cours »', () => {
    // Une réplique sue trois fois puis oubliée ne demande pas le même travail
    // qu'une réplique jamais réussie : les confondre ferait réapprendre ce qu'il
    // suffit de rafraîchir.
    const oubliee = scores([30, 95], [31, 95], [32, 95]);
    const jamaisSue = scores([1, 50], [2, 60]);

    assert.equal(statutDepuisScores(oubliee, T, REGLES), STATUT.A_REVISER);
    assert.equal(statutDepuisScores(jamaisSue, T, REGLES), STATUT.EN_COURS);
  });

  test('chaque réussite supplémentaire repousse l’échéance', () => {
    // Trois réussites : sept jours. Quatre : seize. C'est l'espacement.
    const troisFois = scores([10, 95], [11, 95], [12, 95]);
    const quatreFois = scores([10, 95], [11, 95], [12, 95], [13, 95]);

    assert.equal(statutDepuisScores(troisFois, T, REGLES), STATUT.A_REVISER);
    assert.equal(statutDepuisScores(quatreFois, T, REGLES), STATUT.MAITRISEE);
  });

  test('l’intervalle plafonne', () => {
    // Dix réussites ne donnent pas dix ans : une pièce se joue dans l'année.
    const beaucoup = { scores: Array.from({ length: 10 }, (_, i) => ({
      le: T - (i + 40) * JOUR, score: 95,
    })) };

    assert.equal(statutDepuisScores(beaucoup, T, REGLES), STATUT.A_REVISER);
  });

  test('un échec récent défait une maîtrise valide', () => {
    // C'est la dernière récitation qui dit où en est la mémoire, pas la moyenne
    // d'un passé flatteur.
    const suivi = scores([0, 40], [1, 95], [2, 95], [3, 95]);

    assert.equal(statutDepuisScores(suivi, T, REGLES), STATUT.A_REVISER);
  });

  test('un échec rompt la série : une seule réussite ne suffit pas à revenir', () => {
    // Sans cela, un raté suivi d'une réussite restaurerait la maîtrise
    // instantanément — la série compte, pas le total.
    const suivi = scores([0, 95], [1, 40], [2, 95], [3, 95], [4, 95]);

    assert.equal(statutDepuisScores(suivi, T, REGLES), STATUT.A_REVISER);
  });

  test('trois réussites après l’échec rétablissent la maîtrise', () => {
    const suivi = scores([0, 95], [1, 95], [2, 95], [3, 40], [4, 95], [5, 95]);

    assert.equal(statutDepuisScores(suivi, T, REGLES), STATUT.MAITRISEE);
  });

  test('un échec sur une réplique jamais sue la laisse en cours', () => {
    // « À réviser » suppose une maîtrise passée : sans elle, il n'y a rien à
    // réviser, il y a à apprendre.
    const suivi = scores([0, 40], [1, 60]);

    assert.equal(statutDepuisScores(suivi, T, REGLES), STATUT.EN_COURS);
  });

  test('une validation manuelle répare la série', () => {
    // C'est l'usage même du bouton « c'était juste » : la transcription a
    // faussement rompu une série.
    const rompue = scores([0, 55], [1, 95], [2, 95], [3, 95]);
    const reparee = {
      scores: rompue.scores.map((e, i) => (i === 0 ? { ...e, corrige: true } : e)),
    };

    assert.equal(statutDepuisScores(rompue, T, REGLES), STATUT.A_REVISER);
    assert.equal(statutDepuisScores(reparee, T, REGLES), STATUT.MAITRISEE);
  });

  test('l’échéance suit la série, non le total des réussites', () => {
    // Six réussites dont la série n'en compte que trois : sept jours, pas
    // trente-cinq.
    const suivi = scores([8, 95], [9, 95], [10, 95], [11, 40], [12, 95], [13, 95], [14, 95]);

    assert.equal(statutDepuisScores(suivi, T, REGLES), STATUT.A_REVISER);
  });

  test('une entrée mal formée est ignorée', () => {
    const suivi = { scores: [null, { le: T }, { score: 95 }, { le: T, score: 95 }] };

    assert.equal(statutDepuisScores(suivi, T, REGLES), STATUT.EN_COURS);
  });
});

describe('prochaineRevision', () => {
  const JOUR = 86400000;
  const T = 1_800_000_000_000;
  const REGLES = { seuil: 90, reussitesPourMaitrise: 3, intervallesJours: [7, 16, 35] };

  test('null tant que la réplique n’est pas sue', () => {
    assert.equal(prochaineRevision({ scores: [{ le: T, score: 95 }] }, REGLES), null);
  });

  test('null quand la série est rompue, même après une maîtrise passée', () => {
    const suivi = {
      scores: [
        { le: T, score: 40 },
        { le: T - JOUR, score: 95 },
        { le: T - 2 * JOUR, score: 95 },
        { le: T - 3 * JOUR, score: 95 },
      ],
    };

    assert.equal(prochaineRevision(suivi, REGLES), null);
  });

  test('sept jours après la dernière réussite, à trois réussites', () => {
    const suivi = { scores: [T, T - JOUR, T - 2 * JOUR].map((le) => ({ le, score: 95 })) };

    assert.equal(prochaineRevision(suivi, REGLES), T + 7 * JOUR);
  });
});

describe('ajouterScore', () => {
  const T = 1_800_000_000_000;

  test('ajoute sans modifier l’original', () => {
    const avant = { scores: [{ le: T - 1000, score: 50 }] };
    const apres = ajouterScore(avant, 95, T, 10);

    assert.equal(avant.scores.length, 1);
    assert.equal(apres.scores.length, 2);
  });

  test('le plus récent d’abord', () => {
    const apres = ajouterScore({ scores: [{ le: T - 1000, score: 50 }] }, 95, T, 10);

    assert.equal(apres.scores[0].score, 95);
  });

  test('le plafond sacrifie l’ancien, jamais le nouveau', () => {
    const anciens = { scores: [3, 2, 1].map((n) => ({ le: T - n * 1000, score: n })) };
    const apres = ajouterScore(anciens, 95, T, 2);

    assert.equal(apres.scores.length, 2);
    assert.equal(apres.scores[0].score, 95);
  });

  test('la date de vérification est posée', () => {
    assert.equal(ajouterScore({}, 95, T, 10).verifiee_le, T);
  });
});


describe('validation manuelle d’une récitation', () => {
  const JOUR = 86400000;
  const T = 1_800_000_000_000;
  const REGLES = { seuil: 90, reussitesPourMaitrise: 3, intervallesJours: [7, 16, 35] };

  test('une entrée corrigée compte comme réussie malgré son score', () => {
    // La transcription vocale n'est pas fiable : un score bas ne prouve pas un
    // oubli, et sans ce recours l'outil mesurerait la transcription.
    const suivi = { scores: [{ le: T, score: 62, corrige: true }] };
    const brut = { scores: [{ le: T, score: 62 }] };

    assert.equal(statutDepuisScores(suivi, T, REGLES), STATUT.EN_COURS);
    assert.equal(statutDepuisScores(brut, T, REGLES), STATUT.EN_COURS);

    // Une seule ne suffit pas ; trois corrigées, oui.
    const trois = {
      scores: [0, 1, 2].map((n) => ({ le: T - n * JOUR, score: 55, corrige: true })),
    };

    assert.equal(statutDepuisScores(trois, T, REGLES), STATUT.MAITRISEE);
  });

  test('le score mesuré est conservé', () => {
    // Écrire 100 % effacerait la trace de ce que l'outil a réellement entendu.
    const apres = corrigerDerniereRecitation({ scores: [{ le: T, score: 62 }] });

    assert.equal(apres.scores[0].score, 62);
    assert.equal(apres.scores[0].corrige, true);
  });

  test('seule la plus récente est corrigée', () => {
    const apres = corrigerDerniereRecitation({
      scores: [
        { le: T - JOUR, score: 40 },
        { le: T, score: 62 },
      ],
    });
    const parDate = Object.fromEntries(apres.scores.map((e) => [e.le, e.corrige]));

    assert.equal(parDate[T], true);
    assert.equal(parDate[T - JOUR], undefined);
  });

  test('idempotente', () => {
    const une = corrigerDerniereRecitation({ scores: [{ le: T, score: 62 }] });
    const deux = corrigerDerniereRecitation(une);

    assert.deepEqual(deux.scores, une.scores);
  });

  test('sans historique, ne casse pas', () => {
    assert.deepEqual(corrigerDerniereRecitation({}).scores, undefined);
    assert.doesNotThrow(() => corrigerDerniereRecitation(undefined));
  });

  test('l’original n’est pas modifié', () => {
    const avant = { scores: [{ le: T, score: 62 }] };
    corrigerDerniereRecitation(avant);

    assert.equal(avant.scores[0].corrige, undefined);
  });

  test('une correction compte aussi pour la prochaine révision', () => {
    const suivi = {
      scores: [0, 1, 2].map((n) => ({ le: T - n * JOUR, score: 55, corrige: true })),
    };

    assert.equal(prochaineRevision(suivi, REGLES), T + 7 * JOUR);
  });
});

describe('difficulte', () => {
  const T = 1_800_000_000_000;
  const JOUR = 86400000;

  test('une reponse parfaite et fraiche donne zero', () => {
    const suivi = { scores: [{ le: T, score: 100 }], verifiee_le: T };

    assert.equal(difficulte(suivi, T).difficulte, 0);
  });

  test('jamais recitee vaut le maximum', () => {
    // Les deux termes sont au plus haut : on ne sait rien, et depuis toujours.
    assert.equal(difficulte(undefined, T).difficulte, 1);
    assert.equal(difficulte({ scores: [] }, T).difficulte, 1);
  });

  test('le dernier score compte, non la moyenne', () => {
    // Trois reussites puis un echec : c'est l'echec qui doit peser, exactement
    // comme pour le statut. Une moyenne donnerait 0,225 de faiblesse au lieu de 0,9.
    const suivi = {
      scores: [
        { le: T, score: 10 },
        { le: T - JOUR, score: 100 },
        { le: T - 2 * JOUR, score: 100 },
        { le: T - 3 * JOUR, score: 100 },
      ],
      verifiee_le: T,
    };

    assert.equal(difficulte(suivi, T).score, 10);
    assert.equal(
      Math.round(difficulte(suivi, T).difficulte * 1000) / 1000,
      REVISION.POIDS_FAIBLESSE * 0.9,
    );
  });

  test('l anciennete plafonne a l horizon', () => {
    // Sans plafond, une replique tres vieille ecraserait toute la file.
    const vieille = { scores: [{ le: T, score: 100 }], verifiee_le: T };
    const auHorizon = difficulte(vieille, T + REVISION.HORIZON_JOURS * JOUR);
    const bienApres = difficulte(vieille, T + 300 * JOUR);

    assert.equal(auHorizon.difficulte, REVISION.POIDS_ANCIENNETE);
    assert.equal(bienApres.difficulte, auHorizon.difficulte);
  });

  test('un score futur ou negatif ne sort pas des bornes', () => {
    // Le score vient d'un calcul, donc d'un possible defaut : la difficulte doit
    // rester dans [0, 1] quoi qu'on lui donne.
    for (const score of [-50, 0, 50, 100, 150]) {
      const d = difficulte({ scores: [{ le: T, score }], verifiee_le: T }, T).difficulte;

      assert.ok(d >= 0 && d <= 1, `hors bornes pour ${score} : ${d}`);
    }

    // Une date dans le futur ne doit pas rendre l'anciennete negative.
    assert.equal(
      difficulte({ scores: [{ le: T, score: 100 }], verifiee_le: T + JOUR }, T)
        .difficulte,
      0,
    );
  });
});

describe('filePrioritaire', () => {
  const T = 1_800_000_000_000;
  const JOUR = 86400000;

  /** Index minimal : seul `mesRepliques` compte ici. */
  const index = { mesRepliques: ['a', 'b', 'c', 'd'] };

  test('les plus difficiles sortent en tete', () => {
    const progres = {
      a: { scores: [{ le: T, score: 100 }], verifiee_le: T, statut: STATUT.MAITRISEE },
      b: { scores: [{ le: T, score: 20 }], verifiee_le: T, statut: STATUT.EN_COURS },
      c: {
        scores: [{ le: T - 60 * JOUR, score: 100 }],
        verifiee_le: T - 60 * JOUR,
        statut: STATUT.A_REVISER,
      },
      // `d` n'a jamais ete recitee : elle passe devant tout le monde.
    };

    assert.deepEqual(
      filePrioritaire(index, progres, T).map((e) => e.id),
      ['d', 'b', 'c', 'a'],
    );
  });

  test('l ordre de jeu tranche les egalites', () => {
    // Aucune replique recitee : toutes a 1. La file doit alors rendre l'ordre de
    // la piece, et non un ordre imprevisible qui changerait a chaque ouverture.
    const file = filePrioritaire(index, {}, T);

    assert.deepEqual(file.map((e) => e.id), ['a', 'b', 'c', 'd']);
    assert.ok(file.every((e) => e.difficulte === 1));
  });

  test('chaque entree porte de quoi expliquer son rang', () => {
    // L'interface doit pouvoir dire *pourquoi* une replique est la : sans cela,
    // l'ordre parait arbitraire et l'on cesse de s'y fier.
    const progres = {
      a: { scores: [{ le: T - 3 * JOUR, score: 40 }], verifiee_le: T - 3 * JOUR },
    };
    const entree = filePrioritaire(index, progres, T).find((e) => e.id === 'a');

    assert.equal(entree.score, 40);
    assert.equal(Math.round(entree.jours), 3);
    assert.equal(entree.statut, STATUT.A_APPRENDRE, 'statut par defaut si absent');
  });

  test('toutes mes repliques figurent dans la file, une seule fois', () => {
    // Une file qui perd des repliques laisserait des trous invisibles : on
    // croirait avoir tout revu.
    const ids = filePrioritaire(index, {}, T).map((e) => e.id);

    assert.equal(ids.length, index.mesRepliques.length);
    assert.deepEqual([...new Set(ids)].sort(), [...index.mesRepliques].sort());
  });
});
