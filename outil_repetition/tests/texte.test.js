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
  amorceCouvreTout,
  contient,
  estMot,
  positionsDesMots,
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

describe('estMot et positionsDesMots', () => {
  test('la ponctuation française détachée n’est pas un mot', () => {
    // Le français place une espace avant « ! ? ; : » : le découpage produit donc
    // des jetons de pure ponctuation, qu'il ne faut ni masquer, ni compter.
    assert.ok(estMot('Alors'));
    assert.ok(!estMot('!'));
    assert.ok(!estMot('?...'));
    assert.ok(!estMot('«'));
  });

  test('un mot avec sa ponctuation collée reste un mot', () => {
    assert.ok(estMot('heure.'));
    assert.ok(estMot("qu'elle"));
  });

  test('un nombre est un mot', () => {
    assert.ok(estMot('1789'));
  });

  test('positionsDesMots écarte les jetons de ponctuation', () => {
    // « Alors ? Vraiment ! » = 4 jetons, 2 mots.
    assert.deepEqual(positionsDesMots('Alors ? Vraiment !'), [0, 2]);
  });

  test('un texte sans mot ne rend aucune position', () => {
    assert.deepEqual(positionsDesMots('... ?!'), []);
  });
});

describe('amorce comptée en mots', () => {
  test('la ponctuation détachée ne consomme pas un mot d’amorce', () => {
    // Sans ce comptage, l'amorce ne montrerait que deux mots ici.
    assert.equal(amorce('Alors ? Vraiment ! Bien sûr.', 3), 'Alors ? Vraiment ! Bien');
  });

  test('la ponctuation collée est rendue avec son mot', () => {
    assert.equal(amorce('Un, deux, trois, quatre.', 2), 'Un, deux,');
  });

  test('une réplique plus courte que l’amorce est rendue en entier', () => {
    assert.equal(amorce('Oui.', 3), 'Oui.');
  });
});

describe('amorceCouvreTout', () => {
  test('vrai quand la réplique n’a pas de suite à cacher', () => {
    // Le mode « amorce » l'afficherait alors en entier, sans rien demander à la
    // mémoire : le rendu la masque complètement.
    assert.ok(amorceCouvreTout('Monsieur Costello.', 3));
    assert.ok(amorceCouvreTout('Oui.', 3));
    assert.ok(amorceCouvreTout('Alors ?', 3));
  });

  test('faux dès qu’il reste un mot après l’amorce', () => {
    assert.ok(!amorceCouvreTout('Je cherche Mme Brown.', 3));
  });

  test('la ponctuation ne fait pas basculer le verdict', () => {
    // « Bien ! » ne fait qu'un mot : trois jetons ne sont pas trois mots.
    assert.ok(amorceCouvreTout('Ah ! Bon ?', 3));
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


describe('abréviations et exposants', () => {
  test('« Mme » et « Madame » sont la même chose', () => {
    // C'est le cas signalé à l'usage : l'édition écrit l'abréviation, le
    // comédien dit le mot, et la transcription rend ce qu'elle entend.
    assert.equal(normaliser('Mme Brown'), normaliser('Madame Brown'));
  });

  test('les lettres en exposant sont dépliées', () => {
    // Le document de travail écrit « Mᵐᵉ » avec des lettres modificatives. NFD
    // les laissait intactes ; NFKD les déplie.
    assert.equal(normaliser('Mᵐᵉ Brown'), normaliser('Madame Brown'));
  });

  test('les autres abréviations courantes du théâtre', () => {
    const paires = [
      ['M. Costello', 'Monsieur Costello'],
      ['MM. Costello', 'Messieurs Costello'],
      ['Mlle Peake', 'Mademoiselle Peake'],
      ['Mmes Brown', 'Mesdames Brown'],
      ['Dr Brown', 'Docteur Brown'],
      ['St Pierre', 'Saint Pierre'],
    ];

    for (const [ecrit, dit] of paires) {
      assert.equal(normaliser(ecrit), normaliser(dit), `${ecrit} ≠ ${dit}`);
    }
  });

  test('un mot ordinaire n’est pas confondu avec une abréviation', () => {
    // « me », « ma », « mon » ne doivent pas devenir « madame ».
    assert.equal(normaliser('me voici'), 'me voici');
    assert.equal(normaliser('ma maison'), 'ma maison');
    assert.equal(normaliser('sti'), 'sti');
  });

  test('toutes les correspondances sont d’un mot vers un mot', () => {
    // Contrainte, non coïncidence : `comparaison.comparer` aligne la forme
    // affichée sur la forme normalisée pour surligner le bon mot. Une abréviation
    // qui se déplierait en deux mots romprait cet alignement.
    for (const abrege of ['Mme', 'MM', 'Mlle', 'Mmes', 'Dr', 'Pr', 'St', 'etc']) {
      assert.equal(
        motsNormalises(abrege).length,
        1,
        `${abrege} se déplie en plusieurs mots`,
      );
    }
  });

  test('autant de mots significatifs que de mots normalisés', () => {
    // C'est la condition de l'alignement du surlignage dans `comparer` : la
    // ponctuation détachée ne compte d'aucun côté.
    const replique = 'J’y vais. Allô… oui… Copplestone Court… Mme Brown ?';

    assert.equal(
      mots(replique).filter(estMot).length,
      motsNormalises(replique).length,
    );
  });
});
