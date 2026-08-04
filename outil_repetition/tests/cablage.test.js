/**
 * Cohérence du câblage entre `index.html` et les modules.
 *
 * **Pourquoi ces tests existent.** Deux défauts réels ont échappé à toute la
 * suite, et ils avaient la même forme : deux endroits du code se référaient l'un
 * à l'autre, l'un a changé, l'autre non. Aucun n'était faux isolément.
 *
 * - `btn-retour-roles` affichait l'écran des rôles sans le reconstruire. Cela
 *   marchait tant que l'écran était toujours traversé à l'ouverture ; la
 *   mémorisation des rôles a supprimé ce passage, et le bouton est devenu inerte.
 * - « Sommaire » et « Bilan » ouvraient exactement le même écran. Deux boutons
 *   pour une action, personne ne l'a vu.
 * - L'ordre des modes vivait à la fois dans le HTML et dans `app.js` : inverser
 *   deux crans d'un seul côté aurait fait mentir les crans « franchis ».
 *
 * **Ce que ces tests sont, et ne sont pas.** Ils lisent les fichiers comme du
 * texte et vérifient que les références se répondent. Ce n'est pas du test de
 * comportement : ils ne cliquent sur rien. Mais ils attrapent la dérive entre
 * deux fichiers, qui est précisément ce qui nous a échappé — et ils le font sans
 * navigateur ni dépendance, donc dans la suite ordinaire.
 *
 * Le comportement, lui, est éprouvé par `tests.html`, qui pilote la vraie page.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { MODE } from '../js/etat.js';

const RACINE = join(dirname(fileURLToPath(import.meta.url)), '..');

const html = readFileSync(join(RACINE, 'index.html'), 'utf8');
const app = readFileSync(join(RACINE, 'js', 'app.js'), 'utf8');
const sw = readFileSync(join(RACINE, 'sw.js'), 'utf8');

/** Retire les commentaires JS, pour ne juger que du code. */
function sansCommentaires(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/\/\/[^\n]*/g, ' ');
}

const codeApp = sansCommentaires(app);

/** Identifiants déclarés dans le HTML. */
const idsHtml = new Set([...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]));

/** Identifiants réclamés par `app.js` via `$('…')`. */
const idsReclames = new Set([...codeApp.matchAll(/\$\('([^']+)'\)/g)].map((m) => m[1]));

describe('les identifiants se répondent', () => {
  test('tout id réclamé par app.js existe dans le HTML', () => {
    // C'est le défaut le plus bête et le plus silencieux : `$('btn-disparu')`
    // rend `null`, et l'écouteur lève au chargement — donc *toute* la page
    // devient inerte, pas seulement ce bouton.
    const manquants = [...idsReclames].filter((id) => !idsHtml.has(id));

    assert.deepEqual(manquants, [], `ids absents du HTML : ${manquants.join(', ')}`);
  });

  test('tout bouton du HTML est utilisé par app.js', () => {
    // Un bouton sans écouteur est un bouton mort : il paraît cliquable et ne
    // fait rien. C'est exactement ce qu'était « Changer de rôle ».
    const boutons = [...html.matchAll(/<button[^>]*\sid="([^"]+)"/g)].map((m) => m[1]);
    const orphelins = boutons.filter((id) => !codeApp.includes(`'${id}'`));

    assert.deepEqual(orphelins, [], `boutons sans écouteur : ${orphelins.join(', ')}`);
  });

  test('aucun identifiant en double dans le HTML', () => {
    const tous = [...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]);
    const doublons = tous.filter((id, rang) => tous.indexOf(id) !== rang);

    assert.deepEqual(doublons, [], `ids en double : ${doublons.join(', ')}`);
  });
});

describe('deux boutons ne font pas la même chose', () => {
  /** L'écran (`<section id="ecran-…">`) qui contient un identifiant donné. */
  function ecranDe(id) {
    const avant = html.slice(0, html.indexOf(`id="${id}"`));
    const sections = [...avant.matchAll(/<section id="(ecran-[^"]+)"/g)];

    return sections.length ? sections.at(-1)[1] : '(hors écran)';
  }

  /** Les identifiants câblés sur chaque gestionnaire nommé. */
  const parGestionnaire = new Map();

  for (const [, id, appel] of codeApp.matchAll(
    /\$\('([^']+)'\)\.addEventListener\('click',\s*([A-Za-z_$][\w$]*)\s*\)/g,
  )) {
    parGestionnaire.set(appel, [...(parGestionnaire.get(appel) ?? []), id]);
  }

  test('aucun écran n’offre deux fois la même action', () => {
    // « Sommaire » et « Bilan » appelaient tous deux `ouvrirBilan`, sur le même
    // écran : deux commandes pour une action, que rien ne signalait.
    //
    // La nuance importe. La première version de ce test interdisait *tout*
    // partage de gestionnaire, et accusait aussitôt les trois boutons
    // « Sauvegarder » — qui sont légitimes, un par écran : on doit pouvoir
    // sauvegarder d'où l'on est. Le défaut n'est pas de réutiliser une action,
    // c'est de la proposer deux fois au même endroit, où l'une des deux est
    // forcément de trop.
    const doubles = [];

    for (const [appel, ids] of parGestionnaire) {
      const ecrans = ids.map(ecranDe);
      const repetes = ecrans.filter((ecran, rang) => ecrans.indexOf(ecran) !== rang);

      for (const ecran of new Set(repetes)) {
        doubles.push(`${appel} deux fois sur ${ecran}`);
      }
    }

    assert.deepEqual(doubles, [], doubles.join(' ; '));
  });

  test('une action réutilisée porte partout le même libellé', () => {
    // Le même geste nommé « Exporter » ici et « Sauvegarder » là se lit comme
    // deux fonctions distinctes. C'est ce que faisaient les trois boutons de
    // sauvegarde, dont les identifiants `-2` et `-3` ne disaient rien non plus.
    const discordances = [];

    for (const [appel, ids] of parGestionnaire) {
      if (ids.length < 2) {
        continue;
      }

      const libelles = new Set(
        ids
          .map((id) => html.match(new RegExp(`id="${id}"[^>]*>([^<]*)<`))?.[1]?.trim())
          .filter(Boolean),
      );

      if (libelles.size > 1) {
        discordances.push(`${appel} : ${[...libelles].join(' / ')}`);
      }
    }

    assert.deepEqual(discordances, [], discordances.join(' ; '));
  });
});

describe('les modes se répondent des trois côtés', () => {
  const modesHtml = [...html.matchAll(/data-mode="([^"]+)"/g)].map((m) => m[1]);
  const modesDeclares = Object.values(MODE);

  test('chaque mode déclaré a son cran dans le HTML', () => {
    const absents = modesDeclares.filter((mode) => !modesHtml.includes(mode));

    assert.deepEqual(absents, [], `modes sans cran : ${absents.join(', ')}`);
  });

  test('chaque cran du HTML correspond à un mode déclaré', () => {
    // Un `data-mode` inconnu fait lever `changerMode`, qui refuse à juste titre.
    const inconnus = modesHtml.filter((mode) => !modesDeclares.includes(mode));

    assert.deepEqual(inconnus, [], `crans inconnus : ${inconnus.join(', ')}`);
  });

  test('chaque mode a une description', () => {
    // Sans elle, le mode s'affiche sans un mot d'explication — c'est ce qui
    // rendait « Au top » incompréhensible.
    const bloc = codeApp.slice(codeApp.indexOf('DESCRIPTIONS_MODES'));
    const sansDescription = modesDeclares.filter(
      (mode) => !new RegExp(`^\\s*${mode}:`, 'm').test(bloc),
    );

    assert.deepEqual(sansDescription, [], sansDescription.join(', '));
  });

  test('chaque mode figure dans l’échelle d’exigence', () => {
    const echelle = codeApp.slice(
      codeApp.indexOf('ORDRE_EXIGENCE'),
      codeApp.indexOf('];', codeApp.indexOf('ORDRE_EXIGENCE')),
    );
    const absents = modesDeclares.filter(
      (mode) => !echelle.includes(mode.toUpperCase()),
    );

    assert.deepEqual(absents, [], `absents de l’échelle : ${absents.join(', ')}`);
  });

  test('l’ordre du HTML et celui de l’échelle concordent', () => {
    // Ils vivent à deux endroits, et inverser deux crans d'un seul côté ferait
    // mentir les crans « franchis » sans que rien ne le signale. C'est ce qui a
    // failli arriver en échangeant « Aveugle » et « Au top ».
    const numerotes = [
      ...html.matchAll(/data-mode="([^"]+)"><span>(\d+)<\/span>/g),
    ]
      .sort((a, b) => Number(a[2]) - Number(b[2]))
      .map((m) => m[1]);

    const echelle = codeApp.slice(
      codeApp.indexOf('const ORDRE_EXIGENCE'),
      codeApp.indexOf('];', codeApp.indexOf('const ORDRE_EXIGENCE')),
    );
    const ordreApp = [...echelle.matchAll(/MODE\.([A-Z_]+)/g)].map((m) =>
      m[1].toLowerCase(),
    );

    assert.deepEqual(
      numerotes,
      ordreApp.map((nom) => MODE[nom.toUpperCase()]),
      'l’ordre des crans diffère entre le HTML et ORDRE_EXIGENCE',
    );
  });

  test('les numéros des crans sont consécutifs à partir de 1', () => {
    const numeros = [...html.matchAll(/class="cran"[^>]*><span>(\d+)<\/span>/g)].map(
      (m) => Number(m[1]),
    );

    assert.deepEqual(
      numeros,
      numeros.map((_, rang) => rang + 1),
      `numérotation cassée : ${numeros.join(', ')}`,
    );
  });
});

/**
 * Chaque import relatif d'`app.js` doit résoudre vers un fichier réel.
 *
 * **Pourquoi ce test existe.** `import * as drive from '../pieces/drive.js'`
 * a été écrit dans `app.js` (qui vit dans `js/`) en oubliant qu'un `import`
 * résout **relativement au fichier qui importe**, et non relativement à la
 * page HTML comme le fait `fetch()` — la confusion exacte qui a cassé
 * l'outil en production : `app.js` échouait à charger tout son graphe de
 * modules, donc n'exécutait **plus aucune ligne**, le bandeau « cette page ne
 * peut pas fonctionner » restant affiché même servi en HTTPS. Aucun test
 * existant ne l'attrapait : `cablage.test.js` ne vérifiait jusqu'ici que les
 * imports en `./`, et aucun test ne charge réellement `app.js` comme un vrai
 * module (il touche le DOM dès son évaluation, donc ce n'est pas testable
 * par `node --test` sans navigateur — voir §6 de `ARCHITECTURE.md`). Ce test
 * ne charge rien : il vérifie seulement que le fichier visé **existe**, ce
 * qui suffit à attraper cette classe d'erreur sans navigateur.
 */
describe('les imports de app.js résolvent vers un fichier existant', () => {
  test('aucun import relatif ne pointe dans le vide', () => {
    const specifiers = [...codeApp.matchAll(/^import[^;]*from\s+'([^']+)';/gm)].map(
      (m) => m[1],
    );

    const manquants = specifiers
      .filter((specifier) => specifier.startsWith('.'))
      .filter((specifier) => !existsSync(join(RACINE, 'js', specifier)));

    assert.deepEqual(manquants, [], `imports introuvables : ${manquants.join(', ')}`);
  });
});

/** Les chemins de la liste `FICHIERS` de `sw.js`, sans les commentaires alentour. */
function fichiersDuCache() {
  const debut = sw.indexOf('const FICHIERS');

  return [...sw.slice(debut, sw.indexOf('];', debut)).matchAll(/'\.\/([^']*)'/g)]
    .map((trouve) => trouve[1])
    .filter(Boolean); // « ./ » est un alias d'index.html, pas un fichier
}

describe('le service worker suit les fichiers', () => {
  test('chaque module de js/ est préchargé', () => {
    // Un module oublié rend l'outil inutilisable hors ligne, sans erreur
    // visible tant qu'on a du réseau.
    const modules = [...html.matchAll(/src="js\/([^"]+)"/g)].map((m) => m[1]);
    const importes = [...readFileSync(join(RACINE, 'js', 'app.js'), 'utf8')
      .matchAll(/from '\.\/([^']+)'/g)].map((m) => m[1]);

    for (const fichier of [...modules, ...importes]) {
      assert.ok(
        sw.includes(`./js/${fichier}`),
        `${fichier} n’est pas dans la liste de préchargement de sw.js`,
      );
    }
  });

  test('la version du cache est bien une constante à incrémenter', () => {
    assert.match(sw, /const VERSION = 'repetition-v\d+';/);
  });

  test('l’issue de secours n’est jamais mise en cache', () => {
    // `maj.html` sert à sortir d'un cache périmé. La mettre en cache la rendrait
    // périmable, donc inutile précisément le jour où elle sert : on se retrouverait
    // à devoir réparer le réparateur. Ce test existe pour qu'aucune bonne intention
    // future — « tant qu'on y est, mettons tout hors ligne » — ne referme la porte.
    // On inspecte la **liste**, non le fichier entier : la première version de ce
    // test cherchait « maj.html » dans tout `sw.js` et se déclenchait sur le
    // commentaire qui explique justement pourquoi elle n'y est pas. Un test doit
    // porter sur la portée exacte de ce qu'il affirme.
    assert.ok(
      !fichiersDuCache().includes('maj.html'),
      'maj.html figure dans FICHIERS : elle doit rester hors du cache',
    );
    assert.ok(
      html.includes('./maj.html'),
      'l’accueil doit pointer vers l’issue de secours, sinon elle est introuvable',
    );
  });

  test('le service worker demande le réseau avant le cache', () => {
    // Le cache d'abord rend le défaut auto-scellant : sans nouvelle VERSION,
    // l'appareil ne redemande jamais rien, et le remède qu'on déploie voyage par
    // le canal bloqué. Un appareil est resté sur v19 à travers trois versions.
    assert.ok(
      sw.includes('reseauDAbord'),
      'sw.js ne suit plus la stratégie « réseau d’abord »',
    );
    assert.ok(
      /const DELAI_RESEAU_MS = \d+;/.test(sw),
      'le repli sur le cache doit être borné dans le temps : un réseau lent mais ' +
        'présent est le pire cas, et pendrait indéfiniment sans délai de garde',
    );
  });

  /**
   * La version du cache doit changer dès qu'un fichier caché change.
   *
   * **Ce test existe parce que son absence a cassé l'outil sur le téléphone.**
   * `outil_edition` est passé au schéma `repetition/2` ; cinq modules ont suivi ;
   * `sw.js` n'a pas été touché. Le cache s'appelait donc toujours
   * `repetition-v19` et contenait l'ancien `config.js`, qui n'acceptait que
   * `repetition/1`. En stratégie « cache d'abord », rien n'est jamais redemandé :
   * l'import refusait le JSON avec un message conseillant de mettre la page à
   * jour — ce que le service worker rendait précisément impossible.
   *
   * Le test précédent ne vérifiait que la *forme* de la constante. Il passait
   * pendant que le défaut partait en production, ce qui est pire que rien : il
   * donnait l'impression que la question était couverte.
   *
   * Le mécanisme est volontairement bête. On enregistre dans
   * `tests/empreinte-cache.json` le couple (version, empreinte des fichiers). Si
   * les fichiers changent sans que la version bouge, ce test échoue et donne la
   * valeur à recopier. Oublier devient impossible, au prix d'une ligne à mettre à
   * jour — le bon échange, puisque l'oubli ne se voyait qu'une semaine plus tard,
   * sur un téléphone, loin de tout outil de diagnostic.
   */
  test('la version change dès qu’un fichier caché change', () => {
    const chemins = fichiersDuCache();
    const empreinte = createHash('sha1');

    for (const chemin of chemins.sort()) {
      // Le chemin entre dans l'empreinte : renommer un fichier sans changer son
      // contenu modifie bien ce que le cache contient.
      empreinte.update(chemin);
      empreinte.update(readFileSync(join(RACINE, chemin)));
    }

    const calculee = empreinte.digest('hex').slice(0, 16);
    const version = sw.match(/const VERSION = '([^']+)';/)[1];
    const enregistre = JSON.parse(
      readFileSync(join(RACINE, 'tests', 'empreinte-cache.json'), 'utf8'),
    );

    const aJour = JSON.stringify({ version, empreinte: calculee }, null, 2);

    if (calculee !== enregistre.empreinte) {
      assert.notEqual(
        version,
        enregistre.version,
        `Les fichiers mis en cache ont changé, mais VERSION vaut toujours ` +
          `« ${version} ». Incrémentez-la dans sw.js, sinon la correction restera ` +
          `invisible sur les appareils qui ont déjà le cache.`,
      );
    }

    assert.equal(
      aJour,
      JSON.stringify(enregistre, null, 2),
      `Recopiez ceci dans tests/empreinte-cache.json :\n${aJour}`,
    );
  });
});

describe('les écrans sont tous déclarés', () => {
  test('chaque section de premier niveau figure dans ECRANS', () => {
    // Un écran absent de la liste ne serait jamais masqué : deux écrans
    // s'afficheraient l'un sous l'autre.
    const sections = [...html.matchAll(/<section id="(ecran-[^"]+)"/g)].map((m) => m[1]);
    const liste = codeApp.slice(codeApp.indexOf('const ECRANS'));
    const absents = sections.filter((id) => !liste.includes(`'${id}'`));

    assert.deepEqual(absents, [], `écrans hors de ECRANS : ${absents.join(', ')}`);
  });
});
