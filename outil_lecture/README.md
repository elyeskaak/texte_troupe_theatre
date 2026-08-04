# outil_lecture — lecture interactive projetée

Outil pour une lecture collective de texte de théâtre, projetée au
vidéoprojecteur : le texte s'affiche en grand, chaque réplique est mise en
évidence par la couleur du lecteur qui la prononce (10 lecteurs possibles :
H1-H5, F1-F5), un même lecteur pouvant jouer plusieurs personnages.

Voir [ARCHITECTURE.md](ARCHITECTURE.md) pour les choix de conception, en
particulier §2 (pourquoi cet outil lit un `REPET.json` plutôt que le format
`.txt` décrit dans le prompt d'origine) et §13 (décisions validées).

## Usage

1. Ouvrir `index.html` par double-clic (aucune installation, aucun serveur),
   ou depuis sa version publiée en HTTPS — nécessaire pour Google Drive
   ci-dessous (§4.3 de `ARCHITECTURE.md`).
2. Charger un `<Pièce>_REPET.json` : soit un fichier choisi à la main (produit
   par `outil_edition`, même fichier que celui utilisé par `outil_repetition`),
   soit **« Se connecter à Google Drive »** — visible seulement en HTTPS —
   pour choisir un dossier une fois et retrouver ses pièces à chaque ouverture
   sans réimporter de fichier.
3. Attribuer chaque personnage détecté à un slot (H1-H5, F1-F5) — plusieurs
   personnages peuvent partager le même slot.
4. Optionnel : ouvrir la fenêtre de contrôle et la déplacer sur le deuxième
   écran (celui qui n'est pas projeté), pour y saisir le prénom de chaque
   lecteur en direct.
5. Démarrer la lecture, puis naviguer au clavier :
   - `→` réplique/élément suivant
   - `←` réplique/élément précédent
   - `F` passer en plein écran

La position de lecture et l'attribution des personnages sont conservées dans
`localStorage` : rouvrir l'outil sur la même pièce propose de reprendre où
la lecture s'était arrêtée.

## Limites connues

- Nécessite `localStorage` et, pour la synchronisation avec la fenêtre de
  contrôle, `BroadcastChannel` (absent → message explicite, la projection
  continue de fonctionner seule).
- La fenêtre de contrôle s'ouvre via `window.open` : un bloqueur de popup
  affiche un message et un bouton « réessayer », sur l'écran de préparation
  et, discrètement, sur la fenêtre de projection.
- Les prénoms des lecteurs sont globaux (indépendants de la pièce chargée) :
  ce sont les personnes présentes ce jour-là, pas une distribution figée.
