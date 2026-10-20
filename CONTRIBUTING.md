# Contributing & Development

## Architecture

```
Frontend (Next.js)  ←→  Backend (FastAPI)  ←→  PostgreSQL
                              ↕
                        Claude API (LLM)
```

- **Frontend**: Next.js with SSE streaming
- **Backend**: Python/FastAPI, async PostgreSQL (asyncpg)
- **Database**: Dedicated tables + entity registry for cross-entity references
- **AI**: Claude Sonnet (narration), parallel specialized extractors (world state)

## Project structure

```
backend/
├── api/            # FastAPI routes (auth, game, chat), SSEWriter
├── domain/         # Pure types (turn, errors, game, identity), no I/O
├── kg/             # Knowledge graph (populator by entity id, reader, refs)
├── pipeline/       # Turn pipeline: steps/{load,arbitrate,narrate,commit,respond,schedule}, init_flow, post_turn
├── workers/        # Per-game job supervisor and turn locks (in-process, imports no other layer)
├── repos/          # SQL (games, turns, uow, entities, llm_calls, users, llm_models)
├── prompts/        # LLM prompt templates
├── schema/         # Pydantic models
├── services/       # Business logic (game, LLM, extraction, identity, auth, post-turn hooks and subscribers, Director)
├── tests/          # Unit + integration tests (700+)
├── startup_checks.py  # Secrets validation run before startup (JWT_SECRET, ENCRYPTION_KEY)
└── main.py

frontend/
├── app/            # Next.js pages
├── components/     # React components
├── hooks/          # Custom hooks
└── lib/            # API client, game logic

db/migrations/      # PostgreSQL schema: baseline migration + incremental ones (dbmate)
```

## Setup

### Docker Compose (whole stack)

```bash
scripts/dev-setup.sh      # once: docker-compose.override.yml + .env with random secrets
docker compose up --build # frontend http://localhost:3000, backend http://localhost:8000
```

`docker-compose.yml` is the production file (deployed by Coolify) and is fail-closed: without `JWT_SECRET`, `DB_PASSWORD` or `ENCRYPTION_KEY`, `docker compose` stops with `required variable JWT_SECRET is missing a value: ... (for local dev, run scripts/dev-setup.sh)`, and `DEBUG` defaults to `false`. Everything that only makes sense locally lives in `docker-compose.override.yml`, which `docker compose up` applies automatically: published ports, `DEBUG=true` and the dev user (`dev@ldvelh.local` / `devpassword`, seeded in debug mode only).

That override is git-ignored and created from the committed `docker-compose.override.example.yml`, so a server that runs a plain `docker compose up` on a fresh clone never gets debug mode or the dev account by accident. `scripts/dev-setup.sh` is safe to re-run: it keeps an existing override and existing values in `.env`, and only fills `JWT_SECRET` (when empty or refused by the backend rules), `ENCRYPTION_KEY` (when empty) and `DB_PASSWORD` (`ldvelh`, the password of existing local `pgdata` volumes). It checks the existing values with the backend's own rules (`backend/startup_checks.py`, when `python3` with `cryptography` is available; otherwise an equivalent shell check that reads the published values from that file): a `JWT_SECRET` the backend would refuse is regenerated (it only signs local sessions), but a set `ENCRYPTION_KEY` is never overwritten (saved API keys depend on it): if it would be refused, the script prints a warning and the `sed` command that replaces it. After pulling this change, run it once: the formerly tracked `docker-compose.override.yml` is deleted by the pull and the script writes your own, ignored copy. If you had edited the tracked file, the pull stops on a conflict instead: back up your copy (`mv docker-compose.override.yml /tmp/`), pull, run the script, then port your edits into the new `docker-compose.override.yml`.

### Backend

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example .env  # set DATABASE_URL, JWT_SECRET (openssl rand -hex 32), ENCRYPTION_KEY, API keys
uvicorn main:app --reload
```

`scripts/dev-setup.sh` writes a random `JWT_SECRET` and `ENCRYPTION_KEY` into the root `.env`: copy those two lines, or generate them yourself (`ENCRYPTION_KEY`: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`); `ENCRYPTION_KEY` may stay empty only with `DEBUG=true`.

The backend refuses to start (`backend/startup_checks.py`), whatever `DEBUG` says, when `JWT_SECRET` is under 32 characters, has leading/trailing whitespace, uses fewer than 8 distinct characters, contains `change-me` or is a value published in the repo; and when `ENCRYPTION_KEY` is set but has leading/trailing whitespace, is not a valid Fernet key or is a published one. An empty `ENCRYPTION_KEY` is refused outside debug mode.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Database

The schema is the baseline migration (`db/migrations/20260413000000_baseline.sql`) plus the later ones in `db/migrations/` (dbmate format). They are applied at backend boot inside the container (`docker compose up`); never run dbmate from the host against a real database.

Identity data (#152): after `dbmate up` the entrypoint runs `python -m scripts.identity_backfill` (languages, norms, mentions, classification of unknown characters; idempotent, honours `IDENTITY_BACKFILL_EXCEPTIONS`), preceded by `scripts.sync_lang_packs` before the migrations. `scripts/test-backend.sh` does the pack sync too. See "Deploying the identity migration".

Turn journal (#105): every table holding world state must be attached to the journal in the migration that creates it, with `SELECT ldvelh_journal('<table>');` (optionally a second argument, the column list of `UPDATE OF`). Without it, the rollback of P5b cannot undo the writes to that table. Tables that are not world state (accounting such as `llm_calls`, users, catalog, the journal itself) go in `NOT_JOURNALED` of `tests/test_journal.py::test_journal_is_attached_to_every_world_table`, which fails for any table with a `game_id` that is neither attached nor excluded (world tables without a `game_id`, the pivots, go in `PIVOTS` of the same test). Writes that must be journaled run inside `repos.uow.uow(conn, turn_id)`, the outermost transaction of the connection.

## Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | — |
| `ANTHROPIC_API_KEY` | Claude API key (server fallback) | — |
| `JWT_SECRET` | JWT signing key, required: 32+ random characters, no outer whitespace, 8+ distinct characters, no `change-me`, not a published value (checked at startup, even in debug) | — |
| `ENCRYPTION_KEY` | Fernet key for stored API keys: required by `docker-compose.yml` and at startup unless `DEBUG=true`; must be a valid, unpublished Fernet key; never change it once set | — |
| `DB_PASSWORD` | Postgres password, required by `docker-compose.yml`; URL-safe (it goes into `DATABASE_URL`) | — |
| `EMAIL_FROM` | Sender of verification emails | `noreply@yourdomain.com` |
| `RESEND_API_KEY` | Resend key for verification emails (optional) | — |
| `NEXT_PUBLIC_API_URL` | Frontend build arg: backend base URL; empty means same origin (`/api`) | compose: `http://localhost:8000` when unset |
| `REGISTRATION_ENABLED` | Enable/disable registration | `true` |
| `DEBUG` | Debug mode (seeds dev user, streams debug payloads): local only, set by `docker-compose.override.yml` | `false` |
| `DEV_USER_EMAIL` / `DEV_USER_PASSWORD` | Dev account seeded in debug mode | `dev@ldvelh.local` / `devpassword` |
| `LOG_PROMPTS` | Log narrator prompts and JSON (DEBUG level) | `false` |
| `CORS_ORIGINS` | Allowed origins | `http://localhost:3000` |
| `TRUSTED_PROXY_HOPS` | Reverse proxies in front of the backend that append to `X-Forwarded-For`; the client IP used by the rate limits is the entry the outermost one added. `0` ignores the header (TCP peer) | `0`; `docker-compose.yml`: `1` (Traefik); override: `0` |
| `JWT_SESSION_MAX_HOURS` | Absolute session lifetime: a refresh never extends a session past it, then the player logs in again | `720` |
| `SUPERVISOR_MAX_GAMES` | Games that may run a background job (extraction, Director) at once; at least 1 | `3` |
| `SUPERVISOR_DRAIN_TIMEOUT` | Seconds the shutdown waits for background jobs before cancelling them; greater than 0. Keep it, plus the 5 s cancel grace, under `stop_grace_period` | `20` |
| `SUPERVISOR_CANCEL_TIMEOUT` | Seconds a rollback waits for the game's cancelled background jobs; greater than 0 | `10` |
| `ROLLBACK_ENGINE` | `journal` replays the turn journal; `cycle` is the legacy cycle-based rollback, kept one release (WARNING at startup; removal #160). Do not switch back to `journal` for games rolled back under `cycle` meanwhile: the cycle path rewrites world rows outside the journal | `journal` |

## Running tests

There is no need for a local Postgres or Python venv: the scripts run everything in Docker (run them from anywhere in the repo).

```bash
scripts/test-backend.sh                      # full backend suite (Postgres 18 + migrations, same env as CI)
scripts/test-backend.sh tests/pipeline -x    # arguments are passed to pytest
scripts/test-e2e.sh                          # frontend build + Playwright (screenshots copied to $E2E_OUT, default /tmp/ldvelh-e2e)
```

Without Docker, from `backend/` against your own `ldvelh_test` database:

```bash
pytest tests/ -m "not integration" -q       # unit tests (no DB needed)
pytest tests/ -m integration -q             # integration tests
pytest tests/ -m "not integration" --cov=. --cov-branch -q
```

Frontend:

```bash
cd frontend
npm test            # unit tests (node --test, pure .mjs modules)
npx playwright install chromium   # once
npm run test:e2e    # builds the static export and drives it in Chromium against a mocked API
```

The e2e tests (`frontend/tests/e2e/`) answer every `/api` call from `mockApi.mjs`, so they need neither the backend nor an LLM key. Screenshots of the key screens land in `frontend/test-results/screens/`.

## Identity evaluation

The entity-identity work (phase 6, #151) is measured against a hand-annotated gold corpus, never against the live game. Everything lives under `backend/`:

- **Corpus**: `tests/fixtures/identity/` — `scenes/*.yaml` (one narration with its world, history and gold mentions), `sequences/*.yaml` (5-10 chained turns with gold clusters, for B³ / CEAF-e), and `ANNOTATION.md`, the annotation guide (categories, decisions, resolved cases). `scenes/_example.yaml` is a format example, never measured. Every scene is validated by `tests/identity/test_corpus.py`: an invalid scene fails CI.
- **Language-agnostic code**: the closed word lists (determiners, pronouns, apostrophes) are data, in the language pack `backend/packs/lang/<language>.yaml`, which the identity service and `ldvelh_norm` (via `lang_packs`) also read; `evals/identity/lexicon/<language>.yaml` only adds the evaluation's own lists (`unambiguous_pronouns`). `tests/identity/test_genericity.py` keeps pack words out of the rest of the backend; `tests/identity/test_lexicon.py` fails if a language or genre word appears as a literal in `evals/identity/` (adapters included; `report.py` excepted, its French labels are display text, configurable from PR 5) or the identity scripts. A scene in another language declares `language:` and needs its language pack and evaluation lexicon.
- **Split by campaign**: `tests/fixtures/identity/split.yaml` (dev about 60 %, test about 40 % of every category) is generated by `python -m scripts.identity_corpus_split`, which moves whole campaigns (`campaign:`, the scenes that share a world or a history) so that no test narration shows up on the dev side. Sequences are not in the split; they are dev-side material, so their B³ / CEAF-e is a dev-side regression number, not a held-out measure (holding some sequences out is a decision for the PR that makes B³ a gate).
- **Frozen test split**: `TEST_SHA256` is the fingerprint of the test scene files, checked by `test_frozen_test_split_fingerprint_matches`. Refreeze it (`python -m scripts.identity_corpus_split --freeze --keep-split`) only for a gold correction of a test scene, in its own PR that explains the correction. Never re-split, and never refreeze once prompt or resolver tuning has started: from then on the test split is read, not edited, or its numbers stop meaning anything.
- **Adding a scene after the freeze**: a new scene goes to dev with `python -m scripts.identity_corpus_split --add-dev SCENE_ID...`. It appends the ids to the dev list and leaves the test list and `TEST_SHA256` untouched; it refuses a scene whose campaign has test scenes (its history would show test gold on the dev side). Never edit `split.yaml` by hand.
- **Evaluation**: `python -m scripts.eval_identity` (or `scripts/eval-identity.sh ARGS...`, which runs it in Docker with the repo read-only) scores a resolver adapter and writes `tests/reports/identity/<date>-<split>-<provider>-<models>[-<responder kind>].md|json`: the gate of spec § 3.5 with 95 % bootstrap intervals per scene, the per-category floors, spurious decisions, category × type, cost and B³ / CEAF-e. Only the baseline and gate reports (`*-baseline-*`, `*-gate-*`) are committed; other reports are ignored by git.
- **Two modes**:
  - *live API*: `--provider anthropic --runs N` makes real, paid calls with the server key (`ANTHROPIC_API_KEY`...);
  - *emit / import*, without an API key: `--emit-prompts DIR` writes one `<scene id>.json` per request, exactly what the app would send (model, options, system, messages); someone else answers each one into `<scene id>.txt` (for the baseline, Claude subagents of the app's model tier); `--import-responses DIR --responder KIND:DETAIL` parses those answers with the app's own code and scores them. `--responder` is required: it is printed in the report header and json and its kind ends the file name (`...-claude-sonnet-5-5-subagent`), so an imported report never passes for an API run.
- **Resolver v2** (`--adapter v2`, #154): runs the app's own resolver v2 on a scratch game of a throwaway database (`eval-identity.sh` starts one), rolled back after each scene. Its model calls follow the catalog roles **`identity`** (the small model that decides every turn: Haiku on Anthropic) and **`identity_strong`** (the strong model of the escalation: Sonnet); `--models identity=…,identity_strong=…` overrides them, `--tier cheap` turns the escalation off (the small model alone). Its emit / import is **staged**, because the second call of a turn depends on the first answer: one request per call, `<token>.<n>.json` (an opaque hash of the scene id, whose name gives away the gold category; the request carries its `purpose` and `model`, so it can be routed to the right responder), answered in `<token>.<n>.txt` as `backend/evals/identity/RESPONDERS.md` says (a responder reads only the request files it is given and writes only their `.txt`); each run replays the answered calls and writes the next unanswered one, listed in `DIR/pending.json`, until nothing is pending (`--import-responses` exits with code 3 and scores nothing while a request is pending). `--runs N` uses `DIR/run1` … `DIR/runN`. A replayed run's tokens are estimated (characters / 4, no cache, no thinking) and priced from the model prices when known; the report says so. A cascade import also replays the cheap tier from the same answers. `--milestone pr2` adds the PR 2 gate (hard pool ≥ 0.85, W ≤ 0.02, L = 0 — no undisclosed secret name of the fixtures in the cards or the outputs — plus the escalation rate and the cost per turn against their targets).
- **Re-evaluation is mandatory** for any change to the identity prompt (`prompts/identity_prompt.py`, the pack examples it renders), the blocking (`services/identity/candidates.py`, the `IdentityConfig` values) or a model of the `identity` / `identity_strong` roles: re-run the v2 adapter on dev (and, for a gate decision, the test split once) and put the numbers in the PR. A change to the blocking also re-runs `tests/identity/test_candidates.py::test_blocking_recall_of_the_turn_set_on_the_whole_corpus`.

Re-evaluate on dev while working; run the test split only for a gate decision (choose on dev, read test once):

```bash
scripts/eval-identity.sh --adapter legacy --split dev --sequences --runs 3 --provider anthropic
scripts/eval-identity.sh --adapter legacy --split test --runs 3 --provider anthropic --gate   # exit 1 if the gate fails
EVAL_IO=/tmp/identity scripts/eval-identity.sh --adapter legacy --split dev --sequences --emit-prompts /io/dev
EVAL_IO=/tmp/identity scripts/eval-identity.sh --adapter legacy --split dev --sequences --import-responses /io/dev --responder subagent:claude-sonnet
scripts/eval-identity.sh --adapter v2 --split dev --runs 1 --provider anthropic
scripts/eval-identity.sh --adapter v2 --split test --runs 3 --provider anthropic --milestone pr2 --gate
EVAL_IO=/tmp/identity scripts/eval-identity.sh --adapter v2 --split dev --emit-prompts /io/dev
EVAL_IO=/tmp/identity scripts/eval-identity.sh --adapter v2 --split dev --import-responses /io/dev --responder subagent:claude-haiku+claude-sonnet --milestone pr2   # repeat until nothing is pending
```

The reference numbers are the baseline of the legacy resolver: `tests/reports/identity/2026-10-19-baseline-{test,dev}-anthropic-claude-sonnet-5-5-subagent.md`, and the PR 2 gate of the resolver v2: **[GATE REPORT: to be filled, `tests/reports/identity/<date>-pr2-gate-anthropic-haiku-sonnet.md`]**. Flags and details: `backend/scripts/README.md`.

## Architecture rules and lint

`backend/tests/test_architecture.py` enforces the dependency rule (`domain` imports no other layer; `workers` imports none of `api`, `pipeline`, `services`, `repos`, `kg`, `llm`, `schema`, `prompts`, nor asyncpg/FastAPI; `pipeline` never imports `api`; `services`, `repos`, `kg`, `llm`, `schema` and `prompts` import neither `api` nor `pipeline`; no SQL in `api/routes.py`) and that `_handle_chat` stays under 80 lines. A violation fails the suite, so add new code in the right layer rather than editing the test.

A violation is judged against two frozen lists in `backend/tests/test_architecture.py`, which may only shrink: `KNOWN_VIOLATIONS` (pairs of file and full imported module that still break a layer rule; a new import in a listed file is a new violation, and a fixed entry must be removed, the suite fails otherwise) and `SQL_IN_API_ALLOWED` (the `api/` files that still hold SQL; no SQL is allowed in any other `api/` file). The architecture tests also forbid `repos/turns.py` from importing `kg` or `services`, and the layer rules forbid `api/` from importing `main`: the pool is read with `api.dependencies.get_pool`. Turn effects live in `services/turn_effects.py`, identity value types in `domain/identity.py` and the JSON coercion validators in `schema/coerce.py`.

Every route that takes a game id (any spelling of `game_id`/`gameId` in path, query, header or body, nested fields included, or any path parameter right under `/games/`) must call `GameService.verify_ownership` before touching the game, and take the id from one place only. `backend/tests/test_game_ownership_guard.py` discovers these routes from the OpenAPI schema and fails until a new one is added to its `GAME_SCOPED_CALLS` table, which then checks that another user gets a 403 and that the game (existence, name, messages) is unchanged. Routes must not use `include_in_schema=False` (the same test fails on a hidden route).

The whole backend (tests excluded, see #75) is linted for complexity (McCabe 15 at most), unused imports and unused variables (C901, F401, F841), and for stale `noqa` comments (RUF100). `backend/ruff.toml` is the reference and CI runs `ruff check .` from `backend/` (ruff 0.8.4). The functions above 15 are frozen debt, each marked on its `def` line with `# noqa: C901 - <task>, ...`: because of RUF100, a `noqa` whose function drops to 15 or below fails the lint until you remove it, so the list can only shrink; never add one, and a new function over 15 fails.

```bash
cd backend && pip install ruff==0.8.4
ruff check .
```

The CI test step fails under 91% coverage (`--cov-fail-under=91`); raise the floor when coverage rises, never lower it to get a change through.

Errors reaching the player come from `pipeline/errors.py` (one French message, a `code`, a `ref`); never send raw exception text, and use `logger.exception` rather than `traceback.print_exc`. Prompts are logged only with `LOG_PROMPTS=true`.

## Deployment

Coolify deploys `docker-compose.yml` alone (no override). Environment to set in Coolify:

- `JWT_SECRET` (required): 32+ random characters (`openssl rand -hex 32`). Missing: the deploy fails; weak or published: the backend refuses to start. Changing it logs every player out.
- `DB_PASSWORD` (required): must be the password the existing `pgdata` volume was created with. Postgres only reads it when the volume is first initialised; if Coolify never set it, production has been running with the old default `ldvelh`, so set exactly that (or first change the password in Postgres with `ALTER USER ldvelh PASSWORD '...'`, then update the variable). It is interpolated into `DATABASE_URL`, so use URL-safe characters only (letters, digits, `-`, `_`, `.`, `~`; `openssl rand -hex 24` fits).
- `ENCRYPTION_KEY` (required): a Fernet key. Players' saved API keys are encrypted with it: once set, never change or lose it, or those keys become unreadable (players must enter them again).
- `SERVICE_URL_FRONTEND` (Coolify magic variable), `CORS_ORIGINS` (the production origin), `NEXT_PUBLIC_API_URL` (build arg: set it empty for same-origin `/api`, or to the backend URL; unset falls back to `http://localhost:8000`).
- `TRUSTED_PROXY_HOPS`: number of reverse proxies between the internet and the backend; the compose default `1` fits Coolify (one Traefik). Never set it above the real count: the extra entry is client-supplied, so a client could choose its rate-limit key (a chosen entry that is not an IP address falls back to the TCP peer). Too low (`0` behind Traefik) puts every player behind Traefik's address, so one player's failed logins throttle everyone. Behind Cloudflare in proxy mode, use `2`, but only after making Traefik trust the Cloudflare ranges (Coolify proxy configuration: `--entryPoints.https.forwardedHeaders.trustedIPs=<Cloudflare IPv4/IPv6 ranges>`, and the same for `http`): without it Traefik discards the `X-Forwarded-For` Cloudflare sends, the header holds only Cloudflare's address and every player shares it. The backend port must stay unpublished, so that only the proxy reaches it.
- `IDENTITY_BACKFILL_EXCEPTIONS` (optional): path, inside the backend container, of the owner-reviewed YAML corrections of the identity dry-run report (see "Deploying the identity migration"); applied once at boot by `scripts.identity_backfill`.
- Optional: `SUPERVISOR_MAX_GAMES`, `SUPERVISOR_DRAIN_TIMEOUT`, `SUPERVISOR_CANCEL_TIMEOUT`, `ROLLBACK_ENGINE` (see the table above; an invalid value stops the start with an error naming the variable), `RESEND_API_KEY`, `EMAIL_FROM`, `REGISTRATION_ENABLED`, `JWT_SESSION_MAX_HOURS` (default 720: players log in again every 30 days).
- Single worker: the backend runs one uvicorn process (in-process game locks and task supervisor). Do not set `WEB_CONCURRENCY` or `UVICORN_WORKERS` above 1: the backend refuses to start. `stop_grace_period: 30s` in the compose file gives the shutdown drain of background jobs (`supervisor_drain_timeout`) time to finish before the container is killed: keep `SUPERVISOR_DRAIN_TIMEOUT` (default 20 s) plus the 5 s cancel grace under it.
- Database timeouts: every pooled connection sets `idle_in_transaction_session_timeout` to 30 s and `statement_timeout` to 60 s (`POOL_SERVER_SETTINGS` in `main.py`).
- Leave `DEBUG` unset (`false`), and do not set `DEV_USER_*`.

Images: both run as an unprivileged user (backend `app`, uid 10001; frontend `node`, uid 1000). dbmate is pinned in one place, `db/dbmate-release.env` (version and the SHA-256 of the linux amd64 and arm64 binaries, from the GitHub release asset digests), and installed by `db/install-dbmate.sh` (download + `sha256sum -c`) in the backend image (`TARGETARCH`), CI and `scripts/test-backend.sh`: to upgrade, change that file only. `serve` comes from its own minimal manifest, `frontend/runtime/package.json` + committed `package-lock.json` (`npm ci --omit=dev` in the runner stage: serve and all its dependencies lock-pinned, without next/react); that manifest is the image's source of truth, and `tests/runtimeServe.test.mjs` checks the main lockfile (used by e2e and `npm start`) resolves the same version. To upgrade serve: change `runtime/package.json`, run `npm install --package-lock-only` in `frontend/runtime/`, and update the main `package.json`/lockfile to match. The backend image is built from the repo root: `/.dockerignore` keeps `.env` files, `backend/tests`, caches and the frontend out of it; it sets `PYTHONDONTWRITEBYTECODE=1` (the code is read-only for `app`). The backend has a compose healthcheck on `GET /health` (`docker compose ps` shows `healthy`; 30 s start period for the migrations run at boot).

### Before a data migration

Take a backup before deploying a migration that changes data (not required for purely additive DDL such as an empty table, a column or triggers, which the P5a migrations are; recommended before any migration touching many tables; **required** for `20261020000001_entity_identity.sql`, which rewrites ids and the journal: follow "Deploying the identity migration" below):

```bash
docker compose exec -T db pg_dump -U ldvelh -Fc ldvelh > ldvelh-$(date +%F).dump
```

To go back, restore it over the database (the backend stopped; `-T` is needed so the binary dump is not altered by a TTY):

```bash
docker compose exec -T db pg_restore -U ldvelh -d ldvelh --clean --if-exists < ldvelh-<date>.dump
```

`*.dump` files are git-ignored: keep them out of the repository. dbmate never runs from the host against a real database; migrations run at backend boot inside the container.

### Deploying the identity migration (#152, D28)

The identity migration (`20261020000001_entity_identity.sql`) transforms existing data and cannot be undone by a turn rollback. At boot the backend entrypoint runs `scripts.sync_lang_packs`, then `dbmate up`, then `scripts.identity_backfill`, which gives the old games their language and norms, classifies their unknown characters, rebuilds mentions and applies `IDENTITY_BACKFILL_EXCEPTIONS`. The startup check refuses to serve while a name has no norm, so a failed backfill keeps the backend down (fail-closed): the migration has already committed by then. Pushing the branch Coolify deploys starts all of this, so go through these steps first:

1. **Backup** the production database (`pg_dump -Fc`, see "Before a data migration").
2. **Restore it into a throwaway Postgres 18** (a local container, never the production server), e.g. `docker run -d --name restore -e POSTGRES_PASSWORD=x -p 55432:5432 postgres:18`, then `pg_restore -d postgres://postgres:x@localhost:55432/postgres --no-owner < ldvelh-<date>.dump`.
3. **Dry-run report** on the restored copy, before any migration, from a checkout of the branch (`backend/`): `DATABASE_URL=… python -m scripts.identity_migration_report --out report.md`. It only reads: re-identification, orphans (and the journal rows they take along), classification of the unknown characters, proposed secrets, secret facts, dropped mentions (with the reason: unresolved, ambiguous, or no entity of that type), suspected duplicates (never merged), normalised collisions. To read production directly instead, use a read-only session through a tunnel, never the new image: its entrypoint migrates on start (`docker run --entrypoint python …` if you must use the image).
4. **Full rehearsal** on the copy: `python -m scripts.sync_lang_packs`, `dbmate --migrations-dir ../db/migrations up` (in one transaction, as at boot; replaying section 3 by hand needs `psql -1`), then `time python -m scripts.identity_backfill`, then `psql -f scripts/identity_invariants.sql`: every count must be 0. Run the backfill and section 3 again: nothing may change. Compare the backfill time with the compose healthcheck start period (30 s): the migration and the backfill run before uvicorn listens.
5. **Owner review**: the game owner reads the report and writes the corrections, `{character id: {true_name: …}}` or `{character id: {descriptor: …}}`, in a YAML file. Rerun step 4 with `--exceptions file.yaml` and check the invariants again.
6. **Deploy**: put the YAML file where the backend container can read it (a mounted file), set `IDENTITY_BACKFILL_EXCEPTIONS` to its path, then push. Watch the boot log: `[IDENTITY_BACKFILL] game=<id> {...}` per game, then `[STARTUP]`. A missing or malformed exceptions file stops the boot with one `[IDENTITY_BACKFILL] cannot read the exceptions file …` line. If it fails, restore the backup (step 1) and redeploy the previous image.

Each correction is applied once (an `identity_events` row records it), so leaving the variable set never undoes what the game did since. A correction `true_name: X` drops the character's descriptor when its normalised words contain X's: the classification's copy of a name nobody saw, but also a descriptor the player did see (« Le vieux Marn au chapeau » for `true_name: Marn`). The player then reads the pack's unknown label, never X.

Rollback: the backup restore of step 1 is the only way back. The migration's `-- migrate:down` restores the schema only: the journal rows keep the new column names (characters rows without `unknown_name`, objects rows without `canonical_name`), so an undo after a `down` would lose those columns.

After the #83 deploy every player is logged out once (tokens without `ver`/`orig_iat` are refused).

One-off check after this change (manual): debug mode used to seed `dev@ldvelh.local` with a known password. Make sure that account does not exist in the production database (`SELECT id FROM users WHERE email = 'dev@ldvelh.local';`) and delete it if it does.

### Merging duplicates (#153)

Two entities that are the same (for example a place or an NPC the resolver created twice) are merged by hand with `backend/scripts/merge_entities.py`. A merge moves every edge to the kept entity and cannot be undone by a turn rollback, so:

1. **Backup first** (`pg_dump -Fc`, see "Before a data migration").
2. Find the two handles (`E<n>`, shown in the tooltips and the prompts) or ids. Keep the older, better-named one.
3. From `backend/`, with the production database reached through a tunnel or a restored copy. Pass the URL through an environment variable, not the command line (a URL on the command line shows in `ps` and the shell history): `MERGE_DB_URL=… python -m scripts.merge_entities --database-url-env MERGE_DB_URL --game GAME_UUID --keep E12 --drop E31 --reason "same person"`. One of `--database-url` or `--database-url-env` is required; the script reads no other variable.
4. Read the two cards and the edges that will move (every edge the SQL merge moves, counted by running it in a rolled-back savepoint), and the engine rows of DROP (stat blocks) that KEEP's own replace: KEEP's block wins, DROP's is kept only as a copy in `entity_merges.dropped_row` (key `engine`). Then answer `y`. Any other answer changes nothing. `--yes` skips the question for a scripted run.
5. The script prints the `entity_merges` id, or the refusal code (`both_mandatory`, `reserved_type`, `type_mismatch`, `same_entity`, `already_merged`, `missing`). When the guards refuse, the script says so and exits without asking and without writing anything.

To undo a merge, restore the backup.

## CI

GitHub Actions runs on every push to `main`/`dev`/`test`:
- **Unit tests** with coverage (uploaded to Codecov)
- **Integration tests** against a Postgres service container
- **Lint** of the backend with `ruff check .` (C901, F401, F841; config in `backend/ruff.toml`)
- **Frontend**: lint, unit tests, build, then the Playwright e2e tests (results uploaded as the `e2e-results` artifact)
- **Docker images**: `docker build` of the backend (repo root context) and the frontend, run as non-root
