/**
 * Tests de `../../pieces/drive.js`.
 *
 * Ne couvre que ce qui est pur ou injectable (§3.3 de `ARCHITECTURE.md`) :
 * construction d'URL, interprétation d'une réponse JSON, et les deux appels
 * réseau avec un `fetch` doublé. L'authentification, le chargement des
 * scripts Google et le Picker ne sont pas couverts ici — même statut que
 * `voix.js`, qui pilote de vraies API navigateur qu'aucune doublure ne
 * remplace fidèlement.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import {
  ErreurDrive,
  urlListeFichiers,
  urlContenuFichier,
  fichiersDepuisReponse,
  listerFichiers,
  lireFichier,
} from '../../pieces/drive.js';

describe('urlListeFichiers', () => {
  test('inclut le dossier, exclut la corbeille, filtre sur _REPET.json', () => {
    const url = new URL(urlListeFichiers('DOSSIER123'));
    const requete = url.searchParams.get('q');

    assert.equal(url.origin + url.pathname, 'https://www.googleapis.com/drive/v3/files');
    assert.match(requete, /'DOSSIER123' in parents/);
    assert.match(requete, /trashed = false/);
    assert.match(requete, /name contains '_REPET\.json'/);
  });

  test('demande seulement id et name', () => {
    const url = new URL(urlListeFichiers('X'));

    assert.equal(url.searchParams.get('fields'), 'files(id,name)');
  });
});

describe('urlContenuFichier', () => {
  test('cible le fichier avec alt=media', () => {
    assert.equal(
      urlContenuFichier('ABC'),
      'https://www.googleapis.com/drive/v3/files/ABC?alt=media',
    );
  });

  test('encode un identifiant contenant des caractères spéciaux', () => {
    assert.equal(
      urlContenuFichier('a/b c'),
      'https://www.googleapis.com/drive/v3/files/a%2Fb%20c?alt=media',
    );
  });
});

describe('fichiersDepuisReponse', () => {
  test('rend les fichiers valides tels quels', () => {
    const json = { files: [{ id: '1', name: 'A_REPET.json' }, { id: '2', name: 'B_REPET.json' }] };

    assert.deepEqual(fichiersDepuisReponse(json), json.files);
  });

  test('écarte un fichier sans id ou sans name', () => {
    const json = {
      files: [
        { id: '1', name: 'A_REPET.json' },
        { id: '2' },
        { name: 'sans-id_REPET.json' },
      ],
    };

    assert.deepEqual(fichiersDepuisReponse(json), [{ id: '1', name: 'A_REPET.json' }]);
  });

  test('une réponse sans champ « files » rend une liste vide', () => {
    assert.deepEqual(fichiersDepuisReponse({}), []);
  });

  test('une réponse non conforme (null, tableau, chaîne) rend une liste vide', () => {
    assert.deepEqual(fichiersDepuisReponse(null), []);
    assert.deepEqual(fichiersDepuisReponse([]), []);
    assert.deepEqual(fichiersDepuisReponse('oups'), []);
  });
});

/** Doublure minimale de `fetch`, conforme à ce que le module en attend. */
function faireFetch({ ok = true, status = 200, json = async () => ({}), text = async () => '' }) {
  return async () => ({ ok, status, json, text });
}

describe('listerFichiers', () => {
  test('rend les fichiers de la réponse', async () => {
    const fetchImpl = faireFetch({
      json: async () => ({ files: [{ id: '1', name: 'A_REPET.json' }] }),
    });

    const fichiers = await listerFichiers('jeton', 'dossier', fetchImpl);

    assert.deepEqual(fichiers, [{ id: '1', name: 'A_REPET.json' }]);
  });

  test('transmet le jeton en en-tête Authorization', async () => {
    let enteteRecue = null;
    const fetchImpl = async (_url, options) => {
      enteteRecue = options.headers.Authorization;
      return { ok: true, status: 200, json: async () => ({ files: [] }) };
    };

    await listerFichiers('mon-jeton', 'dossier', fetchImpl);

    assert.equal(enteteRecue, 'Bearer mon-jeton');
  });

  test('une réponse HTTP en échec lève une ErreurDrive nommant le code', async () => {
    const fetchImpl = faireFetch({ ok: false, status: 403 });

    await assert.rejects(
      () => listerFichiers('jeton', 'dossier', fetchImpl),
      (erreur) => {
        assert.ok(erreur instanceof ErreurDrive);
        assert.equal(erreur.code, 403);
        assert.match(erreur.message, /403/);
        return true;
      },
    );
  });

  test('un rejet réseau (fetch qui lève) devient une ErreurDrive', async () => {
    const fetchImpl = async () => {
      throw new Error('hors ligne');
    };

    await assert.rejects(
      () => listerFichiers('jeton', 'dossier', fetchImpl),
      (erreur) => {
        assert.ok(erreur instanceof ErreurDrive);
        assert.equal(erreur.cause?.message, 'hors ligne');
        return true;
      },
    );
  });
});

describe('lireFichier', () => {
  test('rend le texte brut de la réponse', async () => {
    const fetchImpl = faireFetch({ text: async () => '{"schema":"repetition/2"}' });

    const texte = await lireFichier('jeton', 'fichier', fetchImpl);

    assert.equal(texte, '{"schema":"repetition/2"}');
  });

  test('une réponse HTTP en échec lève une ErreurDrive nommant le code', async () => {
    const fetchImpl = faireFetch({ ok: false, status: 404 });

    await assert.rejects(
      () => lireFichier('jeton', 'fichier', fetchImpl),
      (erreur) => {
        assert.ok(erreur instanceof ErreurDrive);
        assert.equal(erreur.code, 404);
        return true;
      },
    );
  });
});
