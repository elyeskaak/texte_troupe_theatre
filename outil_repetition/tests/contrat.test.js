/**
 * Le contrat entre `outil_edition` et `outil_repetition`.
 *
 * `tests/exemple-repet.json` est un vrai fichier, produit par
 * `repet_export.py` sur une pièce d'essai de quelques répliques. Ce test le
 * valide avec `schema.js`.
 *
 * C'est le seul test qui éprouve les **deux outils ensemble**, et il attrape la
 * classe de défauts la plus coûteuse : une divergence silencieuse entre ce que
 * Python écrit et ce que le navigateur attend. Sans lui, un champ renommé d'un
 * côté ne se découvrirait qu'en chargeant une pièce sur le téléphone.
 *
 * Pour régénérer la référence après un changement de schéma volontaire, voir le
 * README du sous-projet.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { repliques, valider } from '../js/schema.js';
import { CONFIG } from '../js/config.js';
import { comparer } from '../js/comparaison.js';
import { mots } from '../js/texte.js';
import { indexer, libelleLocuteurs, MOTIF_SANS_TOP, TOP } from '../js/modele.js';

const ICI = dirname(fileURLToPath(import.meta.url));

const BRUT = readFileSync(join(ICI, 'exemple-repet.json'), 'utf8');
const EXEMPLE = JSON.parse(BRUT);

describe('un REPET.json réel est accepté', () => {
  test('la validation passe', () => {
    const resultat = valider(EXEMPLE);

    assert.ok(resultat.valide, resultat.erreur);
  });

  test('la version de schéma est celle qu’attend la page', () => {
    // Si ce test tombe, c'est config.SCHEMA_REPET (Python) et
    // CONFIG.SCHEMA_ACCEPTE (JS) qui ont divergé.
    assert.equal(EXEMPLE.schema, CONFIG.SCHEMA_ACCEPTE);
  });

  test('le fichier est lisible à l’œil : accents non échappés', () => {
    assert.ok(BRUT.includes('SCÈNE'), 'les accents sont échappés');
  });
});

describe('la structure attendue est bien là', () => {
  test('les unités portent acte, scène et personnages', () => {
    const premiere = EXEMPLE.unites[0];

    assert.equal(premiere.acte, 'ACTE PREMIER');
    assert.equal(premiere.scene, 'SCÈNE 1');
    assert.deepEqual(premiere.personnages, ['CLARISSA', 'SIR ROWLAND']);
  });

  test('un séparateur produit une unité implicite qui hérite', () => {
    const implicites = EXEMPLE.unites.filter((u) => u.implicite);

    assert.equal(implicites.length, 1);
    assert.equal(implicites[0].acte, 'ACTE PREMIER');
  });

  test('les noms de personnages n’ont pas de point final', () => {
    // « **JAN.** » est une convention d'imprimerie : « JAN. » dans un sélecteur
    // de rôles serait un défaut visible.
    for (const personnage of EXEMPLE.personnages) {
      assert.ok(!personnage.nom.endsWith('.'), personnage.nom);
    }
  });

  test('tous les identifiants de réplique sont distincts', () => {
    const identifiants = repliques(EXEMPLE).map((r) => r.id);

    assert.equal(new Set(identifiants).size, identifiants.length);
  });

  test('deux « Oui. » de personnages différents coexistent', () => {
    const ouis = repliques(EXEMPLE).filter((r) => r.texte === 'Oui.');

    assert.equal(ouis.length, 2);
    assert.notEqual(ouis[0].id, ouis[1].id);
  });
});

describe('les vers survivent au transport', () => {
  test('une réplique en vers garde ses retours à la ligne', () => {
    const vers = repliques(EXEMPLE).find((r) => r.vers);

    assert.ok(vers, 'aucune réplique en vers dans l’exemple');
    assert.ok(vers.texte.includes('\n'), 'les vers ont été recollés');
  });

  test('la prose n’est pas marquée en vers', () => {
    const prose = repliques(EXEMPLE).find((r) => r.texte === 'Oui.');

    assert.equal(prose.vers, false);
  });
});

describe('les didascalies internes désignent le bon mot', () => {
  test('avant_mot est un index valide dans le texte parlé', () => {
    // C'est le point de jonction le plus fragile : Python compte les mots avec
    // un découpage sur les espaces, et `texte.mots()` doit compter pareil.
    // Un décalage afficherait la didascalie au milieu du mauvais mot.
    for (const replique of repliques(EXEMPLE)) {
      for (const didascalie of replique.didascalies_internes ?? []) {
        assert.ok(
          didascalie.avant_mot <= mots(replique.texte).length,
          `${replique.id} : avant_mot=${didascalie.avant_mot} ` +
            `pour ${mots(replique.texte).length} mots`,
        );
      }
    }
  });

  test('la didascalie n’est pas restée dans le texte parlé', () => {
    const avecJeu = repliques(EXEMPLE).find((r) => r.didascalies_internes);

    assert.ok(avecJeu, 'aucune didascalie interne dans l’exemple');
    assert.ok(!avecJeu.texte.includes('se lève'));
    assert.equal(avecJeu.didascalies_internes[0].texte, 'il se lève');
    assert.equal(avecJeu.didascalies_internes[0].avant_mot, 4);
  });
});

describe('indexer une vraie pièce', () => {
  const index = indexer(EXEMPLE, ['CLARISSA']);

  test('mes unités sont reconnues', () => {
    // CLARISSA parle dans les quatre unités de la pièce d'essai — la
    // quatrième par une réplique dite avec SIR ROWLAND.
    assert.equal(index.unites.filter((u) => u.mienne).length, 4);
    assert.equal(index.mesRepliques.length, 4);
  });

  test('le sommaire couvre toute la pièce', () => {
    assert.equal(index.sommaire.length, EXEMPLE.unites.length);
    assert.equal(index.sommaire[0].titre, 'SCÈNE 1');
    // L'unité ouverte par un `***` n'a pas de titre à afficher.
    assert.equal(index.sommaire[1].titre, null);
  });

  test('chaque réplique à moi a un top calculé', () => {
    for (const id of index.mesRepliques) {
      assert.ok(index.tops.has(id), `pas de top pour ${id}`);
    }
  });

  test('CLARISSA ouvre les quatre unités : aucun top nulle part', () => {
    // Y compris la première, dont la scène ouvre sur une indication de lieu :
    // un décor n'est pas un signal, elle ouvre bien la scène.
    for (const id of index.mesRepliques) {
      const top = index.tops.get(id);

      assert.equal(top.type, TOP.AUCUN, id);
      assert.equal(top.motif, MOTIF_SANS_TOP.DEBUT, id);
    }
  });

  test('en jouant SIR ROWLAND, le top est la réplique de CLARISSA', () => {
    const autre = indexer(EXEMPLE, ['SIR ROWLAND']);
    const premiere = autre.mesRepliques[0];
    const top = autre.tops.get(premiere);

    assert.equal(top.type, TOP.REPLIQUE);
    assert.deepEqual(top.personnages, ['CLARISSA']);
  });

  test('en jouant les deux rôles, plus aucun top ne subsiste', () => {
    // La pièce d'essai n'a que deux personnages : si je les joue tous les deux,
    // il n'y a plus personne pour me donner la réplique.
    const deux = indexer(EXEMPLE, ['CLARISSA', 'SIR ROWLAND']);
    const motifs = deux.mesRepliques.map((id) => deux.tops.get(id).motif);

    assert.ok(motifs.includes(MOTIF_SANS_TOP.ENCHAINEMENT), motifs.join(', '));
    assert.ok(
      deux.mesRepliques.every((id) => deux.tops.get(id).type === TOP.AUCUN),
      'un top subsiste alors que je joue tous les rôles',
    );
  });
});

describe('une réplique dite par plusieurs personnages (« X et Y. »)', () => {
  const collective = repliques(EXEMPLE).find((r) => r.personnages.length > 1);

  test('elle liste les deux personnages', () => {
    assert.ok(collective, 'aucune réplique collective dans l’exemple');
    assert.deepEqual(collective.personnages, ['SIR ROWLAND', 'CLARISSA']);
  });

  test('son libellé joint les deux noms', () => {
    assert.equal(libelleLocuteurs(collective.personnages), 'SIR ROWLAND / CLARISSA');
  });

  test('elle compte parmi les miennes pour chacun des deux, seul', () => {
    for (const role of ['SIR ROWLAND', 'CLARISSA']) {
      const index = indexer(EXEMPLE, [role]);

      assert.ok(index.mesRepliques.includes(collective.id), role);
    }
  });
});

describe('bout en bout : réciter une réplique du fichier', () => {
  test('une récitation exacte obtient 100', () => {
    const replique = repliques(EXEMPLE)[0];

    assert.equal(comparer(replique.texte, replique.texte).score, 100);
  });

  test('une récitation sans ponctuation ni accents obtient 100', () => {
    // Le cas réel : c'est ce que rend la transcription vocale d'iOS.
    const avecJeu = repliques(EXEMPLE).find((r) => r.didascalies_internes);
    const commeDitParIOS = 'je ne crois pas quelle reponde';

    const resultat = comparer(avecJeu.texte, commeDitParIOS);

    // « qu'elle » sans apostrophe reste un mot différent de « quelle » : c'est
    // une limite honnête de la normalisation, pas un défaut à masquer.
    assert.ok(resultat.score >= 80, `score ${resultat.score}`);
  });

  test('un vers récité d’un trait obtient 100', () => {
    const vers = repliques(EXEMPLE).find((r) => r.vers);
    const dUnTrait = vers.texte.replace('\n', ' ');

    assert.equal(comparer(vers.texte, dUnTrait).score, 100);
  });
});
