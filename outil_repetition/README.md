# outil_repetition

Page web pour apprendre et répéter son texte de théâtre, **utilisable sur
iPhone**. Lit le `<Livre>_REPET.json` produit par
[`outil_edition`](../outil_edition/README.md).

> **En cours de construction.** La coque fonctionne : on charge une pièce, on
> choisit ses rôles, et la pièce est conservée sur l'appareil. L'écran de
> répétition proprement dit — les sept modes de masquage, le top, le défilement —
> arrive à l'étape 7. Le périmètre est fixé par le
> [cahier des charges](CAHIER_DES_CHARGES.md), la conception par
> [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## Pourquoi une page servie en HTTPS, et non un fichier

Safari place le micro derrière un *secure context* : depuis un fichier ouvert
dans l'app Fichiers (`file://`), la reconnaissance vocale **n'obtiendra jamais le
micro sur iPhone**. La page est donc publiée sur GitHub Pages, puis ajoutée à
l'écran d'accueil.

Le code est public, **les textes ne le sont pas** : les pièces sont chargées sur
l'appareil et vivent dans son navigateur. C'est ce qui rend le déploiement
compatible avec les droits d'auteur.

## Retrouver ses pièces sans dossier local : Google Drive

Sur l'écran d'accueil, **« Se connecter à Google Drive »** ouvre un sélecteur
Google pour choisir un dossier (une seule fois — il est ensuite retenu sur cet
appareil), puis liste ses `_REPET.json` avec un bouton « Charger » chacun,
exactement comme un fichier importé à la main. Voir
[`ARCHITECTURE.md`](ARCHITECTURE.md) §3.3 pour le mécanisme complet et ses
limites (Safari/iPhone notamment).

C'est une commodité de plus, jamais requise : le dossier partagé local (ci-dessus)
et l'import manuel continuent de fonctionner sans elle.

## Attention : Safari purge le stockage

Depuis iOS 13.4, Safari efface `localStorage` après **7 jours sans interaction**
avec le site, et l'exemption dont bénéficiaient les applications ajoutées à
l'écran d'accueil a été retirée. Trois semaines sans répéter suffiraient à perdre
toute la progression.

D'où le bouton **« Exporter ma progression »**, et une alerte au-delà de 5 jours
sans export. La progression est une donnée d'agrément : sa perte ne doit jamais
empêcher de répéter.

## Développement

### Lancer les tests

Aucune dépendance à installer.

```bash
cd outil_repetition
node --test tests/*.test.js
```

`package.json` ne déclare aucune dépendance : il existe pour que Node accepte les
`export` des `.js` (`"type": "module"`). **`npm install` n'a jamais à être
lancé.**

### Servir la page en local

Les modules ES ne se chargent pas depuis `file://`. Pour ouvrir la page sur son
poste, servir depuis la **racine du dépôt** — et non depuis `outil_repetition/` :
la découverte automatique des pièces (`js/manifeste.js`) va lire
`../pieces/manifest.json`, un dossier **frère** de `outil_repetition/`, pas un
de ses sous-dossiers.

```bash
python -m http.server 8000
# puis http://localhost:8000/outil_repetition/
```

`localhost` est un *secure context* : le micro y fonctionne aussi.

### Régénérer `tests/exemple-repet.json`

Ce fichier est un vrai `REPET.json`, produit par `repet_export.py`, et
`contrat.test.js` le valide avec `schema.js` — c'est le seul test qui éprouve les
deux outils ensemble. À régénérer **seulement après un changement volontaire du
schéma**, et en incrémentant alors `config.SCHEMA_REPET` côté Python et
`CONFIG.SCHEMA_ACCEPTE` côté JavaScript.

La pièce d'essai est écrite pour ce test, donc libre de droits.

## Ce qui ne doit jamais entrer dans le dépôt

`../pieces/` (à la racine du dépôt, partagé avec `outil_lecture`) et tout
`*_REPET.json` sont exclus par `.gitignore` : un `REPET.json` contient le texte
intégral d'une œuvre. Même motif que `exemples/`. Voir
`pieces/LISEZ-MOI.md` et `outil_edition/outils/docx_vers_repet.py` pour
régénérer une pièce.

C'est une leçon coûteuse : la première version de cet outil embarquait 188 Ko du
texte d'une pièce sous droits, en base64, dans un dépôt public. Le retirer a
demandé une réécriture de l'historique git.
