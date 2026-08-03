/**
 * Enregistrement audio d'une récitation.
 *
 * Module **impur**, isolé : le seul à toucher au micro. Son échec ne doit jamais
 * empêcher de répéter (P2).
 *
 * **Ce module a été retiré du périmètre, puis remis.** L'argument du retrait
 * était que l'app Dictaphone de l'iPhone fait déjà cela. L'usage a montré que non :
 * en récitation à l'aveugle, sortir de l'outil, viser un autre bouton, revenir,
 * puis recommencer à la réplique suivante casse l'exercice. Ce qui compte n'est
 * pas d'enregistrer, c'est d'enregistrer **sans quitter la réplique**.
 *
 * Deux décisions de conception en découlent.
 *
 * **Rien n'est conservé.** L'enregistrement vit en mémoire, le temps de se
 * réécouter, et disparaît au changement de réplique. Une minute d'audio pèse plus
 * lourd que la pièce entière : le stocker saturerait le quota que §7.3 protège, et
 * pour un usage qui se joue dans les secondes qui suivent.
 *
 * **Le type MIME est négocié, jamais supposé.** Safari ne produit pas de WebM.
 * Coder `audio/webm` en dur — l'erreur la plus commune avec `MediaRecorder` —
 * ferait échouer l'enregistrement sur le seul appareil qui compte ici.
 */

/**
 * Types tentés, dans l'ordre de préférence.
 *
 * La liste vide en dernier n'est pas une négligence : passer `undefined` à
 * `MediaRecorder` lui laisse choisir son format par défaut, ce qui est le repli
 * correct sur un navigateur dont aucun type déclaré ne conviendrait.
 */
const TYPES = ['audio/mp4', 'audio/webm;codecs=opus', 'audio/webm', 'audio/ogg', ''];

/** L'appareil peut-il enregistrer ? */
export function disponible() {
  return (
    typeof MediaRecorder !== 'undefined' &&
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia
  );
}

function _typeRetenu() {
  for (const type of TYPES) {
    if (type === '' || MediaRecorder.isTypeSupported(type)) {
      return type;
    }
  }

  return '';
}

/**
 * Crée un enregistreur réutilisable.
 *
 * Le flux micro est demandé au **premier** enregistrement puis conservé : Safari
 * affiche sa demande d'autorisation à chaque `getUserMedia`, et la redemander à
 * chaque réplique rendrait l'exercice inutilisable.
 *
 * @param {(etat: string, details?: object) => void} surChangement
 */
export function creerEnregistreur(surChangement = () => {}) {
  let flux = null;
  let enregistreur = null;
  let morceaux = [];
  let urlCourante = null;

  function annoncer(etat, details) {
    surChangement(etat, details);
  }

  function libererUrl() {
    if (urlCourante !== null) {
      URL.revokeObjectURL(urlCourante);
      urlCourante = null;
    }
  }

  return {
    disponible,

    /** L'enregistrement est-il en cours ? */
    actif: () => enregistreur?.state === 'recording',

    /**
     * Démarre l'enregistrement.
     *
     * @returns {Promise<boolean>} `false` si le micro n'a pas été obtenu.
     */
    async demarrer() {
      if (!disponible()) {
        annoncer('indisponible');
        return false;
      }

      if (enregistreur?.state === 'recording') {
        return true;
      }

      try {
        flux ??= await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (erreur) {
        // Le nom de l'erreur distingue un refus d'un micro absent, et les deux
        // demandent une conduite différente de la part de l'utilisateur.
        annoncer(
          erreur.name === 'NotAllowedError' ? 'refuse' : 'echec',
          { erreur },
        );
        return false;
      }

      libererUrl();
      morceaux = [];

      const type = _typeRetenu();
      enregistreur = new MediaRecorder(flux, type ? { mimeType: type } : undefined);

      enregistreur.addEventListener('dataavailable', (evenement) => {
        if (evenement.data.size > 0) {
          morceaux.push(evenement.data);
        }
      });

      enregistreur.addEventListener('stop', () => {
        // `stop` peut précéder le dernier `dataavailable` sur certains moteurs :
        // l'URL est donc construite dans `arreter()`, après attente explicite.
      });

      enregistreur.addEventListener('error', (evenement) => {
        annoncer('echec', { erreur: evenement.error });
      });

      enregistreur.start();
      annoncer('enregistre');

      return true;
    },

    /**
     * Arrête l'enregistrement et rend une URL lisible.
     *
     * @returns {Promise<string|null>}
     */
    async arreter() {
      if (enregistreur?.state !== 'recording') {
        return null;
      }

      await new Promise((resoudre) => {
        enregistreur.addEventListener('stop', resoudre, { once: true });
        enregistreur.stop();
      });

      if (morceaux.length === 0) {
        annoncer('vide');
        return null;
      }

      const type = enregistreur.mimeType || morceaux[0].type || 'audio/mp4';
      urlCourante = URL.createObjectURL(new Blob(morceaux, { type }));

      annoncer('pret', { url: urlCourante });

      return urlCourante;
    },

    /**
     * Oublie l'enregistrement courant.
     *
     * Appelée au changement de réplique ou de mode. Sans elle, chaque
     * enregistrement fuirait un objet Blob pour toute la session.
     */
    oublier() {
      libererUrl();
      morceaux = [];
      annoncer('inactif');
    },

    /** Rend le micro à l'appareil. */
    fermer() {
      libererUrl();

      for (const piste of flux?.getTracks() ?? []) {
        piste.stop();
      }

      flux = null;
      enregistreur = null;
      morceaux = [];
    },
  };
}

/** Message affichable pour chaque état d'échec. */
export const MESSAGES = Object.freeze({
  indisponible:
    'Cet appareil ne permet pas l’enregistrement depuis le navigateur.',
  refuse:
    'Le micro a été refusé. Réglages → Safari → Microphone, puis rechargez la page.',
  echec: 'Le micro n’a pas pu démarrer.',
  vide: 'Aucun son n’a été capté — vérifiez que le micro n’est pas coupé.',
});
