# Évaluation identité — split `test` — anthropic

Modèles : identity=claude-haiku-5-5, identity_strong=claude-sonnet-5-5 · exécutions : 3 · scènes : 39

> **Avertissement (D25)** : chiffres = accord avec l'annotateur unique, plafond humain non mesuré.
> Source: answers of subagent:claude-haiku+claude-sonnet to the emitted requests (not the API path: no thinking budget, no temperature, model tier of the responder). Subagent responders, to confirm with 3 API runs when a key exists.
> Second frozen test read (d482ca1, ruling R42), after the world loader fix, the card secret filter and the merge known-flag fix. This is the PR 2 gate.

## Gate (spec § 3.5)

| Condition | Seuil | Valeur (3 exéc. groupées) | IC 95 % (bootstrap par scène) | Verdict |
|---|---|---|---|---|
| Macro-moyenne A_cat (6 catégories dures) | ≥ 0,90 | 0,869 | [0,821 ; 0,913] | ÉCHEC |
| Accuracy groupée, mentions dures (pool) | ≥ 0,90 | 0,859 | [0,804 ; 0,908] | ÉCHEC |
| Catégorie dure PART seule | ≥ 0,85 | 0,933 | [0,884 ; 0,975] | OK |
| Catégorie dure DESC seule | ≥ 0,85 | 0,767 | [0,682 ; 0,853] | ÉCHEC |
| Catégorie dure GAP seule | ≥ 0,85 | 0,974 | [0,917 ; 1,000] | OK |
| Catégorie dure REVEAL seule | ≥ 0,85 | 0,951 | [0,853 ; 1,000] | OK |
| Catégorie dure NEW seule | ≥ 0,85 | 0,694 | [0,500 ; 0,883] | ÉCHEC |
| Catégorie dure XTYPE seule | ≥ 0,85 | 0,897 | [0,783 ; 0,968] | OK |
| Accuracy EASY + PC + SKIP | ≥ 0,97 | 0,960 | [0,933 ; 0,982] | ÉCHEC |
| W fusions abusives | ≤ 0,02 | 0,018 | [0,008 ; 0,030] | OK |
| D doublons | ≤ 0,08 | 0,018 | [0,007 ; 0,031] | OK |
| C@10 blocage | ≥ 0,98 | 0,980 | [0,970 ; 0,989] | OK |
| Fuites de secrets L | = 0 | 0 | — | OK |
| Révélations correctes R | ≥ 0,90 | — | — | non mesuré ici (§ 3.4 bis) |
| Erreurs de point de vue P | ≤ 0,05 | — | — | non mesuré ici (§ 3.4 bis) |
| B³ moyen sur les séquences | ≥ 0,85 | — | — | rapporté (gate à partir de la PR 5) |

**Gate des conditions mesurées ici : ÉCHEC ; gate incomplète (R, P non mesurés).**
C@10 : blocage sur dev + test, 1 exécution (spec § 3.5).
IC calculés sur les seuls tirages où la mesure est définie ; tirages indéfinis (catégorie absente du tirage) : hard_macro 1/2000, A_NEW 1/2000.
Catégories dures absentes : aucune.

## Gate du jalon PR 2

| Condition | Seuil | Valeur | IC 95 % | Verdict |
|---|---|---|---|---|
| Accuracy groupée, mentions dures (pool) | ≥ 0,85 | 0,859 | [0,804 ; 0,908] | OK |
| W fusions abusives | ≤ 0,02 | 0,018 | [0,008 ; 0,030] | OK |
| Fuites de secrets L | = 0 | 0 | — | OK |
| Taux d'escalade (tours) | cible ≤ 0,20 | 0,265 | — | rapporté |
| Coût par tour | cible ≤ 0,01 $ | 0,001749 $ (estimé : jetons ≈ caractères / 4, sans cache ni réflexion) | — | rapporté |

**Gate du jalon PR 2 : OK.**

## Planchers par catégorie dure : les deux lectures

- Lecture indicative : plancher 0,85, lu avec son IC large.
- Lecture contraignante : plancher 0,88 si chaque catégorie dure a ≥ 60 mentions en test ; elle ne s'applique pas à ce corpus.

| Catégorie | Mentions test | Moyenne | IC 95 % | Plancher 0,85 | Plancher 0,88 |
|---|---|---|---|---|---|
| PART | 129 | 0,933 | [0,884 ; 0,975] | OK | OK |
| DESC | 130 | 0,767 | [0,682 ; 0,853] | ÉCHEC | ÉCHEC |
| GAP | 39 | 0,974 | [0,917 ; 1,000] | OK | OK |
| REVEAL | 27 | 0,951 | [0,853 ; 1,000] | OK | OK |
| NEW | 36 | 0,694 | [0,500 ; 0,883] | ÉCHEC | ÉCHEC |
| XTYPE | 39 | 0,897 | [0,783 ; 0,968] | OK | OK |

## Décisions parasites et NEW

- Fusions parasites par tour (MATCH/ALIAS hors or) : 0,248
- NEW parasites par tour (hors or) : 0,085
- Erreurs de type NEW (par exécution) : 0,333
- Précision du NEW : 0,662
- Rappel du NEW : 0,677
- Taux d'UNSURE : 0,007
- Une fusion parasite ne compte dans W que si elle contredit une mention or.

## Catégorie × type (accuracy, mentions par exécution)

| Catégorie | character | companion | location | none | object | organization | protagonist |
|---|---|---|---|---|---|---|---|
| PART | 1,000 (37) | — | 0,802 (27) | — | 0,949 (33) | 0,948 (32) | — |
| DESC | 0,878 (52) | — | 0,722 (24) | — | 0,812 (32) | 0,485 (22) | — |
| GAP | 0,970 (11) | — | 1,000 (11) | — | 0,933 (10) | 1,000 (7) | — |
| REVEAL | 1,000 (9) | — | 0,810 (7) | — | 1,000 (6) | 1,000 (5) | — |
| NEW | 0,833 (10) | — | 0,485 (11) | — | 0,667 (7) | 0,833 (8) | — |
| XTYPE | 1,000 (11) | — | 0,967 (10) | — | 0,778 (6) | 0,806 (12) | — |
| EASY | 0,958 (16) | — | 0,857 (14) | — | 1,000 (7) | 1,000 (6) | — |
| PC | — | 0,976 (41) | — | — | — | — | 1,000 (5) |
| SKIP | — | — | — | 0,961 (111) | — | — | — |

Part de chaque type dans les mentions dures : character 0,325, location 0,225, object 0,235, organization 0,215.

## Étage bon marché seul

Résultat de l'étage bon marché seul : pool dur 0,848, macro dure 0,858, EASY+PC+SKIP 0,960, W 0,018, D 0,017.

## Cascade et coût

- Part déterministe des décisions : 0,498
- Taux d'escalade (tours) : 0,265
- Appels par tour : 1,265 (identity 1, identity_strong 0,265)
- Jetons par tour : entrée 2605, sortie 436,8 (estimé : jetons ≈ caractères / 4, sans cache ni réflexion)
- Coût par tour : 0,001749 $ (estimé : jetons ≈ caractères / 4, sans cache ni réflexion)

## Séquences (B³, CEAF-e)

Séquences : non exécutées.
