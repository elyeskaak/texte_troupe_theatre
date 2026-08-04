/**
 * Service worker — ouverture hors ligne.
 *
 * Un outil de coulisses doit s'ouvrir sans réseau : préchargement d'une liste
 * **explicite** à l'installation, puis **réseau d'abord, cache en repli**.
 *
 * L'ordre a compté plus que tout le reste, et il est justifié en détail sur
 * `reseauDAbord`. En un mot : le cache d'abord rend la panne auto-scellante, parce
 * que le remède qu'on déploie voyage par le canal même qui est bloqué.
 *
 * `maj.html` est volontairement **hors** de `FICHIERS`, pour la même raison : une
 * issue de secours mise en cache est une issue de secours périmable.
 *
 * **Les pièces ne passent jamais ici.** Elles vivent dans `localStorage`, donc
 * elles ne transitent pas par le réseau et ne peuvent pas entrer dans ce cache.
 * C'est voulu : le cache d'un service worker est visible par l'outil de
 * développement du navigateur, et un texte sous droits n'a pas à y traîner.
 *
 * **Ce cache fait partie de ce que Safari purge après sept jours d'inactivité.**
 * Après une purge, le premier chargement exige donc du réseau, puis tout
 * redevient hors ligne. C'est une limite à connaître, pas un défaut à corriger :
 * aucune API ne permet de s'en exempter depuis iOS 17.4.
 */

/**
 * À incrémenter **à la main** à chaque déploiement.
 *
 * L'oubli n'est plus fatal depuis le passage au réseau d'abord — c'était tout
 * l'objet du changement. La version garde deux rôles : évincer les anciens caches
 * à l'`activate`, et donner un nom lisible à ce qu'on inspecte.
 *
 * `tests/cablage.test.js` échoue si un fichier caché change sans qu'elle bouge. Ce
 * garde-fou reste utile, mais il n'est plus la seule ligne de défense — il l'a été,
 * et cela n'a pas suffi.
 */
const VERSION = 'repetition-v25';

const FICHIERS = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icone.svg',
  './js/app.js',
  './js/comparaison.js',
  './js/config.js',
  './js/etat.js',
  './js/manifeste.js',
  './js/modele.js',
  './js/rendu.js',
  './js/schema.js',
  './js/stockage.js',
  './js/texte.js',
  './js/tirage.js',
  './js/voix.js',
];

self.addEventListener('install', (evenement) => {
  evenement.waitUntil(
    (async () => {
      const cache = await caches.open(VERSION);

      // `addAll` échoue en bloc si un seul fichier manque, ce qui laisserait
      // l'outil sans cache du tout. On ajoute donc un par un, en signalant les
      // absents : mieux vaut un cache incomplet qu'aucun cache.
      await Promise.all(
        FICHIERS.map(async (chemin) => {
          try {
            await cache.add(new Request(chemin, { cache: 'reload' }));
          } catch (erreur) {
            console.warn(`[sw] non mis en cache : ${chemin}`, erreur);
          }
        }),
      );

      // Le nouveau worker prend la main sans attendre la fermeture des onglets :
      // sur un téléphone, l'onglet n'est jamais fermé, et une correction
      // attendrait des semaines.
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener('activate', (evenement) => {
  evenement.waitUntil(
    (async () => {
      for (const nom of await caches.keys()) {
        if (nom !== VERSION) {
          await caches.delete(nom);
        }
      }

      await self.clients.claim();
    })(),
  );
});

/**
 * Délai au-delà duquel on renonce au réseau et sert le cache.
 *
 * En coulisses, le réseau est souvent présent mais mauvais — le pire des cas,
 * car une requête qui n'échoue pas franchement peut pendre une minute. Deux
 * secondes et demie : au-delà, mieux vaut la version d'hier tout de suite que la
 * version du jour dans trente secondes.
 */
const DELAI_RESEAU_MS = 2500;

/** Ce que le cache a le droit de contenir, en chemins absolus. */
const CACHABLES = new Set(
  FICHIERS.map((chemin) => new URL(chemin, self.location.href).pathname),
);

/**
 * **Réseau d'abord, cache en repli** — et non l'inverse, comme au début.
 *
 * Le premier jet servait le cache d'abord. C'était le choix évident, et il était
 * mauvais pour une raison qui n'apparaît qu'après la panne : **il rend le défaut
 * auto-scellant**. Si `VERSION` n'est pas incrémentée, l'appareil ne redemande
 * jamais rien ; la correction poussée n'arrive pas ; et le remède qu'on ajoute
 * dans le code — un bouton de purge, un meilleur message — voyage précisément par
 * le canal qui est bloqué. On ne peut donc pas se dépanner par où l'on répare.
 *
 * C'est arrivé pour de bon : un appareil est resté sur les fichiers de v19 à
 * travers v20, v21 et v22, refusant un schéma que le dépôt acceptait depuis
 * longtemps. Aucune correction ne pouvait l'atteindre.
 *
 * Le réseau d'abord retourne la dépendance : quand il y a du réseau, le code est
 * frais, toujours, et l'oubli d'un numéro de version n'a plus de conséquence
 * visible. Le cache ne sert plus qu'à ce pour quoi il a été mis là — ouvrir
 * l'outil sans réseau — et ne peut plus décider de ce qu'on exécute.
 *
 * Le prix est un aller-retour réseau au démarrage quand on est connecté. Sur
 * douze fichiers de quelques kilo-octets, il est imperceptible ; et l'exigence
 * était de s'ouvrir **sans** réseau, pas de s'ouvrir instantanément avec.
 *
 * **`cache: 'no-store'` sur le `fetch`, et c'est délibéré.** GitHub Pages sert
 * ces fichiers avec `Cache-Control: max-age=600` : sans cette option, ce
 * `fetch` reste soumis au cache HTTP ordinaire du navigateur et peut resservir
 * une réponse vieille de dix minutes **sans aller au réseau du tout** — donc
 * sans jamais voir un correctif tout juste déployé, malgré la stratégie
 * « réseau d'abord ». Repéré exactement de cette façon : un correctif poussé,
 * `VERSION` incrémentée, et pourtant invisible pendant les dix minutes
 * suivantes sur un navigateur qui avait déjà chargé la page.
 */
async function reseauDAbord(requete) {
  try {
    const reponse = await Promise.race([
      fetch(requete, { cache: 'no-store' }),
      new Promise((_, rejeter) =>
        setTimeout(() => rejeter(new Error('délai réseau dépassé')), DELAI_RESEAU_MS),
      ),
    ]);

    // Seuls les fichiers de l'outil entrent au cache. Sans ce filtre, la page de
    // tests et les fixtures s'y installeraient — sans dommage, mais le cache
    // cesserait de dire ce qu'il contient, et c'est déjà trop.
    if (reponse.ok && CACHABLES.has(new URL(requete.url).pathname)) {
      const cache = await caches.open(VERSION);

      await cache.put(requete, reponse.clone());
    }

    return reponse;
  } catch (erreur) {
    const enCache = await caches.match(requete, { ignoreSearch: true });

    if (enCache) {
      return enCache;
    }

    // Hors ligne et hors cache : pour une navigation, on rend la page d'accueil
    // plutôt qu'une erreur de navigateur, qui ne dirait rien.
    if (requete.mode === 'navigate') {
      const repli = await caches.match('./index.html');

      if (repli) {
        return repli;
      }
    }

    throw erreur;
  }
}

self.addEventListener('fetch', (evenement) => {
  const requete = evenement.request;

  // Une requête POST ou vers un autre domaine passe directement au réseau.
  if (requete.method !== 'GET' || new URL(requete.url).origin !== self.location.origin) {
    return;
  }

  evenement.respondWith(reseauDAbord(requete));
});
