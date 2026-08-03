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
  bilan,
  candidatsSpotCheck,
  chercher,
  fusionnerProgres,
  indexer,
  MOTIF_SANS_TOP,
  repliqueVoisine,
  statutDUnite,
  STATUT,
  texteDuTop,
  titreDUnite,
  TOP,
} from '../js/modele.js';

let compteur = 0;

/** Réplique minimale, identifiant automatique. */
function r(personnage, texte) {
  compteur += 1;

  return {
    type: 'replique',
    id: `r_${compteur}`,
    personnage,
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
        elements.filter((e) => e.type === 'replique').map((e) => e.personnage),
      ),
    ],
    elements,
    ...extra,
  };
}

function piece(unites, personnages = []) {
  return { schema: 'repetition/1', piece: 'Essai', personnages, unites };
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
    assert.equal(top.personnage, 'AUTRE');
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
    assert.equal(top.personnage, 'AUTRE');
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
    assert.equal(top.personnage, 'TIERS');
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
    assert.equal(trouves[0].personnage, 'JAN');
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
      [STATUT.MAITRISEE]: 1,
    });
  });

  test('la somme des statuts fait le total', () => {
    const resultat = bilan(index, {});
    const somme =
      resultat[STATUT.A_APPRENDRE] +
      resultat[STATUT.EN_COURS] +
      resultat[STATUT.MAITRISEE];

    assert.equal(somme, resultat.total);
  });
});
