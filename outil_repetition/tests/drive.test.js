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
  estFichierRepet,
  fichiersDepuisReponse,
  listerFichiers,
  lireFichier,
} from '../../pieces/drive.js';

describe('urlListeFichiers', () => {
  test('inclut le dossier, exclut la corbeille', () => {
    const url = new URL(urlListeFichiers('DOSSIER123'));
    const requete = url.searchParams.get('q');

    assert.equal(url.origin + url.pathname, 'https://www.googleapis.com/drive/v3/files');
    assert.match(requete, /'DOSSIER123' in parents/);
    assert.match(requete, /trashed = false/);
  });

  test('ne filtre plus sur le nom côté serveur', () => {
    // Régression : `name contains '_REPET.json'` ne remontait jamais rien,
    // l'opérateur de l'API Drive segmentant le nom en mots ('_' et '.' comptent
    // comme séparateurs). Le filtre vit maintenant dans `estFichierRepet`.
    const requete = new URL(urlListeFichiers('DOSSIER123')).searchParams.get('q');

    assert.ok(!requete.includes('contains'));
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

describe('estFichierRepet', () => {
  test('un nom qui finit par _REPET.json est reconnu', () => {
    assert.ok(estFichierRepet('Le roi nu_REPET.json'));
  });

  test('tout le reste est écarté', () => {
    assert.ok(!estFichierRepet('Le roi nu.docx'));
    assert.ok(!estFichierRepet('notes.txt'));
    assert.ok(!estFichierRepet(''));
    assert.ok(!estFichierRepet(null));
    assert.ok(!estFichierRepet(undefined));
  });
});

describe('fichiersDepuisReponse', () => {
  test('rend les fichiers _REPET.json valides tels quels', () => {
    const json = { files: [{ id: '1', name: 'A_REPET.json' }, { id: '2', name: 'B_REPET.json' }] };

    assert.deepEqual(fichiersDepuisReponse(json), json.files);
  });

  test('écarte un fichier sans id, sans name, ou qui n’est pas un _REPET.json', () => {
    // Le dossier Drive peut contenir d'autres documents : notes, PDF sources,
    // le .docx d'origine — jamais listés ici (voir urlListeFichiers).
    const json = {
      files: [
        { id: '1', name: 'A_REPET.json' },
        { id: '2' },
        { name: 'sans-id_REPET.json' },
        { id: '3', name: 'notes.txt' },
        { id: '4', name: 'Le roi nu.docx' },
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
