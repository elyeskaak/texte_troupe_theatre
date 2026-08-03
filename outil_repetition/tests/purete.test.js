/**
 * Contrôle mécanique de la pureté des modules.
 *
 * Transposition du test qui garde `utils/blocks.py` pur dans `outil_edition`, où
 * l'absence d'`os`, `time`, `openai` et `docx` est vérifiée par analyse AST.
 *
 * Sans ce test, la pureté se dégrade au premier correctif pressé : un
 * `localStorage.getItem` glissé dans `texte.js` pour « mémoriser un réglage »
 * rendrait le module inchargeable par Node, et la suite entière tomberait sans
 * qu'on comprenne pourquoi. Ici, elle tombe **en nommant le coupable**.
 *
 * Le contrôle est lexical et non syntaxique, ce qui est assumé : il peut se
 * tromper sur une occurrence en commentaire. Les commentaires sont donc retirés
 * avant l'examen.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const RACINE = join(dirname(fileURLToPath(import.meta.url)), '..');

/** Les modules qui doivent rester purs. */
const MODULES_PURS = [
  'config.js',
  'schema.js',
  'texte.js',
  'comparaison.js',
  'tirage.js',
  'modele.js',
  'etat.js',
];

/**
 * Ce qu'un module pur ne doit pas contenir.
 *
 * `Math.random` et `Date.now` sont interdits au même titre que le DOM : un
 * module qui les appelle n'est pas testable, puisque deux exécutions donnent
 * deux résultats. C'est le défaut exact du prototype, dont les mots à trous se
 * déplaçaient à chaque rendu.
 */
const INTERDITS = [
  'document',
  'window',
  'localStorage',
  'sessionStorage',
  'navigator',
  'fetch(',
  'Math.random',
  'Date.now',
  'new Date',
  'setTimeout',
  'setInterval',
];

/** Retire commentaires de bloc et de ligne, pour ne juger que du code. */
function sansCommentaires(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/\/\/[^\n]*/g, ' ');
}

for (const nom of MODULES_PURS) {
  test(`${nom} est pur`, () => {
    const code = sansCommentaires(
      readFileSync(join(RACINE, 'js', nom), 'utf8'),
    );

    for (const interdit of INTERDITS) {
      assert.ok(
        !code.includes(interdit),
        `${nom} contient « ${interdit} » : le module n'est plus pur, ` +
          'et il n’est plus testable sans navigateur.',
      );
    }
  });
}

test('le contrôle trouve bien quelque chose à examiner', () => {
  // Garde-fou : un chemin faux rendrait tous les tests ci-dessus verts sans
  // rien vérifier. C'est le même garde-fou que `test_documentation.py`.
  const code = readFileSync(join(RACINE, 'js', 'texte.js'), 'utf8');

  assert.ok(code.length > 1000, 'texte.js paraît vide : chemin erroné ?');
  assert.ok(code.includes('export function normaliser'));
});

test('un module impur serait bien détecté', () => {
  // Vérifie le détecteur lui-même sur un cas fabriqué : sans cela, une
  // expression mal écrite dans INTERDITS passerait inaperçue.
  const faux = sansCommentaires('const x = 1; // document\nlocalStorage.getItem("a");');

  assert.ok(INTERDITS.some((interdit) => faux.includes(interdit)));
  assert.ok(!sansCommentaires('const x = 1; // document').includes('document'));
});
