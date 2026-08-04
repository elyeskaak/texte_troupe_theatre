/**
 * Tests de `js/schema.js`.
 *
 * Un `REPET.json` est produit par une machine : ces tests ne cherchent donc pas
 * la faute de frappe, ils vérifient qu'une **désynchronisation de version** ou
 * un fichier tronqué sont refusés clairement, plutôt qu'acceptés puis
 * interprétés au mieux.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { repliques, valider, REMEDE } from '../js/schema.js';
import { CONFIG } from '../js/config.js';

/** Un document minimal mais valide. */
function piece(surcharges = {}) {
  return {
    schema: CONFIG.SCHEMA_ACCEPTE,
    piece: 'Le Malentendu',
    personnages: [{ nom: 'JAN', repliques: 1, mots: 4 }],
    unites: [
      {
        id: 'u001',
        acte: 'ACTE PREMIER',
        scene: null,
        implicite: false,
        personnages: ['JAN'],
        elements: [
          { type: 'lieu', texte: 'Une auberge.' },
          {
            type: 'replique',
            id: 'r_aaa',
            personnages: ['JAN'],
            texte: 'Nous y sommes enfin.',
            vers: false,
          },
        ],
      },
    ],
    ...surcharges,
  };
}

describe('un document conforme est accepté', () => {
  test('valide, et rendu tel quel', () => {
    const resultat = valider(piece());

    assert.ok(resultat.valide);
    assert.equal(resultat.piece.piece, 'Le Malentendu');
  });

  test('les champs optionnels peuvent manquer', () => {
    // `avertissements`, `liminaires` et `genere_le` sont facultatifs : leur
    // absence ne doit pas empêcher de répéter.
    const minimal = piece();
    delete minimal.liminaires;

    assert.ok(valider(minimal).valide);
  });

  test('une didascalie interne bien formée passe', () => {
    const avecJeu = piece();
    avecJeu.unites[0].elements[1].didascalies_internes = [
      { avant_mot: 2, texte: 'elle se lève' },
    ];

    assert.ok(valider(avecJeu).valide);
  });
});

describe('version du schéma', () => {
  test('une version inconnue est refusée', () => {
    const resultat = valider(piece({ schema: 'repetition/1' }));

    assert.ok(!resultat.valide);
    assert.match(resultat.erreur, /repetition\/1/);
  });

  test('un fichier plus récent accuse la page, non le fichier', () => {
    // C'est le cas qui a réellement bloqué l'outil : le fichier était au schéma 2,
    // la page cachée en était restée au 1. Le message doit désigner la page, et le
    // remède doit permettre à l'interface d'offrir la purge du cache.
    const resultat = valider(piece({ schema: 'repetition/9' }));

    assert.ok(!resultat.valide);
    assert.equal(resultat.remede, REMEDE.PAGE_PERIMEE);
    assert.match(resultat.erreur, /plus récent/i);
    assert.match(resultat.erreur, /page.*en retard/i);
  });

  test('un fichier plus ancien accuse le fichier, non la page', () => {
    // Le sens inverse a la cause inverse : purger le cache n'y changerait rien, et
    // le proposer enverrait vers un geste inutile.
    const resultat = valider(piece({ schema: 'repetition/1' }));

    assert.equal(resultat.remede, REMEDE.FICHIER_PERIME);
    assert.match(resultat.erreur, /plus ancien/i);
    assert.match(resultat.erreur, /régénérez/i);
  });

  test('les deux sens ne donnent pas le même remède', () => {
    // L'ancien message conseillait « mettez la page à jour, ou régénérez le
    // fichier » — les deux à la fois, donc aucun. Ce test interdit d'y revenir.
    assert.notEqual(
      valider(piece({ schema: 'repetition/9' })).remede,
      valider(piece({ schema: 'repetition/1' })).remede,
    );
  });

  test('une forme étrangère n’est pas prise pour une version', () => {
    const resultat = valider(piece({ schema: 'lecture/1' }));

    assert.ok(!resultat.valide);
    assert.equal(resultat.remede, REMEDE.FICHIER_ETRANGER);
  });

  test('un schéma absent est refusé', () => {
    const sansSchema = piece();
    delete sansSchema.schema;

    const resultat = valider(sansSchema);

    assert.ok(!resultat.valide);
    assert.match(resultat.erreur, /schema/);
  });
});

describe('champs de premier niveau', () => {
  test('ce qui n’est pas un objet est refusé', () => {
    for (const valeur of [null, undefined, 42, 'texte', [], true]) {
      const resultat = valider(valeur);

      assert.ok(!resultat.valide, `accepté à tort : ${JSON.stringify(valeur)}`);
    }
  });

  test('« piece » vide est refusé', () => {
    assert.ok(!valider(piece({ piece: '   ' })).valide);
  });

  test('« unites » vide est refusé et le dit', () => {
    const resultat = valider(piece({ unites: [] }));

    assert.ok(!resultat.valide);
    assert.match(resultat.erreur, /aucun texte à répéter/);
  });

  test('« personnages » absent est refusé', () => {
    const sansPersonnages = piece();
    delete sansPersonnages.personnages;

    assert.ok(!valider(sansPersonnages).valide);
  });
});

describe('unités et éléments', () => {
  test('une unité sans identifiant est refusée', () => {
    const cassee = piece();
    delete cassee.unites[0].id;

    const resultat = valider(cassee);

    assert.ok(!resultat.valide);
    assert.match(resultat.erreur, /id/);
  });

  test('l’erreur situe l’unité fautive', () => {
    const cassee = piece();
    delete cassee.unites[0].elements;

    const resultat = valider(cassee);

    assert.match(resultat.erreur, /unité 1/);
    assert.match(resultat.erreur, /u001/);
  });

  test('un type d’élément inconnu est refusé', () => {
    const cassee = piece();
    cassee.unites[0].elements.push({ type: 'chanson', texte: 'la la' });

    const resultat = valider(cassee);

    assert.ok(!resultat.valide);
    assert.match(resultat.erreur, /chanson/);
  });

  test('une réplique sans texte est refusée', () => {
    const cassee = piece();
    delete cassee.unites[0].elements[1].texte;

    const resultat = valider(cassee);

    assert.ok(!resultat.valide);
    assert.match(resultat.erreur, /texte/);
  });

  test('une réplique sans identifiant est refusée', () => {
    const cassee = piece();
    delete cassee.unites[0].elements[1].id;

    assert.match(valider(cassee).erreur, /« id »/);
  });

  test('une réplique sans personnages est refusée', () => {
    const cassee = piece();
    delete cassee.unites[0].elements[1].personnages;

    assert.match(valider(cassee).erreur, /personnages/);
  });

  test('une réplique avec une liste de personnages vide est refusée', () => {
    const cassee = piece();
    cassee.unites[0].elements[1].personnages = [];

    assert.match(valider(cassee).erreur, /personnages/);
  });

  test('une réplique dite par plusieurs personnages est acceptée', () => {
    const collective = piece();
    collective.unites[0].elements[1].personnages = ['JAN', 'MARTHA'];

    assert.ok(valider(collective).valide);
  });

  test('une didascalie sans texte est refusée', () => {
    const cassee = piece();
    delete cassee.unites[0].elements[0].texte;

    assert.ok(!valider(cassee).valide);
  });

  test('une didascalie interne mal formée est refusée', () => {
    for (const mauvaise of [
      { texte: 'sans position' },
      { avant_mot: -1, texte: 'position négative' },
      { avant_mot: 1.5, texte: 'position fractionnaire' },
      { avant_mot: 2 },
    ]) {
      const cassee = piece();
      cassee.unites[0].elements[1].didascalies_internes = [mauvaise];

      assert.ok(
        !valider(cassee).valide,
        `acceptée à tort : ${JSON.stringify(mauvaise)}`,
      );
    }
  });
});

describe('cohérence globale', () => {
  test('deux identifiants de réplique identiques sont refusés', () => {
    // Le pire défaut possible : les statuts étant indexés par identifiant, deux
    // répliques homonymes partageraient silencieusement une progression.
    const cassee = piece();
    cassee.unites[0].elements.push({
      type: 'replique',
      id: 'r_aaa',
      personnages: ['MARTHA'],
      texte: 'Autre chose.',
      vers: false,
    });

    const resultat = valider(cassee);

    assert.ok(!resultat.valide);
    assert.match(resultat.erreur, /double/);
    assert.match(resultat.erreur, /r_aaa/);
  });

  test('un doublon entre deux unités est aussi détecté', () => {
    const cassee = piece();
    cassee.unites.push({
      id: 'u002',
      acte: null,
      scene: null,
      implicite: true,
      personnages: ['JAN'],
      elements: [
        {
          type: 'replique',
          id: 'r_aaa',
          personnages: ['JAN'],
          texte: 'Encore.',
          vers: false,
        },
      ],
    });

    assert.ok(!valider(cassee).valide);
  });

  test('un document sans aucune réplique est refusé', () => {
    const sansReplique = piece();
    sansReplique.unites[0].elements = [{ type: 'didascalie', texte: 'Pause.' }];

    const resultat = valider(sansReplique);

    assert.ok(!resultat.valide);
    assert.match(resultat.erreur, /rien à répéter/);
  });
});

describe('repliques', () => {
  test('rend les répliques dans l’ordre de jeu, avec leur unité', () => {
    const trouvees = repliques(piece());

    assert.equal(trouvees.length, 1);
    assert.equal(trouvees[0].id, 'r_aaa');
    assert.equal(trouvees[0].unite, 'u001');
  });

  test('les didascalies et lieux sont écartés', () => {
    assert.ok(repliques(piece()).every((r) => r.type === 'replique'));
  });
});
