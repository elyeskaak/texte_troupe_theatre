# Doctrine — équilibrage et coupes de pièces de théâtre

Contexte : troupe de 10 comédiens (5H/5F), spectacle de 1h30-2h. Critère prioritaire absolu : aucun comédien ne doit se retrouver avec un rôle disproportionné.

## Procédure en 2 étapes obligatoires (avant toute coupe)

Ne jamais estimer les poids de personnages "à la lecture" pour un texte de plus de quelques pages — toujours passer par `analyze.py`. La lecture reste appropriée pour le jugement dramaturgique (où couper, quelle scène est faible), pas pour le comptage.

### Étape 1 — Détection

```bash
python3 analyze.py detect <chemin\_du\_fichier>
```

Produit : nombre d'actes/scènes détectés, liste des personnages avec répliques brutes, alerte format classique/moderne, lignes suspectes (didascalies mal classées).

**Toujours vérifier avant de continuer :**

* variantes du même personnage comptées séparément (ex: "ALCESTE" / "ALC.") → à fusionner
* noms qui ne sont pas des personnages
* nombre de scènes cohérent avec le découpage connu

Si fusion nécessaire, créer un `aliases.json` :

```json
{ "ALC.": "ALCESTE", "LE PRINCE": "PRINCE" }
```

### Étape 2 — Calcul

```bash
python3 analyze.py compute <chemin\_du\_fichier> \[--aliases aliases.json] \[--cast cast.json] \[--target 15000]
```

Produit : tableau mots/%/répliques/présence scénique par personnage, avec flags "rôle creux" (< 25% du poids moyen ET < 3% du total) / "rôle hypertrophié" (> 2.5x le poids moyen ET > 15% du total), et un CSV de matrice de présence scène × personnage.

**`--cast cast.json`** (distribution déjà connue, doublages inclus) :

```json
{ "Comédien A": \["ALCESTE"], "Comédien B": \["PHILINTE", "LE PRINCE"] }
```

Agrège par comédien (pas par personnage), compare à la cible réelle (100% / nb comédiens, ex. 10% pour 10). C'est ce tableau qui sert de référence pour les coupes une fois la distribution fixée.

**`--target <mots>`** : affiche l'écart à combler et classe les scènes par poids décroissant, pour repérer les candidates à une coupe large.

Toujours recalculer (étape 1 + 2) après chaque passe de coupe — ne jamais réutiliser un ancien comptage après modification du texte.

## Doctrine de coupe (distribution fixée)

Couper en priorité chez les rôles les plus au-dessus de la cible d'équilibre (\~10% pour 10 comédiens), pour les ramener progressivement vers cette cible. Les rôles déjà proches ou en dessous de la cible ne sont pas des candidats à la coupe.

**2-3 passes, pas un rabotage ligne à ligne répété à l'infini :**

1. Passe structurelle : scènes/sous-intrigues entières chez les rôles surchargés, viser \~70-80% du volume à couper dès cette passe
2. Passe d'ajustement fin : ligne à ligne pour la cible exacte
3. Passe de rééquilibrage si une passe précédente a trop vidé un rôle

**Avant de sacrifier une scène entière, vérifier sa fonction dramaturgique, pas seulement son poids en mots :**

* une scène d'exposition qui paraît "sans intérêt" peut être nécessaire à la mise en place
* une scène hors-intrigue peut porter la farce ou l'humour de la pièce

Toujours signaler explicitement la fonction identifiée (exposition / farce / intrigue) pour chaque scène proposée à la coupe large.

## Format de restitution des coupes

* .docx avec suivi des modifications Word (`<w:del>`/`<w:ins>`), texte intégral conservé et visible en barré.



## Limites connues

* PDF sans mise en forme préservée : détection moins fiable qu'en .docx ; privilégier le .docx si disponible.
* Format moderne sans didascalies explicites : présence scénique déduite des seules répliques prononcées (personnage silencieux mais présent = non détecté). À signaler.
* Titres de personnage complexes (ex: "LE ROI, à part") : peuvent perturber la détection de nom.

## Restitution

Tableau synthétique (personnage / mots / % / verdict), pas de longue prose. Citer les scènes précises (Acte/Sc.) où un personnage est absent sur une plage anormalement longue, en s'appuyant sur le CSV de présence.

