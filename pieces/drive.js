/**
 * Client Google Drive, partagé entre `outil_repetition` et `outil_lecture`.
 *
 * Voir `outil_repetition/ARCHITECTURE.md` §3.3 et `outil_lecture/ARCHITECTURE.md`
 * §4.3 pour le mécanisme complet (pourquoi Drive, pourquoi le Picker plutôt
 * qu'un accès large, pourquoi ce module est partagé). Ce fichier ne documente
 * que ce qui ne se lit pas déjà là-bas.
 *
 * Vit dans `pieces/`, frère des deux outils et non fils de l'un d'eux : ni
 * `outil_repetition` ni `outil_lecture` ne dépend du reste du code de l'autre,
 * seul ce module est partagé (exception assumée, voir les deux ARCHITECTURE.md
 * ci-dessus).
 *
 * `outil_repetition` l'importe statiquement (`import * as drive from
 * '../pieces/drive.js'`) — il exige déjà des modules ES, donc HTTPS. `outil_lecture`
 * l'importe **dynamiquement** (`await import('../pieces/drive.js')`), seule façon
 * de charger un module ES depuis un fichier par ailleurs fait de scripts
 * classiques ; l'échec de cet `import()` sous `file://` est géré par l'appelant,
 * pas ici.
 *
 * Comme `stockage.js`, ce module sépare ce qui est **injectable et testable**
 * (construction d'URL, lecture d'une réponse JSON, via un `fetch` injecté) de ce
 * qui ne peut s'éprouver que dans un vrai navigateur (chargement des scripts
 * Google, OAuth, Picker). Il ne connaît **aucune clé `localStorage`** : le
 * dossier retenu vit dans le stockage de chaque outil, pas ici (§3.3/§4.3).
 */

// ============================================================
// ERREUR — un seul type, un message déjà affichable
// ============================================================

export class ErreurDrive extends Error {
  constructor(message, { code = null, cause = undefined } = {}) {
    super(message);
    this.name = 'ErreurDrive';
    this.code = code;
    this.cause = cause;
  }
}

// ============================================================
// PUR — construire une requête, interpréter une réponse
// ============================================================

/**
 * URL de listage des `_REPET.json` d'un dossier Drive.
 *
 * Filtré côté serveur (`name contains '_REPET.json'`) plutôt que de tout lister
 * et filtrer ici : un dossier Drive peut contenir d'autres documents (notes,
 * PDF sources), et les lister tous ne servirait à rien.
 *
 * @param {string} dossierId
 */
export function urlListeFichiers(dossierId) {
  const requete =
    `'${dossierId}' in parents and trashed = false and ` +
    "name contains '_REPET.json'";

  const params = new URLSearchParams({
    q: requete,
    fields: 'files(id,name)',
    pageSize: '100',
  });

  return `https://www.googleapis.com/drive/v3/files?${params.toString()}`;
}

/** URL de lecture du contenu brut d'un fichier Drive. */
export function urlContenuFichier(fichierId) {
  return `https://www.googleapis.com/drive/v3/files/${encodeURIComponent(fichierId)}?alt=media`;
}

/**
 * Fichiers valides d'une réponse `files.list`, jamais `undefined`.
 *
 * Une réponse malformée (champ absent, fichier sans `id` ni `name`) rend une
 * liste vide plutôt que de lever : c'est à l'appelant de décider si « rien à
 * afficher » est une erreur ou un dossier simplement vide — cette fonction ne
 * fait qu'interpréter la forme, pas juger du cas.
 *
 * @param {unknown} json
 * @returns {{id: string, name: string}[]}
 */
export function fichiersDepuisReponse(json) {
  if (json === null || typeof json !== 'object' || !Array.isArray(json.files)) {
    return [];
  }

  return json.files.filter(
    (f) => f && typeof f === 'object' && typeof f.id === 'string' && typeof f.name === 'string',
  );
}

// ============================================================
// IMPUR, INJECTABLE — réseau (fetch injecté, testable sans navigateur)
// ============================================================

/**
 * Liste les `_REPET.json` d'un dossier Drive.
 *
 * @param {string} accessToken
 * @param {string} dossierId
 * @param {typeof fetch} fetchImpl injectable par les tests ; `fetch` global sinon
 * @returns {Promise<{id: string, name: string}[]>}
 */
export async function listerFichiers(accessToken, dossierId, fetchImpl = fetch) {
  let reponse;

  try {
    reponse = await fetchImpl(urlListeFichiers(dossierId), {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
  } catch (erreur) {
    throw new ErreurDrive('Réseau indisponible pour interroger Google Drive.', { cause: erreur });
  }

  if (!reponse.ok) {
    throw new ErreurDrive(
      `Google Drive a refusé la liste des fichiers (HTTP ${reponse.status}).`,
      { code: reponse.status },
    );
  }

  return fichiersDepuisReponse(await reponse.json());
}

/**
 * Lit le contenu brut d'un fichier Drive.
 *
 * Rend le **texte**, pas un objet déjà parsé : à l'appelant de faire
 * `JSON.parse` puis de valider avec son propre `schema.js`/`validerRepet`,
 * exactement comme un fichier importé à la main (§3.3/§4.3) — ce module ne
 * connaît pas le schéma `REPET.json`, et ne doit pas avoir à le connaître.
 *
 * @param {string} accessToken
 * @param {string} fichierId
 * @param {typeof fetch} fetchImpl
 * @returns {Promise<string>}
 */
export async function lireFichier(accessToken, fichierId, fetchImpl = fetch) {
  let reponse;

  try {
    reponse = await fetchImpl(urlContenuFichier(fichierId), {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
  } catch (erreur) {
    throw new ErreurDrive('Réseau indisponible pour lire ce fichier Drive.', { cause: erreur });
  }

  if (!reponse.ok) {
    throw new ErreurDrive(
      `Google Drive a refusé la lecture du fichier (HTTP ${reponse.status}).`,
      { code: reponse.status },
    );
  }

  return reponse.text();
}

// ============================================================
// IMPUR, NON TESTABLE SANS NAVIGATEUR — scripts Google, OAuth, Picker
//
// Même statut que `voix.js` dans outil_repetition : ces fonctions pilotent de
// vraies API navigateur (injection de <script>, popups Google) qu'aucune
// doublure ne remplace fidèlement. Non couvertes par node --test, à dessein.
// ============================================================

let _promesseIdentite = null;
let _promessePicker = null;

function _chargerScript(src) {
  return new Promise((resoudre, rejeter) => {
    const script = document.createElement('script');

    script.src = src;
    script.async = true;
    script.onload = () => resoudre();
    script.onerror = () =>
      rejeter(new ErreurDrive(`Impossible de charger le script Google (${src}).`));

    document.head.appendChild(script);
  });
}

/** Charge Google Identity Services, une seule fois par page (mémoïsé). */
export function chargerIdentiteGoogle() {
  if (!_promesseIdentite) {
    _promesseIdentite = _chargerScript('https://accounts.google.com/gsi/client');
  }

  return _promesseIdentite;
}

/** Charge l'API Picker, une seule fois par page (mémoïsé). */
export function chargerPicker() {
  if (!_promessePicker) {
    _promessePicker = _chargerScript('https://apis.google.com/js/api.js').then(
      () => new Promise((resoudre) => window.gapi.load('picker', resoudre)),
    );
  }

  return _promessePicker;
}

/**
 * Authentifie et rend un jeton d'accès de courte durée (~1h, limite Google,
 * non ajustable — voir §3.3/§4.3).
 *
 * Une popup Google s'ouvre à chaque appel qui n'a pas de session déjà
 * consentie dans ce navigateur : silencieux sur ordinateur la plupart du
 * temps, explicite sur Safari/iPhone à cause de l'ITP (§3.3).
 *
 * @param {{clientId: string, scope: string}} options
 * @returns {Promise<string>} le jeton d'accès
 */
export async function authentifier({ clientId, scope }) {
  await chargerIdentiteGoogle();

  return new Promise((resoudre, rejeter) => {
    const client = google.accounts.oauth2.initTokenClient({
      client_id: clientId,
      scope,
      callback: (reponse) => {
        if (reponse.error) {
          rejeter(
            new ErreurDrive(`Connexion à Google Drive refusée (${reponse.error}).`),
          );
          return;
        }

        resoudre(reponse.access_token);
      },
    });

    client.requestAccessToken();
  });
}

/**
 * Ouvre le sélecteur Google, restreint au choix d'un dossier.
 *
 * Scope `drive.file` : l'app ne reçoit l'accès qu'au dossier choisi ici, jamais
 * à l'ensemble du Drive de la personne (§3.3/§4.3, décision retenue plutôt que
 * `drive.readonly`).
 *
 * @param {{apiKey: string, accessToken: string}} options
 * @returns {Promise<{id: string, nom: string}|null>} `null` si annulé
 */
export async function choisirDossier({ apiKey, accessToken }) {
  await chargerPicker();

  return new Promise((resoudre, rejeter) => {
    try {
      const vue = new google.picker.DocsView(google.picker.ViewId.FOLDERS)
        .setSelectFolderEnabled(true)
        .setIncludeFolders(true)
        .setMode(google.picker.DocsViewMode.LIST);

      const picker = new google.picker.PickerBuilder()
        .setDeveloperKey(apiKey)
        .setOAuthToken(accessToken)
        .addView(vue)
        .setCallback((donnees) => {
          if (donnees.action === google.picker.Action.PICKED) {
            const dossier = donnees.docs[0];
            resoudre({ id: dossier.id, nom: dossier.name });
          } else if (donnees.action === google.picker.Action.CANCEL) {
            resoudre(null);
          }
        })
        .build();

      picker.setVisible(true);
    } catch (erreur) {
      rejeter(
        new ErreurDrive('Le sélecteur Google Drive n’a pas pu s’ouvrir.', { cause: erreur }),
      );
    }
  });
}
