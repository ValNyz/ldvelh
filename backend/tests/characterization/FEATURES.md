# FEATURES.md - feature to guarding-test map (F-01..F-27)

This is the "no feature loss" checklist from the stabilization roadmap (section 2 and 5).
Every refactor PR must: (1) list the F-xx it touches in its description, (2) keep every
test below green, (3) tick the boxes here. Paths are relative to `backend/`.
The characterization snapshots (`tests/characterization/snapshots/*.json`) record the CURRENT
behavior, bugs included; a known bug is not fixed by phase 0, it is annotated in the last column.

| ID | Fonctionnalité | Tests | Known bugs visible in snapshots |
|---|---|---|---|
| F-01 | Inscription, connexion, vérification d'email, refresh, profil, changement de mot de passe | `tests/test_api_auth.py::test_register`, `tests/test_api_auth.py::test_login_by_email`, `tests/test_api_auth.py::test_login_wrong_password`, `tests/test_api_auth.py::test_me_authenticated`, `tests/test_api_auth.py::test_refresh_token`, `tests/test_api_auth.py::test_change_password`, `tests/test_api_auth.py::test_update_display_name`, `tests/test_remaining_coverage.py::TestAuthServiceVerifyEmail::test_verify_email_success` | — (auth abuse issues are in a private advisory, not listed here) |
| F-02 | Préférences utilisateur et clés API chiffrées (Fernet), masquées | `tests/test_api_preferences.py::test_get_empty_preferences`, `tests/test_api_preferences.py::test_update_provider_preference`, `tests/test_api_preferences.py::test_store_and_mask_api_key`, `tests/test_api_preferences.py::test_remove_api_key`, `tests/test_api_preferences.py::test_invalid_provider` | — |
| F-03 | CRUD des parties : liste, détail, création avec moteur, suppression, renommage | `tests/test_api_games.py::test_create_game`, `tests/test_api_games.py::test_list_games`, `tests/test_api_games.py::test_load_game`, `tests/test_api_games.py::test_rename_game`, `tests/test_api_games.py::test_delete_game`, `tests/test_api_games.py::test_create_game_with_engine` | — |
| F-04 | Liste des genres et détail d'un genre | `tests/test_api_genres.py::test_list_genres`, `tests/test_api_genres.py::test_get_genre_by_id`, `tests/test_api_genres.py::test_get_genre_not_found` | — |
| F-05 | Catalogue fournisseurs et modèles (découverte, prix, groupes) | `tests/characterization/test_c20_tooltips_cost.py::test_c22_providers_endpoint_without_user_keys`, `tests/test_llm_and_extraction.py::TestProviderRegistry::test_get_provider_catalog_shape`, `tests/test_llm_and_extraction.py::TestProviderCatalogAsync::test_no_user_keys_returns_anthropic_models_others_empty`, `tests/test_llm_and_extraction.py::TestProviderCatalogAsync::test_unpriced_models_filtered_out`, `tests/test_llm_and_extraction.py::TestPricingLookup::test_anthropic_claude_sonnet_priced` | — |
| F-06 | Génération du monde via le wizard (genre, difficulté, PJ, PNJ manuels, moteur), flux de progression | `tests/characterization/test_c01_c03_core_flow.py::test_c01_init_world`, `tests/characterization/test_harness_smoke.py::test_init_world_reaches_world_gen` | #9 (Director planned right after INIT, visible in llm_calls). Observation, no issue yet: the INIT branch with `manual_entities` is not characterized |
| F-07 | Première scène d'arrivée (`__ARRIVEE__`), selon le genre | `tests/characterization/test_c01_c03_core_flow.py::test_c02_arrival`, `tests/characterization/test_c04_c06_engines.py::test_c18_dark_fantasy_arrival_has_no_ai_companion_text` | #9 (Director after arrival; genre `arrival_prompt` never used because `load_game_state` lacks `genre_id`; the hard-coded first-light line is effectively dead code, C-18 is xfail(strict) to force that branch) |
| F-08 | Tour de narration streamé (chunks SSE, `done`, `saved`) | `tests/characterization/test_c01_c03_core_flow.py::test_c03_light_turn[tool_use]`, `tests/characterization/test_c01_c03_core_flow.py::test_c03_light_turn[json_schema]`, `tests/characterization/test_c01_c03_core_flow.py::test_c03_light_turn[text]` | #9 (Director call every turn in llm_calls); #10 (structured_output_mode only affects `extract_structured`) |
| F-09 | Moteur `none` | `tests/characterization/test_c01_c03_core_flow.py::test_c03_light_turn[tool_use]` | #9 (same as F-08) |
| F-10 | Moteur `narrative` (traits, résistance) | `tests/characterization/test_c04_c06_engines.py::test_c04_engine_turn_with_test[narrative]` | #9 (Director every turn). Observation, no issue yet: no mechanical step by design |
| F-11 | Moteur Fate Core : jet 4dF, échelle, aspects | `tests/characterization/test_c04_c06_engines.py::test_c04_engine_turn_with_test[fate_core]` | #9 (Director every turn) |
| F-12 | Fate : invocation d'aspects (`roll_pending`, puis reprise avec `roll_id` et `invoked_aspects`) | `tests/characterization/test_c04_c06_engines.py::test_c05_fate_invocation_pending_then_resume` | #9 (Director every turn) |
| F-13 | Fate : compels proposés, acceptés ou refusés | `tests/characterization/test_c04_c06_engines.py::test_c06_fate_compel[proposed]`, `tests/characterization/test_c04_c06_engines.py::test_c06_fate_compel[accepted]`, `tests/characterization/test_c04_c06_engines.py::test_c06_fate_compel[refused]`, `tests/characterization/test_c04_c06_engines.py::test_c06_fate_compel[refused_at_zero]` | Observation, no issue yet: "proposed" is a no-op (not stored, not surfaced); accepted +1 FP, refused -1 FP floored at 0; the compel result is not surfaced in `done` |
| F-14 | Moteur D6 : pool de dés, wild die | `tests/characterization/test_c04_c06_engines.py::test_c04_engine_turn_with_test[d6]` | #9 (Director every turn) |
| F-15 | Deltas narrateur en direct : crédits, indices d'inventaire, révélations d'entités | `tests/characterization/test_c07_c11_world_updates.py::test_c07_credit_and_inventory_deltas` | Observation, no issue yet: inventory hints (item_name/item_description) are not applied live, they only feed the inventory extractor, which writes the rows |
| F-16 | `info_requests` : préchargement d'entités au tour suivant | `tests/characterization/test_c07_c11_world_updates.py::test_c08_info_requests_prefetch` | Observation, no issue yet: the details block persists across later turns until a day transition (not consumed after use) |
| F-17 | Changement de jour (`day_transition`, cycle et date) | `tests/characterization/test_c07_c11_world_updates.py::test_c09_day_transition`, `tests/characterization/test_c07_c11_world_updates.py::test_c09b_day_transition_strictness[no_date]`, `tests/characterization/test_c07_c11_world_updates.py::test_c09b_day_transition_strictness[no_cycle]`, `tests/characterization/test_c07_c11_world_updates.py::test_c09b_day_transition_strictness[extra_key]`, `tests/characterization/test_c07_c11_world_updates.py::test_c09b_day_transition_strictness[new_cycle_ignored]` | #16 (missing new_cycle or new_date discards the whole turn); observation, no issue yet: payload `new_cycle` is ignored, cycle is always current+1 |
| F-18 | Extraction en arrière-plan : resolver puis extracteurs | `tests/characterization/test_c07_c11_world_updates.py::test_c10_extraction_writes_entities`, `tests/characterization/test_c01_c03_core_flow.py::test_c03_light_turn[tool_use]`, `tests/characterization/test_c12_c17_control_flow.py::test_c17_back_to_back_turns_keep_both_extractions` | #17 (back-to-back turns: second extraction skipped "already extracting", C-17 is xfail(strict)) |
| F-19 | Director : plan de scénario en arrière-plan, injecté au narrateur | `tests/characterization/test_c07_c11_world_updates.py::test_c11_director_plan_written` | #9 (Director runs after every turn, all engines) |
| F-20 | Rollback, édition, régénération d'un message | `tests/characterization/test_c12_c17_control_flow.py::test_c12_rollback_regenerate` | #11, #22, #24 (rollback is cycle-based: messages restored, but characters, director_plans and extraction_logs created in the target cycle survive; entity_registry never cleaned) |
| F-21 | Partie occupée : un second `/chat` concurrent est rejeté | `tests/characterization/test_c12_c17_control_flow.py::test_c13_busy_game_rejected` | — |
| F-22 | Erreur « aucune clé API » | `tests/characterization/test_c12_c17_control_flow.py::test_c14_missing_api_key` | — |
| F-23 | Tooltips et annotations d'entités | `tests/characterization/test_c20_tooltips_cost.py::test_c20_tooltips_annotations_and_entity`, `tests/test_resolver.py::TestBuildSpanAnnotations::test_single_mention`, `tests/test_game_and_populator.py::TestFirstTurnResolver::test_first_turn_reference_built` | Observation, no issue yet: the pre-existing `test_context_and_tooltips.py` has NO test of the `/tooltips/*` endpoints (api/tooltips.py was at 11% coverage), so C-20 was added; the C-20 snapshot has an empty annotation list because the scripted resolver yields no spans |
| F-24 | Panneau monde (`/games/{id}/world`) | `tests/characterization/test_c12_c17_control_flow.py::test_c15_world_panel` | Observation, no issue yet: the panel lists only characters known_by_protagonist (by design) |
| F-25 | Compteur de coût de session et coût par message (toggle debug) | `tests/characterization/test_c20_tooltips_cost.py::test_c21_cost_recorded_on_message_and_session`, `tests/test_llm_and_extraction.py::TestCostTracker::test_get_summary_grouped_by_purpose`, `tests/test_sse_payload.py::TestSSEDonePayload::test_light_mode` | Observation, no issue yet: the C-03 snapshot does not assert cost (the roadmap pointed there); C-21 does. The scripted model is unpriced, so `cost_usd` is 0.0 and the session total does not grow |
| F-26 | Fiche personnage et stats moteur dans l'UI, modale d'invocation | MANUAL: smoke Playwright Firefox, voir roadmap section 5.4 | — |
| F-27 | Landing page et pages auth | MANUAL: smoke Playwright Firefox, voir roadmap section 5.4 | — |

Other guards that are not tied to one F-xx: `tests/characterization/test_c19_legacy.py::test_c19_legacy_game_loads_and_plays`
(pre-refactor saved game still loads and plays; it does NOT test that migrations preserve saves),
`tests/characterization/test_harness_smoke.py` and `tests/characterization/test_scripted_llm.py` (harness self-tests).

## Per-PR checklist

- [ ] F-xx touched are listed in the PR description
- [ ] Full suite green locally (Postgres with `fsync=off`) and CI green
- [ ] Snapshots unchanged, or changed only for a fixed issue (see below)
- [ ] Legacy fixture (C-19) replayed if the phase contains a migration
- [ ] Manual smoke (F-26, F-27) in phases P1, P3, P5, P7, P8

## Comment mettre à jour un snapshot

A behavior change is allowed only when it fixes an issue listed in the phase. Then:

1. Run the affected test(s) with `UPDATE_SNAPSHOTS=1` to rewrite the JSON, for example
   `UPDATE_SNAPSHOTS=1 python -m pytest tests/characterization/test_c01_c03_core_flow.py -q`.
2. Review the `git diff` of `tests/characterization/snapshots/*.json` line by line: every
   changed line must be explained by the fixed issue. An unexplained diff is a regression.
3. Cite the fixed issue in the commit message (for example `Fix director running every turn (#9)`).
4. Update the "Known bugs visible in snapshots" column of this file in the same commit
   (remove the issue that is now fixed, or add the new observation).
5. If an xfail(strict) test (C-17, C-18) starts passing, remove its xfail marker in the same commit.

## Check that every node id listed here is collectable

```bash
cd backend && grep -o '`tests/[^`]*::[^`]*`' tests/characterization/FEATURES.md | tr -d '`' | sort -u \
  | xargs python -m pytest --collect-only -q 2>&1 | tail -3
```

All cited ids contain `::`; the last line must report no error and "N tests collected".
