/**
 * Service worker — ouverture hors ligne.
 *
 * Un outil de coulisses doit s'ouvrir sans réseau. La stratégie est
 * volontairement banale, parce qu'il n'y a rien à gagner à être astucieux :
 * préchargement d'une liste **explicite** à l'installation, puis cache d'abord.
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
 * Sans changement de nom, un navigateur qui a déjà le cache ne va jamais
 * rechercher les fichiers : une correction poussée sur GitHub Pages resterait
 * invisible sur le téléphone, indéfiniment. C'est le piège classique du service
 * worker, et la seule protection est de ne pas oublier cette ligne.
 */
const VERSION = 'repetition-v7';

const FICHIERS = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icone.svg',
  './js/app.js',
  './js/comparaison.js',
  './js/config.js',
  './js/etat.js',
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

self.addEventListener('fetch', (evenement) => {
  const requete = evenement.request;

  // Seules les navigations et les ressources de l'outil sont servies du cache.
  // Une requête POST ou vers un autre domaine passe directement au réseau.
  if (requete.method !== 'GET' || new URL(requete.url).origin !== self.location.origin) {
    return;
  }

  evenement.respondWith(
    (async () => {
      const enCache = await caches.match(requete, { ignoreSearch: true });

      if (enCache) {
        return enCache;
      }

      try {
        return await fetch(requete);
      } catch (erreur) {
        // Hors ligne et hors cache : pour une navigation, on rend la page
        // d'accueil plutôt qu'une erreur de navigateur, qui ne dirait rien.
        if (requete.mode === 'navigate') {
          const repli = await caches.match('./index.html');

          if (repli) {
            return repli;
          }
        }

        throw erreur;
      }
    })(),
  );
});
