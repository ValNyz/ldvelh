# Évaluation identité — split `dev` — anthropic

Modèles : resolver=claude-sonnet-5-5 · exécutions : 1 · scènes : 64

> **Avertissement (D25)** : chiffres = accord avec l'annotateur unique, plafond humain non mesuré.
> Source: answers of subagent:claude-sonnet to the emitted requests (not the API path: no thinking budget, no temperature, model tier of the responder). Sequences: MESSAGE 1 of each turn is the gold history annotated with world labels, not the system's own annotations of its previous turn. C@10: on a scene without history, the first-turn reference lists the registry entities in (type, name) order and the scorer keeps the first 10, so a gold id can fall outside for alphabetical reasons, not for the blocking's quality.

## Gate (spec § 3.5)

| Condition | Seuil | Valeur (1 exéc. groupées) | IC 95 % (bootstrap par scène) | Verdict |
|---|---|---|---|---|
| Macro-moyenne A_cat (6 catégories dures) | ≥ 0,90 | 0,318 | [0,278 ; 0,360] | ÉCHEC |
| Accuracy groupée, mentions dures (pool) | ≥ 0,90 | 0,366 | [0,304 ; 0,437] | ÉCHEC |
| Catégorie dure PART seule | ≥ 0,85 | 0,454 | [0,363 ; 0,556] | ÉCHEC |
| Catégorie dure DESC seule | ≥ 0,85 | 0,380 | [0,281 ; 0,490] | ÉCHEC |
| Catégorie dure GAP seule | ≥ 0,85 | 0,000 | [0,000 ; 0,000] | ÉCHEC |
| Catégorie dure REVEAL seule | ≥ 0,85 | 0,000 | [0,000 ; 0,000] | ÉCHEC |
| Catégorie dure NEW seule | ≥ 0,85 | 0,863 | [0,731 ; 0,952] | OK |
| Catégorie dure XTYPE seule | ≥ 0,85 | 0,211 | [0,100 ; 0,341] | ÉCHEC |
| Accuracy EASY + PC + SKIP | ≥ 0,97 | 0,833 | [0,780 ; 0,883] | ÉCHEC |
| W fusions abusives | ≤ 0,02 | 0,101 | [0,071 ; 0,135] | ÉCHEC |
| D doublons | ≤ 0,08 | 0,319 | [0,263 ; 0,379] | ÉCHEC |
| C@10 blocage | ≥ 0,98 | 0,397 | [0,350 ; 0,449] | ÉCHEC |
| Révélations correctes R | ≥ 0,90 | — | — | non mesuré ici (§ 3.4 bis) |
| Erreurs de point de vue P | ≤ 0,05 | — | — | non mesuré ici (§ 3.4 bis) |
| Fuites de secrets L | = 0 | — | — | non mesuré ici (§ 3.4 bis) |
| B³ moyen sur les séquences | ≥ 0,85 | 0,872 | [0,856 ; 0,884] | rapporté (gate à partir de la PR 5) |

**Gate des conditions mesurées ici : ÉCHEC ; gate incomplète (R, P, L non mesurés).**
C@10 : blocage sur dev + test, 1 exécution (spec § 3.5).
IC : la mesure est définie sur tous les tirages.
Catégories dures absentes : aucune.

## Planchers par catégorie dure : les deux lectures

- Lecture indicative : plancher 0,85, lu avec son IC large.
- Lecture contraignante : plancher 0,88 si chaque catégorie dure a ≥ 60 mentions en test ; elle ne s'applique pas à ce corpus.

| Catégorie | Mentions dev | Moyenne | IC 95 % | Plancher 0,85 | Plancher 0,88 |
|---|---|---|---|---|---|
| PART | 196 | 0,454 | [0,363 ; 0,556] | ÉCHEC | ÉCHEC |
| DESC | 192 | 0,380 | [0,281 ; 0,490] | ÉCHEC | ÉCHEC |
| GAP | 60 | 0,000 | [0,000 ; 0,000] | ÉCHEC | ÉCHEC |
| REVEAL | 39 | 0,000 | [0,000 ; 0,000] | ÉCHEC | ÉCHEC |
| NEW | 51 | 0,863 | [0,731 ; 0,952] | OK | ÉCHEC |
| XTYPE | 57 | 0,211 | [0,100 ; 0,341] | ÉCHEC | ÉCHEC |

## Décisions parasites et NEW

- Fusions parasites par tour (MATCH/ALIAS hors or) : 0,281
- NEW parasites par tour (hors or) : 0,094
- Erreurs de type NEW (par exécution) : 0,000
- Précision du NEW : 0,169
- Rappel du NEW : 0,849
- Taux d'UNSURE : 0,000
- Une fusion parasite ne compte dans W que si elle contredit une mention or.

## Catégorie × type (accuracy, mentions par exécution)

| Catégorie | arc | character | companion | location | none | object | organization | protagonist |
|---|---|---|---|---|---|---|---|---|
| PART | 0,000 (2) | 0,679 (56) | — | 0,439 (57) | — | 0,250 (40) | 0,390 (41) | — |
| DESC | — | 0,694 (85) | — | 0,179 (39) | — | 0,056 (36) | 0,156 (32) | — |
| GAP | — | 0,000 (15) | — | 0,000 (15) | — | 0,000 (15) | 0,000 (15) | — |
| REVEAL | — | 0,000 (11) | — | 0,000 (8) | — | 0,000 (10) | 0,000 (10) | — |
| NEW | — | 0,857 (14) | — | 0,867 (15) | — | 0,818 (11) | 0,909 (11) | — |
| XTYPE | — | 0,167 (12) | — | 0,278 (18) | — | 0,176 (17) | 0,200 (10) | — |
| EASY | — | 0,810 (21) | — | 0,750 (24) | — | 0,500 (4) | 0,688 (16) | — |
| PC | — | — | 0,611 (72) | — | — | — | — | 0,000 (2) |
| SKIP | — | — | — | — | 0,962 (185) | — | — | — |

Part de chaque type dans les mentions dures : arc 0,003, character 0,324, location 0,255, object 0,217, organization 0,200.
Types sous 0,15 des mentions dures : arc.

## Étage bon marché seul

Résultat de l'étage bon marché seul : non exécuté.

## Cascade et coût

- Part déterministe des décisions : 0,000
- Taux d'escalade (tours) : 0,000
- Coût par tour : non mesuré (réponses importées)

## Séquences (B³, CEAF-e)

- Séquences : 7
- B³ F1 moyen : 0,872 [0,856 ; 0,884]
- CEAF-e moyen : 0,762 [0,735 ; 0,792]
