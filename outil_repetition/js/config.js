/**
 * Toutes les constantes de l'outil de répétition.
 *
 * Aucune logique ici, et aucun nombre magique ailleurs dans le code — même
 * règle que `config.py` dans `outil_edition`. Régler la difficulté par défaut
 * ou le délai avant écoute doit rester la modification d'une seule ligne.
 */

export const CONFIG = Object.freeze({
  // --- Modes de masquage -------------------------------------------
  /** Mots visibles en mode « amorce seule ». */
  MOTS_AMORCE: 3,
  /** Derniers mots du top affichés en mode réduit. */
  MOTS_TOP: 5,
  /** Pourcentage de mots masqués en mode « mots à trous ». */
  DIFFICULTE_DEFAUT: 45,

  // --- Rendu -------------------------------------------------------
  /**
   * Unités jouables gardées montées dans le DOM (§6.4 de ARCHITECTURE.md).
   *
   * Doit rester **nettement supérieur** au nombre d'unités tenant dans la portée
   * de montage (`MARGE_MONTAGE`). Sinon chaque passe évince ce que la précédente
   * vient de monter : constaté avec un plafond de 5 pour une portée de dix
   * unités, où l'ensemble monté alternait entre deux groupes à chaque événement
   * de défilement — soit exactement le coût que le montage paresseux évite.
   */
  UNITES_MONTEES_MAX: 8,

  /**
   * Portée de montage, en hauteurs d'écran de part et d'autre.
   *
   * Un demi-écran d'avance suffit à la vitesse d'un défilement de lecture, et
   * garde la portée à trois ou quatre unités — largement sous le plafond.
   */
  MARGE_MONTAGE: 0.5,

  // --- Persistance -------------------------------------------------
  /** Scores vocaux conservés par réplique, les plus anciens chassés d'abord. */
  SCORES_PAR_REPLIQUE: 10,
  /** Délai avant écriture différée dans localStorage. */
  DELAI_ECRITURE_MS: 800,
  /**
   * Seuil d'alerte sur l'ancienneté du dernier export.
   *
   * Cinq jours et non sept : Safari purge le stockage après sept jours
   * d'inactivité, et alerter le jour de l'échéance serait alerter trop tard.
   */
  JOURS_SANS_EXPORT_ALERTE: 5,

  // --- Reconnaissance vocale ---------------------------------------
  /**
   * Délai au-delà duquel on annonce l'écoute sans en avoir la confirmation.
   *
   * **Ce n'est plus un décompte imposé.** La première version attendait deux
   * secondes avant même de démarrer, parce que Safari met ce temps à ouvrir le
   * micro et que le début de la réplique se perdait. À l'usage, l'attente était
   * insupportable — et elle était inutile : l'API émet `audiostart` quand la
   * capture commence réellement. On démarre donc aussitôt, et l'interface annonce
   * « je vous écoute » sur cet événement.
   *
   * Ce délai ne sert plus que de repli, pour les moteurs qui n'émettent pas
   * `audiostart` : passé ce temps, on suppose le micro ouvert plutôt que de
   * laisser « préparation… » indéfiniment.
   */
  DELAI_ATTENTE_MICRO_MS: 1200,
  /** Délai de garde : l'écoute iOS peut ne jamais s'arrêter d'elle-même. */
  ECOUTE_MAX_MS: 30000,
  LANGUE_RECONNAISSANCE: 'fr-FR',

  // --- Comparaison -------------------------------------------------
  /**
   * Garde-fou sur l'alignement, dont le coût est quadratique.
   *
   * Une réplique de théâtre fait quelques dizaines de mots ; 400 laisse une
   * marge confortable tout en écartant le cas pathologique d'une transcription
   * qui partirait en boucle.
   */
  MOTS_MAX_ALIGNEMENT: 400,

  // --- Répétition espacée ------------------------------------------
  /** Score à partir duquel une récitation compte comme réussie. */
  SEUIL_REUSSITE: 90,

  /** Réussites nécessaires avant qu'une réplique soit tenue pour sue. */
  REUSSITES_POUR_MAITRISE: 3,

  /**
   * Jours de validité d'une maîtrise, selon le nombre de réussites accumulées.
   *
   * C'est le ressort de la répétition espacée : chaque réussite supplémentaire
   * repousse la révision. Une réplique sue trois fois se revoit à sept jours ;
   * sue six fois, à cinq semaines. Au-delà de la dernière valeur, l'intervalle
   * ne croît plus — une pièce se joue dans l'année, pas dans dix ans.
   */
  INTERVALLES_REVISION_JOURS: Object.freeze([7, 16, 35]),

  /**
   * Répliques affichées dans la file de révision.
   *
   * Volontairement court. La file complète ferait plusieurs centaines de lignes
   * sur *La toile d'araignée*, et une liste qu'on ne peut pas finir ne donne pas
   * envie de la commencer. Douze, c'est une séance.
   */
  REPLIQUES_A_REVISER: 12,

  // --- Données -----------------------------------------------------
  /** Version de schéma acceptée. Toute autre est refusée, jamais devinée. */
  SCHEMA_ACCEPTE: 'repetition/2',
  /** Préfixe de toutes les clés localStorage. */
  PREFIXE_STOCKAGE: 'repet:v1',
  /**
   * Marque une réplique dite par toute la distribution (« TOUS. »), plutôt
   * que par un ou plusieurs personnages nommés. Vaut pour n'importe quel rôle
   * choisi — voir `modele.estMienne`.
   */
  JOKER_TOUS: '*',

  // --- Google Drive (../pieces/drive.js, §3.3 de ARCHITECTURE.md) --
  /**
   * Ni l'un ni l'autre n'est un secret (§3.3) : la sécurité vient des
   * origines JavaScript autorisées côté Google Cloud et du consentement
   * utilisateur, pas de leur confidentialité — ils peuvent rester en clair
   * ici, dans le code public.
   */
  DRIVE_CLIENT_ID:
    '865511393898-i692e2218d8u8hb4rd5afhjjhfb9opec.apps.googleusercontent.com',
  DRIVE_API_KEY: 'AIzaSyBKHu8igUEGgbNAACvjYZbCPppHi8nc8VU',
  /**
   * Accès restreint à ce que l'utilisateur choisit explicitement dans le
   * sélecteur Google (Picker), jamais un accès large à tout son Drive
   * (`drive.readonly`) — décision retenue en §3.3.
   */
  DRIVE_SCOPE: 'https://www.googleapis.com/auth/drive.file',
});
