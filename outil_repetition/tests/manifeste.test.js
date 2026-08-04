/**
 * Tests de `js/manifeste.js`.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { piecesNonImportees } from '../js/manifeste.js';

const ID = (titre) => titre.toLowerCase().replace(/\s+/g, '-');

describe('piecesNonImportees', () => {
  test('une pièce absente du stockage est retenue', () => {
    const manifeste = { pieces: [{ fichier: 'A_REPET.json', piece: 'Piece A' }] };

    const resultat = piecesNonImportees(manifeste, [], ID);

    assert.deepEqual(resultat, [{ fichier: 'A_REPET.json', piece: 'Piece A' }]);
  });

  test('une pièce déjà enregistrée est écartée', () => {
    const manifeste = { pieces: [{ fichier: 'A_REPET.json', piece: 'Piece A' }] };
    const enregistrees = [{ id: 'piece-a' }];

    assert.deepEqual(piecesNonImportees(manifeste, enregistrees, ID), []);
  });

  test('seules les pièces non enregistrées sont retenues, dans leur ordre', () => {
    const manifeste = {
      pieces: [
        { fichier: 'A_REPET.json', piece: 'Piece A' },
        { fichier: 'B_REPET.json', piece: 'Piece B' },
        { fichier: 'C_REPET.json', piece: 'Piece C' },
      ],
    };
    const enregistrees = [{ id: 'piece-b' }];

    const resultat = piecesNonImportees(manifeste, enregistrees, ID);

    assert.deepEqual(
      resultat.map((p) => p.piece),
      ['Piece A', 'Piece C'],
    );
  });

  test('un manifeste absent (null) ne rend aucune pièce', () => {
    assert.deepEqual(piecesNonImportees(null, [], ID), []);
  });

  test('un manifeste sans champ « pieces » ne rend aucune pièce', () => {
    assert.deepEqual(piecesNonImportees({}, [], ID), []);
  });

  test('un manifeste vide ne rend aucune pièce', () => {
    assert.deepEqual(piecesNonImportees({ pieces: [] }, [], ID), []);
  });
});
