/**
 * Tests de `js/comparaison.js`.
 *
 * C'est le module dont un défaut ne se voit pas : il ne casse rien, il produit
 * seulement des scores qu'on finit par ignorer. Ces tests portent donc d'abord
 * sur les cas où un score naïf serait faux — récitation parfaite mais sans
 * ponctuation, substitution comptée deux fois, mot en trop pénalisé.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { comparer, ETAT } from '../js/comparaison.js';
import { CONFIG } from '../js/config.js';

/** États des mots attendus, dans l'ordre. */
function etats(resultat) {
  return resultat.details.map((detail) => detail.etat);
}

describe('récitation exacte', () => {
  test('score de 100', () => {
    const resultat = comparer('Nous y sommes enfin.', 'Nous y sommes enfin.');

    assert.equal(resultat.score, 100);
    assert.deepEqual(etats(resultat), Array(4).fill(ETAT.CORRECT));
  });

  test('la ponctuation absente ne coûte rien', () => {
    // La transcription iOS ne rend aucune ponctuation : sans normalisation, une
    // récitation parfaite obtiendrait un score proche de zéro.
    const resultat = comparer(
      'Vous ne savez pas, monsieur, ce que vous dites !',
      'vous ne savez pas monsieur ce que vous dites',
    );

    assert.equal(resultat.score, 100);
  });

  test('accents et apostrophes typographiques ne coûtent rien', () => {
    const resultat = comparer('Qu’elle réponde.', "qu'elle reponde");

    assert.equal(resultat.score, 100);
  });

  test('le mot affiché garde sa forme d’origine', () => {
    // Le surlignage doit montrer le texte de l'auteur, pas sa forme normalisée.
    const resultat = comparer('Qu’elle RÉPONDE.', "qu'elle reponde");

    assert.deepEqual(
      resultat.details.map((d) => d.mot),
      ['Qu’elle', 'RÉPONDE.'],
    );
  });
});

describe('oublis', () => {
  test('un mot oublié est marqué et pèse sur le score', () => {
    const resultat = comparer('Nous y sommes enfin.', 'Nous y sommes.');

    assert.deepEqual(etats(resultat), [
      ETAT.CORRECT,
      ETAT.CORRECT,
      ETAT.CORRECT,
      ETAT.OUBLIE,
    ]);
    assert.equal(resultat.score, 75);
  });

  test('une récitation vide donne zéro, sans erreur', () => {
    const resultat = comparer('Nous y sommes enfin.', '');

    assert.equal(resultat.score, 0);
    assert.deepEqual(etats(resultat), Array(4).fill(ETAT.OUBLIE));
  });

  test('un texte attendu vide ne donne pas 100', () => {
    // Un score parfait sur du vide serait un mensonge commode.
    const resultat = comparer('', 'quelque chose');

    assert.equal(resultat.score, 0);
    assert.equal(resultat.attendus, 0);
    assert.deepEqual(resultat.details, []);
  });
});

describe('substitutions', () => {
  test('un mot substitué compte pour une faute, pas deux', () => {
    // Sans la fusion oubli + ajout, le score chuterait deux fois plus vite que
    // la mémoire ne défaille.
    const resultat = comparer('Il prend la chaire.', 'Il prend la chaise.');

    assert.deepEqual(etats(resultat), [
      ETAT.CORRECT,
      ETAT.CORRECT,
      ETAT.CORRECT,
      ETAT.SUBSTITUE,
    ]);
    assert.equal(resultat.score, 75);
  });

  test('le mot réellement dit est conservé', () => {
    const resultat = comparer('la chaire', 'la chaise');
    const substitue = resultat.details.find((d) => d.etat === ETAT.SUBSTITUE);

    assert.equal(substitue.mot, 'chaire');
    assert.equal(substitue.dit, 'chaise');
  });

  test('une substitution en milieu de réplique', () => {
    const resultat = comparer('un deux trois quatre', 'un deux TROIX quatre');

    assert.deepEqual(etats(resultat), [
      ETAT.CORRECT,
      ETAT.CORRECT,
      ETAT.SUBSTITUE,
      ETAT.CORRECT,
    ]);
  });
});

describe('mots en trop', () => {
  test('un ajout est signalé mais ne pèse pas sur le score', () => {
    // Réciter juste en glissant un « eh bien » n'est pas une faute de mémoire.
    const resultat = comparer('Nous y sommes.', 'Eh bien nous y sommes.');

    assert.equal(resultat.score, 100);
    assert.equal(resultat.corrects, 3);
    assert.equal(
      resultat.details.filter((d) => d.etat === ETAT.AJOUTE).length,
      2,
    );
  });

  test('l’ajout porte le mot dit, pas un mot attendu', () => {
    const resultat = comparer('Nous y sommes.', 'Alors nous y sommes.');
    const ajoute = resultat.details.find((d) => d.etat === ETAT.AJOUTE);

    assert.equal(ajoute.mot, 'alors');
  });
});

describe('cas limites', () => {
  test('une répétition de mot ne dérègle pas l’alignement', () => {
    const resultat = comparer('oui oui oui', 'oui oui');

    assert.equal(resultat.corrects, 2);
    assert.deepEqual(etats(resultat), [
      ETAT.CORRECT,
      ETAT.CORRECT,
      ETAT.OUBLIE,
    ]);
  });

  test('un ordre inversé n’invente pas de mots corrects en trop', () => {
    const resultat = comparer('un deux', 'deux un');

    assert.ok(resultat.corrects <= 1, `corrects = ${resultat.corrects}`);
    assert.ok(resultat.score < 100);
  });

  test('les vers sont comparés comme un tout', () => {
    const resultat = comparer(
      'Je vous ai vu venir de loin,\nEt je n’ai pas bougé.',
      'je vous ai vu venir de loin et je n’ai pas bougé',
    );

    assert.equal(resultat.score, 100);
  });

  test('un texte très long est tronqué et le signale', () => {
    const long = Array(CONFIG.MOTS_MAX_ALIGNEMENT + 50).fill('mot').join(' ');
    const resultat = comparer(long, long);

    assert.ok(resultat.tronque);
    assert.equal(resultat.attendus, CONFIG.MOTS_MAX_ALIGNEMENT);
    assert.equal(resultat.score, 100);
  });

  test('un texte de longueur normale n’est pas marqué tronqué', () => {
    assert.ok(!comparer('trois petits mots', 'trois petits mots').tronque);
  });

  test('le nombre de mots attendus est celui du texte, pas du récité', () => {
    const resultat = comparer('un deux', 'un deux trois quatre cinq');

    assert.equal(resultat.attendus, 2);
  });
});

describe('cohérence du détail', () => {
  test('chaque mot attendu apparaît exactement une fois', () => {
    const attendu = 'Je ne crois pas qu’elle réponde.';
    const resultat = comparer(attendu, 'je crois qu’elle repondra');

    const nonAjoutes = resultat.details.filter((d) => d.etat !== ETAT.AJOUTE);

    assert.equal(nonAjoutes.length, 6);
    assert.deepEqual(
      nonAjoutes.map((d) => d.mot),
      ['Je', 'ne', 'crois', 'pas', 'qu’elle', 'réponde.'],
    );
  });

  test('le score est le rapport des corrects aux attendus', () => {
    const resultat = comparer('un deux trois quatre', 'un deux');

    assert.equal(
      resultat.score,
      Math.round((resultat.corrects / resultat.attendus) * 100),
    );
  });
});
