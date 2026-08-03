/**
 * Tests de `js/etat.js`.
 *
 * Deux invariants portent l'essentiel du risque, et ce sont eux qui sont le plus
 * couverts ici :
 *
 * - `roleActif ⊆ mesRoles` — un rôle actif hors de mes rôles masquerait les
 *   répliques de quelqu'un d'autre, rendant la scène incompréhensible sans rien
 *   signaler ;
 * - `revelees` est vidé à chaque changement de mode — sans quoi une réplique
 *   révélée hier serait révélée demain, et le masquage paraîtrait cassé.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import {
  allerA,
  basculerRevelation,
  masquerReplique,
  basculerMesScenesSeules,
  changerDifficulte,
  changerMesRoles,
  changerMode,
  changerReglage,
  changerRoleActif,
  estRevelee,
  etatInitial,
  masque,
  MODE,
  nouveauTirage,
  partiePersistante,
  restaurer,
  revelerReplique,
  toutRemasquer,
} from '../js/etat.js';
import { CONFIG } from '../js/config.js';

const DEPART = { pieceId: 'p1', mesRoles: ['HENRY', 'OLIVER'] };

describe('état initial', () => {
  test('le rôle actif vaut tous mes rôles', () => {
    // Le cas le plus courant, et cela évite un écran de choix obligatoire quand
    // je n'ai qu'un rôle.
    const etat = etatInitial(DEPART);

    assert.deepEqual(etat.roleActif, ['HENRY', 'OLIVER']);
  });

  test('les valeurs par défaut viennent de config', () => {
    const etat = etatInitial(DEPART);

    assert.equal(etat.difficulte, CONFIG.DIFFICULTE_DEFAUT);
    assert.equal(etat.reglages.taillePolice, 1);
  });

  test('le mode sombre est le défaut', () => {
    // On répète le soir, et l'écran est la seule source de lumière en coulisses.
    assert.equal(etatInitial(DEPART).reglages.sombre, true);
  });

  test('sans argument, un état vide mais utilisable', () => {
    const etat = etatInitial();

    assert.deepEqual(etat.mesRoles, []);
    assert.deepEqual(etat.revelees, []);
    assert.equal(etat.pieceId, null);
  });

  test('les rôles en double sont dédoublonnés', () => {
    const etat = etatInitial({ mesRoles: ['JAN', 'JAN', ''] });

    assert.deepEqual(etat.mesRoles, ['JAN']);
  });

  test('l’état est gelé : aucune modification sur place', () => {
    const etat = etatInitial(DEPART);

    assert.throws(() => {
      etat.mode = MODE.LECTURE;
    });
  });
});

describe('changer de mode', () => {
  test('le mode change', () => {
    const etat = changerMode(etatInitial(DEPART), MODE.AMORCE);

    assert.equal(etat.mode, MODE.AMORCE);
  });

  test('les révélations sont effacées', () => {
    let etat = etatInitial(DEPART);
    etat = revelerReplique(etat, 'r_1');
    etat = changerMode(etat, MODE.AMORCE);

    assert.deepEqual(etat.revelees, []);
  });

  test('revenir au mode précédent remasque bien', () => {
    let etat = etatInitial(DEPART);
    etat = revelerReplique(etat, 'r_1');
    etat = changerMode(etat, MODE.AMORCE);
    etat = changerMode(etat, MODE.MASQUAGE);

    assert.equal(estRevelee(etat, 'r_1'), false);
  });

  test('un mode inconnu est refusé, pas appliqué', () => {
    // Un data-mode sans règle CSS afficherait tout le texte : l'inverse exact
    // de ce qui est demandé.
    assert.throws(() => changerMode(etatInitial(DEPART), 'invente'), /mode inconnu/);
  });

  test('l’état d’origine n’est pas modifié', () => {
    const avant = etatInitial(DEPART);
    changerMode(avant, MODE.LECTURE);

    assert.equal(avant.mode, MODE.MASQUAGE);
  });
});

describe('masque()', () => {
  test('la lecture complète ne masque rien', () => {
    assert.equal(masque(changerMode(etatInitial(DEPART), MODE.LECTURE)), false);
  });

  test('les sept autres modes masquent', () => {
    for (const mode of [
      MODE.MASQUAGE,
      MODE.AMORCE,
      MODE.TROUS,
      MODE.ACRONYME,
      MODE.AVEUGLE,
      MODE.TOP,
      MODE.VOIX,
    ]) {
      assert.equal(masque(changerMode(etatInitial(DEPART), mode)), true, mode);
    }
  });

  test('tout mode déclaré est acceptable, et aucun n’est oublié', () => {
    // Garde-fou : un mode ajouté à MODE mais absent de MODES_MASQUANTS
    // n'aurait pas de bouton « révéler », sans que rien ne le signale.
    for (const mode of Object.values(MODE)) {
      const etat = changerMode(etatInitial(DEPART), mode);

      assert.equal(etat.mode, mode);
      assert.equal(masque(etat), mode !== MODE.LECTURE, mode);
    }
  });

  test('la récitation contrôlée masque, comme le rideau', () => {
    // C'est ce qui en fait un mode de répétition et non un accessoire : le texte
    // est caché, on récite, puis l'outil compare.
    const etat = changerMode(etatInitial(DEPART), MODE.VOIX);

    assert.equal(masque(etat), true);
  });

  test('le mode acronyme masque et se révèle', () => {
    let etat = changerMode(etatInitial(DEPART), MODE.ACRONYME);
    etat = revelerReplique(etat, 'r_1');

    assert.ok(estRevelee(etat, 'r_1'));
  });
});

describe('rôle actif', () => {
  test('se restreint à un seul de mes rôles', () => {
    const etat = changerRoleActif(etatInitial(DEPART), ['OLIVER']);

    assert.deepEqual(etat.roleActif, ['OLIVER']);
    assert.deepEqual(etat.mesRoles, ['HENRY', 'OLIVER']);
  });

  test('un rôle hors de mes rôles est refusé', () => {
    assert.throws(
      () => changerRoleActif(etatInitial(DEPART), ['CLARISSA']),
      /hors de mes rôles/,
    );
  });

  test('le refus nomme le rôle fautif', () => {
    assert.throws(
      () => changerRoleActif(etatInitial(DEPART), ['OLIVER', 'CLARISSA']),
      /CLARISSA/,
    );
  });

  test('un rôle actif vide est refusé', () => {
    // Rien ne serait masqué : le mode paraîtrait cassé.
    assert.throws(() => changerRoleActif(etatInitial(DEPART), []), /ne peut pas être vide/);
  });

  test('changer de rôle actif efface les révélations', () => {
    let etat = revelerReplique(etatInitial(DEPART), 'r_1');
    etat = changerRoleActif(etat, ['HENRY']);

    assert.deepEqual(etat.revelees, []);
  });

  test('mesRoles n’est pas touché par un changement de rôle actif', () => {
    // C'est la distinction du §10.3 : mesRoles est structurel, roleActif est
    // présentationnel.
    const etat = changerRoleActif(etatInitial(DEPART), ['HENRY']);

    assert.deepEqual(etat.mesRoles, ['HENRY', 'OLIVER']);
  });
});

describe('mes rôles', () => {
  test('un rôle ajouté devient actif', () => {
    // Trouvé en pilotant l'interface : déclarer qu'on joue un personnage sans
    // qu'il devienne actif laisse ses répliques en clair, et on croit l'outil
    // cassé.
    let etat = changerMesRoles(etatInitial({ pieceId: 'p' }), ['HENRY']);
    etat = changerMesRoles(etat, ['HENRY', 'OLIVER']);

    assert.deepEqual(etat.roleActif, ['HENRY', 'OLIVER']);
  });

  test('un rôle ajouté rejoint un rôle actif restreint', () => {
    let etat = changerMesRoles(etatInitial(DEPART), ['HENRY', 'OLIVER']);
    etat = changerRoleActif(etat, ['HENRY']);
    etat = changerMesRoles(etat, ['HENRY', 'OLIVER', 'CLARISSA']);

    assert.deepEqual(etat.roleActif, ['HENRY', 'CLARISSA']);
  });

  test('le rôle actif est réduit à l’intersection', () => {
    let etat = changerRoleActif(etatInitial(DEPART), ['HENRY', 'OLIVER']);
    etat = changerMesRoles(etat, ['OLIVER']);

    assert.deepEqual(etat.mesRoles, ['OLIVER']);
    assert.deepEqual(etat.roleActif, ['OLIVER']);
  });

  test('si l’intersection est vide, le rôle actif repart de mes rôles', () => {
    let etat = changerRoleActif(etatInitial(DEPART), ['HENRY']);
    etat = changerMesRoles(etat, ['CLARISSA']);

    assert.deepEqual(etat.roleActif, ['CLARISSA']);
  });

  test('l’invariant tient après tout changement de mes rôles', () => {
    for (const roles of [[], ['HENRY'], ['CLARISSA', 'JAN'], ['HENRY', 'OLIVER']]) {
      const etat = changerMesRoles(etatInitial(DEPART), roles);

      for (const actif of etat.roleActif) {
        assert.ok(etat.mesRoles.includes(actif), `${actif} hors de ${roles}`);
      }
    }
  });
});

describe('difficulté et tirage', () => {
  test('la difficulté est bornée sans lever d’erreur', () => {
    // La valeur vient d'un curseur, et un curseur ne mérite pas une exception.
    assert.equal(changerDifficulte(etatInitial(DEPART), 150).difficulte, 100);
    assert.equal(changerDifficulte(etatInitial(DEPART), -20).difficulte, 0);
  });

  test('elle est arrondie', () => {
    assert.equal(changerDifficulte(etatInitial(DEPART), 45.6).difficulte, 46);
  });

  test('un nouveau tirage incrémente le passage', () => {
    // Le passage entre dans la graine : c'est ce qui rend les trous stables par
    // défaut et changeables sur demande.
    let etat = etatInitial(DEPART);

    assert.equal(etat.passageTrous, 0);

    etat = nouveauTirage(etat);
    etat = nouveauTirage(etat);

    assert.equal(etat.passageTrous, 2);
  });
});

describe('révélations', () => {
  test('révéler puis interroger', () => {
    const etat = revelerReplique(etatInitial(DEPART), 'r_1');

    assert.ok(estRevelee(etat, 'r_1'));
    assert.ok(!estRevelee(etat, 'r_2'));
  });

  test('révéler deux fois ne duplique rien', () => {
    let etat = revelerReplique(etatInitial(DEPART), 'r_1');
    const avant = etat;
    etat = revelerReplique(etat, 'r_1');

    assert.equal(etat, avant, 'un état neuf a été créé pour rien');
    assert.equal(etat.revelees.length, 1);
  });

  test('tout remasquer vide la liste', () => {
    let etat = revelerReplique(etatInitial(DEPART), 'r_1');
    etat = revelerReplique(etat, 'r_2');
    etat = toutRemasquer(etat);

    assert.deepEqual(etat.revelees, []);
  });

  test('remasquer ne change pas de mode', () => {
    const etat = toutRemasquer(changerMode(etatInitial(DEPART), MODE.TROUS));

    assert.equal(etat.mode, MODE.TROUS);
  });
});

describe('position et réglages', () => {
  test('aller à une unité', () => {
    const etat = allerA(etatInitial(DEPART), { unite: 'u3' });

    assert.equal(etat.uniteCourante, 'u3');
    assert.equal(etat.repliqueCourante, null);
  });

  test('aller à une réplique sans toucher l’unité', () => {
    let etat = allerA(etatInitial(DEPART), { unite: 'u3' });
    etat = allerA(etat, { replique: 'r_7' });

    assert.equal(etat.uniteCourante, 'u3');
    assert.equal(etat.repliqueCourante, 'r_7');
  });

  test('un réglage connu change', () => {
    const etat = changerReglage(etatInitial(DEPART), 'taillePolice', 1.4);

    assert.equal(etat.reglages.taillePolice, 1.4);
  });

  test('un réglage inconnu est refusé', () => {
    assert.throws(
      () => changerReglage(etatInitial(DEPART), 'couleurDuRideau', 'rouge'),
      /réglage inconnu/,
    );
  });

  test('changer un réglage n’efface pas les autres', () => {
    let etat = changerReglage(etatInitial(DEPART), 'taillePolice', 1.4);
    etat = changerReglage(etat, 'sombre', false);

    assert.equal(etat.reglages.taillePolice, 1.4);
    assert.equal(etat.reglages.sombre, false);
  });
});

describe('persistance', () => {
  test('revelees n’est jamais persisté', () => {
    // Une réplique révélée hier ne doit pas être révélée demain.
    const etat = revelerReplique(etatInitial(DEPART), 'r_1');
    const persiste = partiePersistante(etat);

    assert.ok(!('revelees' in persiste));
  });

  test('le reste est persisté', () => {
    const persiste = partiePersistante(etatInitial(DEPART));

    for (const champ of ['mode', 'difficulte', 'roleActif', 'reglages', 'pieceId']) {
      assert.ok(champ in persiste, `${champ} manque`);
    }
  });

  test('la part persistée survit à un aller-retour JSON', () => {
    // Le vrai test : des Set auraient donné {} en silence.
    let etat = changerMode(etatInitial(DEPART), MODE.TROUS);
    etat = changerRoleActif(etat, ['OLIVER']);
    etat = changerDifficulte(etat, 70);

    const relu = JSON.parse(JSON.stringify(partiePersistante(etat)));

    assert.deepEqual(relu.roleActif, ['OLIVER']);
    assert.deepEqual(relu.mesRoles, ['HENRY', 'OLIVER']);
    assert.equal(relu.mode, MODE.TROUS);
    assert.equal(relu.difficulte, 70);
  });
});

describe('restauration', () => {
  test('un aller-retour complet redonne le même état utile', () => {
    let etat = changerMode(etatInitial(DEPART), MODE.AMORCE);
    etat = changerRoleActif(etat, ['HENRY']);
    etat = changerDifficulte(etat, 60);
    etat = basculerMesScenesSeules(etat);
    etat = allerA(etat, { unite: 'u4', replique: 'r_9' });
    etat = changerReglage(etat, 'taillePolice', 1.2);

    const restaure = restaurer(
      JSON.parse(JSON.stringify(partiePersistante(etat))),
      DEPART,
    );

    assert.equal(restaure.mode, MODE.AMORCE);
    assert.deepEqual(restaure.roleActif, ['HENRY']);
    assert.equal(restaure.difficulte, 60);
    assert.equal(restaure.mesScenesSeules, true);
    assert.equal(restaure.uniteCourante, 'u4');
    assert.equal(restaure.repliqueCourante, 'r_9');
    assert.equal(restaure.reglages.taillePolice, 1.2);
  });

  test('les révélations ne sont jamais restaurées', () => {
    const restaure = restaurer({ revelees: ['r_1', 'r_2'] }, DEPART);

    assert.deepEqual(restaure.revelees, []);
  });

  test('des données corrompues rendent un état neuf, pas une erreur', () => {
    // P4 : la perte des réglages ne doit jamais empêcher de répéter.
    for (const donnees of [null, undefined, 42, 'texte', [], true]) {
      const restaure = restaurer(donnees, DEPART);

      assert.equal(restaure.mode, MODE.MASQUAGE);
      assert.deepEqual(restaure.mesRoles, ['HENRY', 'OLIVER']);
    }
  });

  test('un mode invalide retombe sur le défaut', () => {
    assert.equal(restaurer({ mode: 'invente' }, DEPART).mode, MODE.MASQUAGE);
  });

  test('un rôle actif devenu invalide est écarté', () => {
    // Cas réel : la pièce a été rééditée et un personnage a changé de nom.
    const restaure = restaurer({ roleActif: ['CLARISSA'] }, DEPART);

    assert.deepEqual(restaure.roleActif, ['HENRY', 'OLIVER']);
  });

  test('un rôle actif partiellement valide conserve ce qui vaut', () => {
    const restaure = restaurer({ roleActif: ['OLIVER', 'CLARISSA'] }, DEPART);

    assert.deepEqual(restaure.roleActif, ['OLIVER']);
  });

  test('un réglage inconnu est ignoré, pas conservé', () => {
    // Le garder ferait échouer `changerReglage` plus tard sur un nom disparu.
    const restaure = restaurer({ reglages: { couleurDuRideau: 'rouge' } }, DEPART);

    assert.ok(!('couleurDuRideau' in restaure.reglages));
  });

  test('un réglage du mauvais type est ignoré', () => {
    const restaure = restaurer({ reglages: { sombre: 'oui' } }, DEPART);

    assert.equal(restaure.reglages.sombre, true);
  });

  test('l’invariant tient sur tout état restauré', () => {
    const restaure = restaurer(
      { roleActif: ['CLARISSA', 'HENRY', ''], mode: MODE.TOP },
      DEPART,
    );

    for (const actif of restaure.roleActif) {
      assert.ok(restaure.mesRoles.includes(actif), actif);
    }
  });
});

describe('révélation basculante', () => {
  test('un second appel remasque', () => {
    // Un dévoilement irréversible obligeait à changer de mode pour retrouver le
    // masquage — donc à perdre toutes les autres révélations au passage.
    let etat = basculerRevelation(etatInitial(DEPART), 'r_1');

    assert.ok(estRevelee(etat, 'r_1'));

    etat = basculerRevelation(etat, 'r_1');

    assert.ok(!estRevelee(etat, 'r_1'));
  });

  test('remasquer n’atteint pas les autres répliques', () => {
    let etat = basculerRevelation(etatInitial(DEPART), 'r_1');
    etat = basculerRevelation(etat, 'r_2');
    etat = basculerRevelation(etat, 'r_1');

    assert.ok(!estRevelee(etat, 'r_1'));
    assert.ok(estRevelee(etat, 'r_2'));
  });

  test('masquerReplique sur une réplique non révélée ne change rien', () => {
    const avant = etatInitial(DEPART);

    assert.equal(masquerReplique(avant, 'r_1'), avant);
  });

  test('l’original n’est pas modifié', () => {
    const avant = basculerRevelation(etatInitial(DEPART), 'r_1');
    basculerRevelation(avant, 'r_1');

    assert.ok(estRevelee(avant, 'r_1'));
  });

  test('un changement de mode remasque tout, comme avant', () => {
    let etat = basculerRevelation(etatInitial(DEPART), 'r_1');
    etat = changerMode(etat, MODE.AMORCE);

    assert.deepEqual(etat.revelees, []);
  });
});
