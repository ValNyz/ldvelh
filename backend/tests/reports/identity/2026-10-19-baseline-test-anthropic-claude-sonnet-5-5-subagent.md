# Évaluation identité — split `test` — anthropic

Modèles : resolver=claude-sonnet-5-5 · exécutions : 1 · scènes : 39

> **Avertissement (D25)** : chiffres = accord avec l'annotateur unique, plafond humain non mesuré.
> Source: answers of subagent:claude-sonnet to the emitted requests (not the API path: no thinking budget, no temperature, model tier of the responder). C@10: on a scene without history, the first-turn reference lists the registry entities in (type, name) order and the scorer keeps the first 10, so a gold id can fall outside for alphabetical reasons, not for the blocking's quality.

## Gate (spec § 3.5)

| Condition | Seuil | Valeur (1 exéc. groupées) | IC 95 % (bootstrap par scène) | Verdict |
|---|---|---|---|---|
| Macro-moyenne A_cat (6 catégories dures) | ≥ 0,90 | 0,254 | [0,200 ; 0,304] | ÉCHEC |
| Accuracy groupée, mentions dures (pool) | ≥ 0,90 | 0,268 | [0,195 ; 0,341] | ÉCHEC |
| Catégorie dure PART seule | ≥ 0,85 | 0,264 | [0,179 ; 0,350] | ÉCHEC |
| Catégorie dure DESC seule | ≥ 0,85 | 0,285 | [0,195 ; 0,407] | ÉCHEC |
| Catégorie dure GAP seule | ≥ 0,85 | 0,000 | [0,000 ; 0,000] | ÉCHEC |
| Catégorie dure REVEAL seule | ≥ 0,85 | 0,000 | [0,000 ; 0,000] | ÉCHEC |
| Catégorie dure NEW seule | ≥ 0,85 | 0,722 | [0,477 ; 0,900] | ÉCHEC |
| Catégorie dure XTYPE seule | ≥ 0,85 | 0,256 | [0,108 ; 0,396] | ÉCHEC |
| Accuracy EASY + PC + SKIP | ≥ 0,97 | 0,810 | [0,730 ; 0,877] | ÉCHEC |
| W fusions abusives | ≤ 0,02 | 0,108 | [0,076 ; 0,143] | ÉCHEC |
| D doublons | ≤ 0,08 | 0,378 | [0,316 ; 0,439] | ÉCHEC |
| C@10 blocage | ≥ 0,98 | 0,397 | [0,350 ; 0,449] | ÉCHEC |
| Révélations correctes R | ≥ 0,90 | — | — | non mesuré ici (§ 3.4 bis) |
| Erreurs de point de vue P | ≤ 0,05 | — | — | non mesuré ici (§ 3.4 bis) |
| Fuites de secrets L | = 0 | — | — | non mesuré ici (§ 3.4 bis) |
| B³ moyen sur les séquences | ≥ 0,85 | — | — | rapporté (gate à partir de la PR 5) |

**Gate des conditions mesurées ici : ÉCHEC ; gate incomplète (R, P, L non mesurés).**
C@10 : blocage sur dev + test, 1 exécution (spec § 3.5).
IC calculés sur les seuls tirages où la mesure est définie ; tirages indéfinis (catégorie absente du tirage) : hard_macro 1/2000, A_NEW 1/2000.
Catégories dures absentes : aucune.

## Planchers par catégorie dure : les deux lectures

- Lecture indicative : plancher 0,85, lu avec son IC large.
- Lecture contraignante : plancher 0,88 si chaque catégorie dure a ≥ 60 mentions en test ; elle ne s'applique pas à ce corpus.

| Catégorie | Mentions test | Moyenne | IC 95 % | Plancher 0,85 | Plancher 0,88 |
|---|---|---|---|---|---|
| PART | 129 | 0,264 | [0,179 ; 0,350] | ÉCHEC | ÉCHEC |
| DESC | 130 | 0,285 | [0,195 ; 0,407] | ÉCHEC | ÉCHEC |
| GAP | 39 | 0,000 | [0,000 ; 0,000] | ÉCHEC | ÉCHEC |
| REVEAL | 27 | 0,000 | [0,000 ; 0,000] | ÉCHEC | ÉCHEC |
| NEW | 36 | 0,722 | [0,477 ; 0,900] | ÉCHEC | ÉCHEC |
| XTYPE | 39 | 0,256 | [0,108 ; 0,396] | ÉCHEC | ÉCHEC |

## Décisions parasites et NEW

- Fusions parasites par tour (MATCH/ALIAS hors or) : 0,231
- NEW parasites par tour (hors or) : 0,077
- Erreurs de type NEW (par exécution) : 1,000
- Précision du NEW : 0,134
- Rappel du NEW : 0,692
- Taux d'UNSURE : 0,000
- Une fusion parasite ne compte dans W que si elle contredit une mention or.

## Catégorie × type (accuracy, mentions par exécution)

| Catégorie | character | companion | location | none | object | organization | protagonist |
|---|---|---|---|---|---|---|---|
| PART | 0,486 (37) | — | 0,222 (27) | — | 0,152 (33) | 0,156 (32) | — |
| DESC | 0,596 (52) | — | 0,042 (24) | — | 0,125 (32) | 0,045 (22) | — |
| GAP | 0,000 (11) | — | 0,000 (11) | — | 0,000 (10) | 0,000 (7) | — |
| REVEAL | 0,000 (9) | — | 0,000 (7) | — | 0,000 (6) | 0,000 (5) | — |
| NEW | 0,700 (10) | — | 0,455 (11) | — | 0,857 (7) | 1,000 (8) | — |
| XTYPE | 0,364 (11) | — | 0,100 (10) | — | 0,333 (6) | 0,250 (12) | — |
| EASY | 1,000 (16) | — | 0,643 (14) | — | 0,286 (7) | 0,167 (6) | — |
| PC | — | 0,634 (41) | — | — | — | — | 0,000 (5) |
| SKIP | — | — | — | 0,973 (111) | — | — | — |

Part de chaque type dans les mentions dures : character 0,325, location 0,225, object 0,235, organization 0,215.

## Étage bon marché seul

Résultat de l'étage bon marché seul : non exécuté.

## Cascade et coût

- Part déterministe des décisions : 0,000
- Taux d'escalade (tours) : 0,000
- Coût par tour : non mesuré (réponses importées)

## Séquences (B³, CEAF-e)

Séquences : non exécutées.
