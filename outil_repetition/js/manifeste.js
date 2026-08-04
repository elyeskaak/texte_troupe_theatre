/**
 * Découverte des pièces du dossier partagé `../pieces/`.
 *
 * `pieces/` est partagé entre `outil_repetition` et `outil_lecture` : les
 * deux consomment le même `<Livre>_REPET.json`, régénéré par
 * `docx_vers_repet.py`, qui y écrit aussi `manifest.json` — la liste de tout
 * ce qui s'y trouve. Sans ce module, chaque pièce devrait être importée à la
 * main une par une (coller le JSON, ou choisir le fichier), à chaque nouvel
 * appareil et à chaque mise à jour du texte.
 *
 * Module **pur** pour la partie qui se teste sans réseau ni DOM : décider
 * quelles entrées du manifeste ne sont pas déjà importées. Le `fetch()`
 * lui-même reste impur et vit dans `app.js` — même séparation qu'ailleurs
 * dans ce projet (`modele.js` calcule, `rendu.js` touche le DOM).
 */

/**
 * Entrées du manifeste dont l'identifiant ne correspond à aucune pièce déjà
 * enregistrée sur cet appareil.
 *
 * Comparé par identifiant, pas par nom de fichier : c'est l'identifiant
 * (dérivé du titre par `idDePiece`) qui décide si une pièce du manifeste est
 * « la même » qu'une pièce déjà importée, exactement comme au moment de
 * l'enregistrer (`stockage.enregistrerPiece`).
 *
 * @param {{pieces?: Array<{fichier: string, piece: string}>}|null} manifeste
 * @param {Array<{id: string}>} enregistrees - `stockage.listerPieces()`
 * @param {(titre: string) => string} idDePiece
 * @returns {Array<{fichier: string, piece: string}>}
 */
export function piecesNonImportees(manifeste, enregistrees, idDePiece) {
  const idsConnus = new Set(enregistrees.map((entree) => entree.id));

  return (manifeste?.pieces ?? []).filter(
    (entree) => !idsConnus.has(idDePiece(entree.piece)),
  );
}
