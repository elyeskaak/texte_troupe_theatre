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
  /** Unités jouables gardées montées dans le DOM (§6.4 de ARCHITECTURE.md). */
  UNITES_MONTEES_MAX: 5,

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

  // --- Confort -----------------------------------------------------
  VITESSE_DEFILEMENT: Object.freeze([1, 2, 3, 4]),

  // --- Données -----------------------------------------------------
  /** Version de schéma acceptée. Toute autre est refusée, jamais devinée. */
  SCHEMA_ACCEPTE: 'repetition/1',
  /** Préfixe de toutes les clés localStorage. */
  PREFIXE_STOCKAGE: 'repet:v1',
});
