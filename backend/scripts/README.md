# Backend scripts

## Model catalog refresh (`refresh_model_catalog.py`)

Keeps the `llm_models` table in sync with what each provider really offers.
**A model is shown to players only if its status is `enabled`.**

### Scheduled task (Coolify)

- Container: `backend` (WORKDIR is `/app`)
- Command: `cd /app && python -m scripts.refresh_model_catalog`
- Frequency: `0 4 * * *` (daily)

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
4. Probes new, pending, failed and role-holding models (all of them with `--reprobe-all`), retrying once with an adjusted profile on a temperature / tool_choice error.
5. Sets the status: probes OK and price known -> `enabled` if the provider auto-enables or the model was enabled before, else `pending`; probe failure -> `failed`.
6. Makes sure `narration` and `mechanical` each have an enabled model.
7. Fills prices.

Demotion rules for an enabled model: it is demoted after 3 consecutive failed
runs, or at once on a permanent error (404 / model not found / invalid model).
429, 5xx and timeouts never demote on their own. A previously enabled model that
recovers returns to `enabled`. Manual rows (`source='manual'`, e.g. the seeded
Claude 5 rows) keep their status and profile.

### Prices

Resolved in this order: manual > provider listing > code table
(`services/pricing.py`) > models.dev > OpenRouter (estimate, Nous only). The
origin is stored in `price_source`. A price change above 50% is logged.

### Reading the report

One block per provider: `N new, N retired, ok/total probed OK`, then
`model -> status` lines, role changes (`narration -> model`) and
`ROLE: NO ENABLED MODEL` when a role lost its last model. Keys are never printed.

Exit code `1` if a provider could not be listed, a role lost its last enabled
model, no provider has a key, or a manual action failed; otherwise `0`.
Check the task's exit status in Coolify.

### Enabling an Anthropic model

Anthropic discoveries stay `pending`. After checking the model's rules (see the
Claude 5 notes: no temperature, no forced tool_choice, thinking counts in
max_tokens), enable it by hand:

```
python -m scripts.refresh_model_catalog --enable anthropic claude-...
```

## Provider smoke test (`smoke_providers.py`)

Manual live check of each provider's chat models (real, paid calls). Its probes
are reused by the catalog refresh. See its docstring for usage.
