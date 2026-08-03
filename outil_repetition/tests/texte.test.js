/**
 * Tests de `js/texte.js`.
 *
 * Ce qui est éprouvé ici, c'est ce que la transcription vocale d'iOS impose de
 * neutraliser : ponctuation absente, apostrophes typographiques, nombres en
 * chiffres, accents. Une normalisation approximative ne casse rien de visible —
 * elle produit seulement des scores absurdes.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import {
  acronyme,
  amorce,
  contient,
  derniersMots,
  lignes,
  mots,
  motsNormalises,
  nombreEnMots,
  normaliser,
  sansAccents,
} from '../js/texte.js';

describe('normaliser', () => {
  test('retire accents, casse et ponctuation', () => {
    assert.equal(
      normaliser('Je ne crois pas qu’elle RÉPONDE !'),
      "je ne crois pas qu'elle reponde",
    );
  });

  test('ramène les apostrophes typographiques à l’apostrophe droite', () => {
    assert.equal(normaliser('qu’elle'), normaliser("qu'elle"));
  });

  test('conserve l’apostrophe, pour ne pas dédoubler un mot', () => {
    // C'est ce qui garde le même compte de mots que `mots()`, dont dépendent
    // les positions `avant_mot` calculées par repet_export.py.
    assert.equal(motsNormalises("Je t'attendais").length, mots("Je t'attendais").length);
  });

  test('une récitation sans ponctuation égale le texte ponctué', () => {
    const attendu = 'Vous ne savez pas, monsieur, ce que vous dites !';
    const recite = 'vous ne savez pas monsieur ce que vous dites';

    assert.equal(normaliser(attendu), normaliser(recite));
  });

  test('les tirets ne créent pas de mot collé', () => {
    assert.equal(normaliser('peut-être'), 'peut etre');
  });

  test('un texte vide donne une chaîne vide et aucun mot', () => {
    assert.equal(normaliser('   \n  '), '');
    assert.deepEqual(motsNormalises('   '), []);
  });

  test('les marqueurs d’emphase résiduels disparaissent', () => {
    assert.equal(normaliser('un *mot* dit'), 'un mot dit');
  });
});

describe('sansAccents', () => {
  test('SCÈNE devient SCENE', () => {
    assert.equal(sansAccents('SCÈNE'), 'SCENE');
  });

  test('la cédille et le tréma tombent aussi', () => {
    assert.equal(sansAccents('reçu naïf'), 'recu naif');
  });
});

describe('nombreEnMots', () => {
  test('les unités et les nombres irréguliers', () => {
    assert.equal(nombreEnMots(0), 'zero');
    assert.equal(nombreEnMots(7), 'sept');
    assert.equal(nombreEnMots(16), 'seize');
  });

  test('dix-sept à dix-neuf, composés', () => {
    // Ces trois-là débordaient de la table : ni unités simples, ni dizaines.
    assert.equal(nombreEnMots(17), 'dix-sept');
    assert.equal(nombreEnMots(18), 'dix-huit');
    assert.equal(nombreEnMots(19), 'dix-neuf');
  });

  test('les dizaines régulières', () => {
    assert.equal(nombreEnMots(20), 'vingt');
    assert.equal(nombreEnMots(21), 'vingt et un');
    assert.equal(nombreEnMots(22), 'vingt-deux');
    assert.equal(nombreEnMots(45), 'quarante-cinq');
  });

  test('les dizaines françaises irrégulières', () => {
    // C'est la particularité qui interdit une simple table de correspondance.
    assert.equal(nombreEnMots(70), 'soixante-dix');
    assert.equal(nombreEnMots(75), 'soixante-quinze');
    assert.equal(nombreEnMots(80), 'quatre-vingts');
    assert.equal(nombreEnMots(81), 'quatre-vingt-un');
    assert.equal(nombreEnMots(90), 'quatre-vingt-dix');
    assert.equal(nombreEnMots(99), 'quatre-vingt-dix-neuf');
  });

  test('les dizaines irrégulières composées sur dix-sept à dix-neuf', () => {
    // C'est exactement là que la première version rendait « undefined ».
    assert.equal(nombreEnMots(77), 'soixante-dix-sept');
    assert.equal(nombreEnMots(79), 'soixante-dix-neuf');
    assert.equal(nombreEnMots(97), 'quatre-vingt-dix-sept');
  });

  test('aucun nombre de 0 à 999 ne rend « undefined »', () => {
    // Garde-fou global : un débordement de table est silencieux et produit un
    // mot qui ne ressemble à rien, mais que rien ne signale.
    for (let n = 0; n <= 999; n += 1) {
      const ecrit = nombreEnMots(n);

      assert.ok(!ecrit.includes('undefined'), `${n} → ${ecrit}`);
      assert.ok(ecrit.length > 0, `${n} rend une chaîne vide`);
    }
  });

  test('les centaines', () => {
    assert.equal(nombreEnMots(100), 'cent');
    assert.equal(nombreEnMots(200), 'deux cents');
    assert.equal(nombreEnMots(203), 'deux cent trois');
    assert.equal(nombreEnMots(999), 'neuf cent quatre-vingt-dix-neuf');
  });

  test('au-delà de 999, les chiffres sont rendus tels quels', () => {
    // Limite assumée : « 1789 » se dit de deux façons, et deviner mal serait
    // pire que de ne rien faire.
    assert.equal(nombreEnMots(1789), '1789');
  });

  test('une valeur non entière est rendue telle quelle', () => {
    assert.equal(nombreEnMots('trois'), 'trois');
    assert.equal(nombreEnMots(-1), '-1');
  });

  test('la normalisation applique la conversion', () => {
    assert.equal(normaliser('J’ai 20 ans'), normaliser("J'ai vingt ans"));
  });
});

describe('mots et lignes', () => {
  test('les espaces multiples ne créent pas de mot vide', () => {
    assert.deepEqual(mots('  deux   mots \n'), ['deux', 'mots']);
  });

  test('lignes préserve la structure d’un vers', () => {
    assert.deepEqual(lignes('Premier vers,\nSecond vers.'), [
      'Premier vers,',
      'Second vers.',
    ]);
  });

  test('mots traverse les vers', () => {
    assert.equal(mots('Premier vers,\nSecond vers.').length, 4);
  });
});

describe('amorce et derniersMots', () => {
  const REPLIQUE = 'Je ne crois pas qu’elle réponde.';

  test('amorce rend les premiers mots, forme d’origine conservée', () => {
    assert.equal(amorce(REPLIQUE, 3), 'Je ne crois');
  });

  test('derniersMots rend la fin — c’est le top réduit', () => {
    assert.equal(derniersMots(REPLIQUE, 2), 'qu’elle réponde.');
  });

  test('demander plus de mots qu’il n’y en a rend tout le texte', () => {
    assert.equal(amorce('Deux mots', 10), 'Deux mots');
    assert.equal(derniersMots('Deux mots', 10), 'Deux mots');
  });

  test('sur un texte vide, aucune erreur', () => {
    assert.equal(amorce('', 3), '');
    assert.equal(derniersMots('', 3), '');
  });
});

describe('acronyme', () => {
  test('l’exemple de référence', () => {
    assert.equal(acronyme('Ai-je ?... Oui... Comme moi...'), 'A-j ?... O... C m...');
  });

  test('chaque mot est réduit à son initiale', () => {
    assert.equal(acronyme('Nous y sommes enfin'), 'N y s e');
  });

  test('la ponctuation est conservée strictement', () => {
    assert.equal(acronyme('Vraiment ?! Bien...'), 'V ?! B...');
    assert.equal(acronyme('Un, deux ; trois.'), 'U, d ; t.');
    assert.equal(acronyme('« Oui »'), '« O »');
  });

  test('la casse de l’initiale est préservée', () => {
    assert.equal(acronyme('Jan et MARTHA'), 'J e M');
  });

  test('l’accent de l’initiale est préservé', () => {
    assert.equal(acronyme('Être ou ne pas être'), 'Ê o n p ê');
    assert.equal(acronyme('À propos'), 'À p');
  });

  test('l’accent survit à une forme décomposée', () => {
    // Si le texte arrive en NFD, l'initiale est une lettre + un accent
    // combinant : sans le groupe \p{M}*, l'accent serait perdu.
    const decompose = 'être'.normalize('NFD');

    assert.equal(acronyme(decompose).normalize('NFC'), 'ê');
  });

  test('l’apostrophe borne deux mots', () => {
    // La conserver tout en ne gardant qu'une initiale donnerait « q' », qui
    // laisse une apostrophe pendante.
    assert.equal(acronyme("qu'elle"), "q'e");
    assert.equal(acronyme('qu’elle réponde'), 'q’e r');
    assert.equal(acronyme("aujourd'hui"), "a'h");
  });

  test('le tiret aussi', () => {
    assert.equal(acronyme('peut-être'), 'p-ê');
    assert.equal(acronyme('Ai-je bien entendu ?'), 'A-j b e ?');
  });

  test('les retours à la ligne d’un vers sont conservés', () => {
    assert.equal(
      acronyme('Je vous ai vu venir de loin,\nEt je n’ai pas bougé.'),
      'J v a v v d l,\nE j n’a p b.',
    );
  });

  test('les espaces multiples ne sont pas normalisés', () => {
    // « sans modifier les espaces » : le rythme visuel est justement l'indice.
    assert.equal(acronyme('un  deux'), 'u  d');
  });

  test('les chiffres sont conservés entiers', () => {
    // Faute d'initiale. Le cas est rare : l'édition imprimée écrit ses nombres
    // en lettres.
    assert.equal(acronyme('vingt ans'), 'v a');
    assert.equal(acronyme('20 ans'), '20 a');
  });

  test('un texte vide ou sans lettre passe tel quel', () => {
    assert.equal(acronyme(''), '');
    assert.equal(acronyme('... ?!'), '... ?!');
  });

  test('l’acronyme est plus court que le texte, jamais plus long', () => {
    for (const texte of [
      'Je ne crois pas qu’elle réponde.',
      'Ai-je ?... Oui...',
      'Nous y sommes enfin.',
    ]) {
      assert.ok(acronyme(texte).length <= texte.length, texte);
    }
  });

  test('la ponctuation survivante est identique à celle du texte', () => {
    // Garde-fou : c'est l'exigence explicite du mode, et une regex trop gourmande
    // la casserait sans qu'aucun autre test ne le voie.
    const texte = 'Ai-je ?... Oui, vraiment ; « bien » !';
    const nonLettres = (s) => s.replace(/[\p{L}\p{M}\d]/gu, '');

    assert.equal(nonLettres(acronyme(texte)), nonLettres(texte));
  });

  test('un mot par mot : autant de mots avant qu’après', () => {
    const texte = 'Je ne crois pas qu’elle réponde.';

    assert.equal(mots(acronyme(texte)).length, mots(texte).length);
  });
});

describe('contient', () => {
  test('la recherche ignore accents et casse', () => {
    assert.ok(contient('Je ne crois pas qu’elle réponde.', 'REPONDE'));
  });

  test('un fragment absent n’est pas trouvé', () => {
    assert.ok(!contient('Je ne crois pas.', 'auberge'));
  });

  test('un fragment vide ne trouve rien', () => {
    // Sinon toute réplique « correspondrait » dès qu'on efface la recherche.
    assert.ok(!contient('Un texte', '   '));
  });
});
