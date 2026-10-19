# Backend scripts

## Model catalog refresh (`refresh_model_catalog.py`)

Keeps the `llm_models` table in sync with what each provider really offers.
**A model is shown to players only if its status is `enabled`.**

### Scheduled task (Coolify)

- Container: `backend` (WORKDIR is `/app`)
- Command: `cd /app && python -m scripts.refresh_model_catalog`
- Frequency: `0 4 * * *` (daily)
- **Timeout: raise it to 3600 s** (Coolify scheduled tasks have a per-task
  timeout, 300 s by default in recent versions: check yours). See "Run time" below.

Environment variables (read by `config.Settings`):

| Variable | Default | Meaning |
|---|---|---|
| `CATALOG_KEYS_USER_EMAIL` | empty | Player whose API keys saved in the app are used when the server has no key (also `--user-email`) |
| `CATALOG_AUTO_ENABLE` | `mistral,wandb,nebius,nous` | Providers whose new, working, priced models are enabled automatically. Anthropic is never auto-enabled, even if listed |

### Flags

```
python -m scripts.refresh_model_catalog [--provider P]... [--user-email E] [--reprobe-all] [--dry-run]
python -m scripts.refresh_model_catalog --enable P MODEL
python -m scripts.refresh_model_catalog --disable P MODEL
python -m scripts.refresh_model_catalog --set-role P MODEL ROLE   # ROLE: narration | mechanical
```

`--dry-run` writes nothing but still makes the paid probe calls (a few hundred
tokens per probed model).

### What a run does

1. Lists each provider's live models (a failed or empty listing writes nothing for that provider).
2. Inserts new chat models as `pending`.
3. Retires `auto` rows no longer listed. Enabled rows and role holders are retired only after 3 consecutive absences.
4. Probes role holders and new / pending / failed models that have a price (an unpriced model can never be enabled, so it is not probed); a `failed` model is re-probed at most once every 7 days (`last_probed_at`). `--reprobe-all` probes every listed model. A temperature / tool_choice error triggers one retry with an adjusted profile.
5. Sets the status: probes OK and price known -> `enabled` if the provider auto-enables or the model was enabled before, else `pending`; probe failure -> `failed`.
6. Makes sure `narration` and `mechanical` each have an enabled, priced model: seeded rank first, then the provider's own default for that role (`MODEL_MAIN` / mechanical model), then the cheapest.
7. Fills prices.

The paid probes (step 4) run **before** the per-provider write transaction:
the rows are planned from an unlocked read, probed, then re-read under
`FOR UPDATE` and updated in one short transaction. A run killed while probing
writes nothing for the provider in progress (providers already done are
committed) and never blocks a manual `--enable` / `--disable` / `--set-role`;
a manual change made during the probes wins.

### Run time

Each probed model makes 3 calls (stream, JSON, structured), each capped at
90 s; a temperature / tool_choice error adds at most 2 more rounds.

- Daily run: role holders (2 per provider, about 10) plus new priced models
  and the weekly re-probe of failed ones. Typically 5-15 s per model, so
  **1-5 minutes**. Worst case if every role holder times out on every call:
  10 x 3 x 90 s = **45 minutes**.
- First run (or `--reprobe-all`): every priced chat model is probed (about
  100 across Mistral, Nous, W&B and Nebius), **15-30 minutes** typically.
  Run it by hand once per provider (`--provider mistral`, ...) before enabling
  the schedule.

Providers are processed in a fixed order (anthropic, mistral, nebius, nous,
wandb): with too short a timeout the last ones may never be refreshed. Hence the
3600 s timeout; check the task logs for a `[catalog] wandb:` report line.

Demotion rules for an enabled model: it is demoted after 3 consecutive failed
runs, or at once on a permanent error (404 / model not found / invalid model).
429, 5xx and timeouts never demote on their own. A previously enabled model that
recovers returns to `enabled`. Manual rows (`source='manual'`, e.g. the seeded
Claude 5 rows) keep their status and profile.

### Prices

Resolved in this order: manual > provider listing > code table
(`services/pricing.py`) > models.dev > OpenRouter (estimate, Nous only). The
origin is stored in `price_source`. A price change above 50% is logged.
Values that are not finite, negative or >= 100000 USD/MTok are ignored (logged)
and the next source is tried. Prices are rounded to 6 decimals like the DB.
The app registers catalog prices for cost tracking when it loads the catalog.

A manual price (never overwritten by a refresh) has no CLI flag; set it in SQL:

```sql
UPDATE llm_models
   SET input_price = 1.20, output_price = 4.80,        -- USD per million tokens
       cache_write_price = 0, cache_read_price = 0.12,
       price_source = 'manual', updated_at = now()
 WHERE provider = 'nous' AND model_id = 'Hermes-4-405B';
```

Set `price_source` back to `NULL` to let the next refresh fill the price again.

### Reading the report

One block per provider: `N new, N retired, ok/total probed OK`, then
`model -> status` lines, role changes (`narration -> model`) and
`ROLE: NO ENABLED MODEL` when a role lost its last model. Keys are never printed.

Exit code `1` if a provider could not be listed, a role lost its last enabled
model, no provider has a key, or a manual action failed; otherwise `0`.
Check the task's exit status in Coolify.

### Enabling an Anthropic model

Anthropic has no model listing endpoint here: the refresh only knows the models
built into `AnthropicProvider.MODELS` plus the rows already in the table, so it
never discovers a new Claude model, and it never auto-enables one. To offer a
new model, after checking its rules (see the Claude 5 notes: no temperature, no
forced tool_choice, thinking counts in max_tokens), add it by hand (it is
inserted with the Claude 5 rules as its profile):

```
python -m scripts.refresh_model_catalog --enable anthropic claude-...
```

If `services/pricing.py` does not know its price, set a manual price (SQL in
"Prices"): an unpriced model is hidden from players.

## Provider smoke test (`smoke_providers.py`)

Manual live check of each provider's chat models (real, paid calls). Its probes
are reused by the catalog refresh. See its docstring for usage.

## Identity evaluation (`eval_identity.py`)

Scores a resolver against the identity gold corpus (`tests/fixtures/identity/`,
rules in its `ANNOTATION.md`) and writes the report of spec § 3.5 to
`tests/reports/identity/<date>-<split>-<provider>-<models>[-<responder kind>].md|json`.
Run it through `scripts/eval-identity.sh ARGS...` from the repo root (Docker, repo
mounted read-only, runs as your user, provider keys given to the final command only,
throwaway Postgres only for adapters that read the database).

```
scripts/eval-identity.sh --adapter legacy --split test --runs 1 --provider anthropic
python -m scripts.eval_identity --adapter legacy --split dev [--sequences] [--category C] [--scene ID]
python -m scripts.eval_identity ... --emit-prompts DIR       # no call: one <scene id>.json per request
python -m scripts.eval_identity ... --import-responses DIR --responder subagent:claude-sonnet
```

- `--adapter legacy`: the current resolver (`services/extraction/resolver.py`), driven as
  the extraction orchestrator drives it (`evals/identity/adapters/legacy_resolver.py`).
  `--models resolver=MODEL` overrides its model (the v2 adapter will take
  `identity=` / `identity_strong=`, `--tier` and `--annotate-blind`).
- Live runs make real, paid calls; the key is the server's (`ANTHROPIC_API_KEY`...) or,
  with a real database, the one the player of `CATALOG_KEYS_USER_EMAIL` saved.
- `--emit-prompts` / `--import-responses` produce the report without an API key: the
  requests are answered elsewhere, the raw answers `<scene id>.txt` are parsed by the
  app's own code. `--responder KIND:DETAIL` (required) says who answered; it goes in the
  report header and json, and its kind ends the file name, so the report names the app
  model it emulates (`...-claude-sonnet-5-5-subagent`) without passing for an API run.
  With `eval-identity.sh`, set `EVAL_IO` to the host directory and pass `/io/<path>`.
- `--sequences` adds every sequence (B³, CEAF-e). With the legacy adapter, MESSAGE 1 of a
  turn is its gold history, not the system's own previous annotations: the report
  header says so.
- `--gate`: exit code 1 when a measured gate row fails. C@10 is measured on dev + test.
- Reports: only `*-baseline-*` and `*-gate-*` files of `tests/reports/identity/` are
  committed (`.gitignore`); the legacy baseline is
  `2026-10-19-baseline-{test,dev}-anthropic-claude-sonnet-5-5-subagent.md|json`.
- When to re-evaluate, and the rules of the frozen test split (`TEST_SHA256`): see
  CONTRIBUTING.md, "Identity evaluation".
