/**
 * Tests de `js/tirage.js`.
 *
 * Le point de ce module est la **reproductibilité**. Ces tests vérifient donc
 * surtout qu'il ne se comporte pas comme `Math.random()` : même graine, même
 * résultat, toujours.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import {
  generateur,
  graineDepuis,
  graineReplique,
  motsAMasquer,
  tirerIndices,
  tirerPondere,
} from '../js/tirage.js';

describe('graine', () => {
  test('la même chaîne donne la même graine', () => {
    assert.equal(graineDepuis('r_abc|45|0'), graineDepuis('r_abc|45|0'));
  });

  test('deux chaînes proches donnent des graines différentes', () => {
    assert.notEqual(graineDepuis('r_abc|45|0'), graineDepuis('r_abc|45|1'));
    assert.notEqual(graineDepuis('r_abc|45|0'), graineDepuis('r_abd|45|0'));
  });

  test('la graine est un entier non signé sur 32 bits', () => {
    for (const texte of ['', 'a', 'une réplique entière avec des accents é']) {
      const graine = graineDepuis(texte);

      assert.ok(Number.isInteger(graine), `${texte} → ${graine}`);
      assert.ok(graine >= 0 && graine <= 0xffffffff);
    }
  });

  test('la graine d’une réplique dépend du passage', () => {
    // C'est ce qui fait fonctionner « nouveau tirage ».
    assert.notEqual(graineReplique('r_a', 45, 0), graineReplique('r_a', 45, 1));
  });

  test('la graine d’une réplique dépend de la difficulté', () => {
    assert.notEqual(graineReplique('r_a', 45, 0), graineReplique('r_a', 60, 0));
  });
});

describe('generateur', () => {
  test('deux générateurs de même graine donnent la même suite', () => {
    const a = generateur(1234);
    const b = generateur(1234);

    for (let i = 0; i < 20; i += 1) {
      assert.equal(a(), b());
    }
  });

  test('les valeurs restent dans [0, 1)', () => {
    const suivant = generateur(graineDepuis('quelconque'));

    for (let i = 0; i < 500; i += 1) {
      const valeur = suivant();

      assert.ok(valeur >= 0 && valeur < 1, `hors bornes : ${valeur}`);
    }
  });

  test('la suite ne stagne pas', () => {
    const suivant = generateur(7);
    const valeurs = new Set(Array.from({ length: 50 }, () => suivant()));

    assert.ok(valeurs.size > 40, `trop de doublons : ${valeurs.size}/50`);
  });
});

describe('tirerIndices', () => {
  test('rend le nombre demandé, sans doublon, trié', () => {
    const indices = tirerIndices(20, 5, 42);

    assert.equal(indices.length, 5);
    assert.equal(new Set(indices).size, 5);
    assert.deepEqual(indices, [...indices].sort((a, b) => a - b));
  });

  test('tous les indices sont dans les bornes', () => {
    for (const indice of tirerIndices(10, 10, 99)) {
      assert.ok(indice >= 0 && indice < 10);
    }
  });

  test('reproductible à graine égale', () => {
    assert.deepEqual(tirerIndices(30, 8, 5), tirerIndices(30, 8, 5));
  });

  test('différent à graine différente', () => {
    assert.notDeepEqual(tirerIndices(30, 8, 5), tirerIndices(30, 8, 6));
  });

  test('demander plus que disponible rend tout, sans boucler', () => {
    // Le prototype bouclait jusqu'à 500 fois avec rejet, ce qui rendait le
    // résultat dépendant du nombre d'essais dès que la difficulté approchait
    // 100 %. Ici, la totalité est rendue franchement.
    assert.deepEqual(tirerIndices(3, 10, 1), [0, 1, 2]);
  });

  test('les cas dégénérés rendent une liste vide', () => {
    assert.deepEqual(tirerIndices(0, 5, 1), []);
    assert.deepEqual(tirerIndices(5, 0, 1), []);
    assert.deepEqual(tirerIndices(-1, 5, 1), []);
  });
});

describe('motsAMasquer', () => {
  test('respecte approximativement le pourcentage demandé', () => {
    assert.equal(motsAMasquer(100, 45, 1).length, 45);
    assert.equal(motsAMasquer(20, 50, 1).length, 10);
  });

  test('masque toujours au moins un mot', () => {
    // À 5 % sur trois mots, zéro trou ferait paraître le mode cassé.
    assert.equal(motsAMasquer(3, 5, 1).length, 1);
    assert.equal(motsAMasquer(1, 1, 1).length, 1);
  });

  test('à 100 %, tous les mots sont masqués', () => {
    assert.equal(motsAMasquer(7, 100, 1).length, 7);
  });

  test('sur un texte vide, rien à masquer', () => {
    assert.deepEqual(motsAMasquer(0, 45, 1), []);
  });

  test('stable pour une même réplique et un même réglage', () => {
    // C'est le défaut central du prototype : les trous se déplaçaient à chaque
    // rendu, empêchant le travail qu'on cherche à faire.
    const graine = graineReplique('r_8f3a1c', 45, 0);

    assert.deepEqual(motsAMasquer(25, 45, graine), motsAMasquer(25, 45, graine));
  });

  test('un nouveau tirage change les trous', () => {
    const premier = motsAMasquer(25, 45, graineReplique('r_8f3a1c', 45, 0));
    const second = motsAMasquer(25, 45, graineReplique('r_8f3a1c', 45, 1));

    assert.notDeepEqual(premier, second);
  });

  test('deux répliques différentes ne masquent pas les mêmes positions', () => {
    const a = motsAMasquer(25, 45, graineReplique('r_aaa', 45, 0));
    const b = motsAMasquer(25, 45, graineReplique('r_bbb', 45, 0));

    assert.notDeepEqual(a, b);
  });
});

describe('tirerPondere', () => {
  test('reproductible à graine égale', () => {
    const candidats = [
      { valeur: 'a', poids: 1 },
      { valeur: 'b', poids: 5 },
      { valeur: 'c', poids: 2 },
    ];

    assert.equal(tirerPondere(candidats, 7), tirerPondere(candidats, 7));
  });

  test('un poids nul n’est jamais tiré', () => {
    const candidats = [
      { valeur: 'jamais', poids: 0 },
      { valeur: 'toujours', poids: 1 },
    ];

    for (let graine = 0; graine < 50; graine += 1) {
      assert.equal(tirerPondere(candidats, graine), 'toujours');
    }
  });

  test('le poids fort sort plus souvent', () => {
    // C'est ce qui fait que le spot check propose d'abord la réplique vue le
    // plus anciennement, au lieu de redemander celle qu'on vient de vérifier.
    const candidats = [
      { valeur: 'rare', poids: 1 },
      { valeur: 'fréquent', poids: 99 },
    ];

    let frequents = 0;

    for (let graine = 0; graine < 200; graine += 1) {
      if (tirerPondere(candidats, graine) === 'fréquent') {
        frequents += 1;
      }
    }

    assert.ok(frequents > 150, `seulement ${frequents}/200`);
  });

  test('une liste vide ou tout à zéro rend null', () => {
    assert.equal(tirerPondere([], 1), null);
    assert.equal(tirerPondere([{ valeur: 'x', poids: 0 }], 1), null);
  });
});
