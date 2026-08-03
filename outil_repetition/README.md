# outil_repetition

Page web pour apprendre et répéter son texte de théâtre, **utilisable sur
iPhone**. Lit le `<Livre>_REPET.json` produit par
[`outil_edition`](../outil_edition/README.md).

> **En cours de construction.** Les modules purs et leurs tests existent ; il n'y
> a pas encore d'interface. Le périmètre est fixé par le
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
poste :

```bash
cd outil_repetition
python -m http.server 8000
# puis http://localhost:8000/
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

`pieces/` et tout `*_REPET.json` sont exclus par `.gitignore` : un `REPET.json`
contient le texte intégral d'une œuvre. Même motif que `exemples/`.

C'est une leçon coûteuse : la première version de cet outil embarquait 188 Ko du
texte d'une pièce sous droits, en base64, dans un dépôt public. Le retirer a
demandé une réécriture de l'historique git.
