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
  horsLigne:
    'La reconnaissance vocale a besoin du réseau : la transcription se fait à ' +
    'distance. Vous pouvez toujours vous enregistrer et vous réécouter.',
  silence: 'Rien n’a été entendu. Reprenez dès que « je vous écoute » s’affiche.',
});

// ============================================================
// RECONNAISSANCE VOCALE
// ============================================================

/**
 * L'appareil sait-il transcrire ?
 *
 * `webkitSpeechRecognition` d'abord : c'est le nom exposé par Safari, y compris
 * sur iOS depuis 14.5, où le nom standard n'existe pas.
 */
function _classeReconnaissance() {
  return globalThis.SpeechRecognition ?? globalThis.webkitSpeechRecognition ?? null;
}

export function reconnaissanceDisponible() {
  return _classeReconnaissance() !== null;
}

/**
 * Crée un contrôleur de reconnaissance vocale.
 *
 * Cinq règles, toutes tirées des limites réelles d'iOS (§8.1 de ARCHITECTURE) :
 *
 * 1. **une réplique à la fois**, jamais d'écoute globale ;
 * 2. **aucune attente imposée.** L'écoute démarre au doigt. L'API annonce
 *    elle-même l'ouverture du micro par `audiostart` : l'interface dit
 *    « préparation… » puis « je vous écoute », ce qui informe sans faire
 *    patienter. Une version antérieure imposait deux secondes de décompte —
 *    long à l'usage, et inutile puisque l'événement existe ;
 * 3. **écoute non continue**, avec un délai de garde. Des rapports récurrents
 *    décrivent une écoute qui ne s'arrête jamais : le garde-fou est une
 *    protection, pas un confort ;
 * 4. **seuls les résultats finaux comptent.** Les intermédiaires sont affichés
 *    s'ils arrivent, jamais utilisés pour un score ;
 * 5. **un échec est un non-événement.** Aucun score enregistré, aucune modale.
 *
 * @param {object} rappels
 * @param {(secondes: number) => void} [rappels.surDecompte]
 * @param {(texte: string) => void} [rappels.surIntermediaire]
 * @param {(texte: string) => void} [rappels.surTranscription]
 * @param {(motif: string) => void} [rappels.surEchec]
 * @param {() => void} [rappels.surFin]
 * @param {object} [options]
 */
export function creerReconnaissance(rappels = {}, options = {}) {
  const {
    surDecompte = () => {},
    surIntermediaire = () => {},
    surTranscription = () => {},
    surEchec = () => {},
    surFin = () => {},
  } = rappels;

  const langue = options.langue ?? 'fr-FR';
  const delaiAttenteMicro = options.delaiAttenteMicroMs ?? 1200;
  const delaiMax = options.ecouteMaxMs ?? 30000;

  let reconnaissance = null;
  let minuterieMicro = null;
  let minuterieGarde = null;
  let aRenduUnResultat = false;

  function nettoyer() {
    clearTimeout(minuterieMicro);
    clearTimeout(minuterieGarde);
    minuterieMicro = null;
    minuterieGarde = null;
  }

  return {
    disponible: reconnaissanceDisponible,

    actif: () => reconnaissance !== null,

    /** Ouvre le micro et écoute, sans délai imposé. */
    demarrer() {
      const Classe = _classeReconnaissance();

      if (Classe === null) {
        surEchec('indisponible');
        return;
      }

      if (reconnaissance !== null) {
        return;
      }

      // `navigator.onLine` à `false` est fiable ; à `true` il ne prouve rien. Il
      // sert donc à éviter une tentative vouée à l'échec, pas à garantir un
      // succès : la reconnaissance iOS est distante.
      if (globalThis.navigator?.onLine === false) {
        surEchec('horsLigne');
        return;
      }

      // Démarrage immédiat. « Préparation » ne fait pas attendre : cet état
      // explique seulement que le micro n'est pas encore ouvert, et il cède la
      // place dès qu'`audiostart` arrive.
      surDecompte(-1);
      this._ecouter(Classe);
    },

    /** @private */
    _ecouter(Classe) {
      aRenduUnResultat = false;
      reconnaissance = new Classe();
      reconnaissance.lang = langue;
      reconnaissance.continuous = false;
      reconnaissance.interimResults = true;
      reconnaissance.maxAlternatives = 1;

      // Le micro est réellement ouvert : c'est le moment de parler.
      reconnaissance.addEventListener('audiostart', () => {
        clearTimeout(minuterieMicro);
        minuterieMicro = null;
        surDecompte(0);
      });

      reconnaissance.addEventListener('result', (evenement) => {
        let intermediaire = '';
        let definitif = '';

        for (const resultat of evenement.results) {
          if (resultat.isFinal) {
            definitif += resultat[0].transcript;
          } else {
            intermediaire += resultat[0].transcript;
          }
        }

        if (intermediaire) {
          surIntermediaire(intermediaire);
        }

        if (definitif.trim()) {
          aRenduUnResultat = true;
          surTranscription(definitif.trim());
        }
      });

      reconnaissance.addEventListener('error', (evenement) => {
        // `no-speech` et `aborted` ne sont pas des pannes : on s'est arrêté, ou
        // on n'a rien dit. Les présenter comme des erreurs serait bruyant.
        const motif =
          evenement.error === 'not-allowed' || evenement.error === 'service-not-allowed'
            ? 'refuse'
            : evenement.error === 'no-speech'
              ? 'silence'
              : evenement.error === 'aborted'
                ? null
                : 'echec';

        if (motif !== null) {
          surEchec(motif);
        }
      });

      reconnaissance.addEventListener('end', () => {
        nettoyer();
        reconnaissance = null;

        if (!aRenduUnResultat) {
          surEchec('silence');
        }

        surFin();
      });

      try {
        reconnaissance.start();
      } catch (erreur) {
        reconnaissance = null;
        surEchec('echec');
        return;
      }

      // Repli : certains moteurs n'émettent pas `audiostart`. Passé ce délai on
      // suppose le micro ouvert, plutôt que de laisser « préparation… » sans fin.
      minuterieMicro = setTimeout(() => surDecompte(0), delaiAttenteMicro);

      // Délai de garde : l'écoute iOS peut ne jamais s'arrêter d'elle-même.
      minuterieGarde = setTimeout(() => this.arreter(), delaiMax);
    },

    /** Arrête l'écoute et ses minuteries. */
    arreter() {
      nettoyer();

      if (reconnaissance === null) {
        surFin();
        return;
      }

      try {
        reconnaissance.stop();
      } catch {
        reconnaissance = null;
        surFin();
      }
    },
  };
}
