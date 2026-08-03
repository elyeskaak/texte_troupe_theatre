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
   * Décompte avant l'écoute effective.
   *
   * Siri activé, Safari met deux à trois secondes à ouvrir réellement le
   * micro : sans ce délai, le début de la réplique est systématiquement perdu.
   */
  DELAI_AVANT_ECOUTE_MS: 2000,
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

  // --- Données -----------------------------------------------------
  /** Version de schéma acceptée. Toute autre est refusée, jamais devinée. */
  SCHEMA_ACCEPTE: 'repetition/1',
  /** Préfixe de toutes les clés localStorage. */
  PREFIXE_STOCKAGE: 'repet:v1',
});
