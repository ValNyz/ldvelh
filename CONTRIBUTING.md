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
├── domain/         # Pure types (turn, errors, game), no I/O
├── kg/             # Knowledge graph (populator, reader)
├── pipeline/       # Turn pipeline: steps/{load,arbitrate,narrate,commit,respond,schedule}, init_flow, post_turn
├── workers/        # Per-game job supervisor and turn locks (in-process, imports no other layer)
├── repos/          # SQL (games, turns, users, llm_models)
├── prompts/        # LLM prompt templates
├── schema/         # Pydantic models
├── services/       # Business logic (game, LLM, extraction, auth, post-turn hooks and subscribers, Director)
├── tests/          # Unit + integration tests (700+)
├── startup_checks.py  # Secrets validation run before startup (JWT_SECRET, ENCRYPTION_KEY)
└── main.py

frontend/
├── app/            # Next.js pages
├── components/     # React components
├── hooks/          # Custom hooks
└── lib/            # API client, game logic

schema.sql          # PostgreSQL schema
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

```bash
psql -U your_user -d your_db -f schema.sql
```

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

## Architecture rules and lint

`backend/tests/test_architecture.py` enforces the dependency rule (`domain` imports no other layer; `workers` imports none of `api`, `pipeline`, `services`, `repos`, `kg`, `llm`, `schema`, `prompts`, nor asyncpg/FastAPI; `pipeline` never imports `api`; `services`, `repos`, `kg`, `llm`, `schema` and `prompts` import neither `api` nor `pipeline`; no SQL in `api/routes.py`) and that `_handle_chat` stays under 80 lines. A violation fails the suite, so add new code in the right layer rather than editing the test.

Every route that takes a game id (any spelling of `game_id`/`gameId` in path, query, header or body, nested fields included, or any path parameter right under `/games/`) must call `GameService.verify_ownership` before touching the game, and take the id from one place only. `backend/tests/test_game_ownership_guard.py` discovers these routes from the OpenAPI schema and fails until a new one is added to its `GAME_SCOPED_CALLS` table, which then checks that another user gets a 403 and that the game (existence, name, messages) is unchanged. Routes must not use `include_in_schema=False` (the same test fails on a hidden route).

`pipeline/`, `api/routes.py` and `workers/` are also linted for complexity (McCabe 15 at most) and unused imports, with the same command as CI (ruff 0.8.4):

```bash
cd backend && pip install ruff==0.8.4
ruff check --select C901,F401 --config "lint.mccabe.max-complexity = 15" pipeline/ api/routes.py workers/
```

Errors reaching the player come from `pipeline/errors.py` (one French message, a `code`, a `ref`); never send raw exception text, and use `logger.exception` rather than `traceback.print_exc`. Prompts are logged only with `LOG_PROMPTS=true`.

## Deployment

Coolify deploys `docker-compose.yml` alone (no override). Environment to set in Coolify:

- `JWT_SECRET` (required): 32+ random characters (`openssl rand -hex 32`). Missing: the deploy fails; weak or published: the backend refuses to start. Changing it logs every player out.
- `DB_PASSWORD` (required): must be the password the existing `pgdata` volume was created with. Postgres only reads it when the volume is first initialised; if Coolify never set it, production has been running with the old default `ldvelh`, so set exactly that (or first change the password in Postgres with `ALTER USER ldvelh PASSWORD '...'`, then update the variable). It is interpolated into `DATABASE_URL`, so use URL-safe characters only (letters, digits, `-`, `_`, `.`, `~`; `openssl rand -hex 24` fits).
- `ENCRYPTION_KEY` (required): a Fernet key. Players' saved API keys are encrypted with it: once set, never change or lose it, or those keys become unreadable (players must enter them again).
- `SERVICE_URL_FRONTEND` (Coolify magic variable), `CORS_ORIGINS` (the production origin), `NEXT_PUBLIC_API_URL` (build arg: set it empty for same-origin `/api`, or to the backend URL; unset falls back to `http://localhost:8000`).
- `TRUSTED_PROXY_HOPS`: number of reverse proxies between the internet and the backend; the compose default `1` fits Coolify (one Traefik). Never set it above the real count: the extra entry is client-supplied, so a client could choose its rate-limit key (a chosen entry that is not an IP address falls back to the TCP peer). Too low (`0` behind Traefik) puts every player behind Traefik's address, so one player's failed logins throttle everyone. Behind Cloudflare in proxy mode, use `2`, but only after making Traefik trust the Cloudflare ranges (Coolify proxy configuration: `--entryPoints.https.forwardedHeaders.trustedIPs=<Cloudflare IPv4/IPv6 ranges>`, and the same for `http`): without it Traefik discards the `X-Forwarded-For` Cloudflare sends, the header holds only Cloudflare's address and every player shares it. The backend port must stay unpublished, so that only the proxy reaches it.
- Optional: `SUPERVISOR_MAX_GAMES`, `SUPERVISOR_DRAIN_TIMEOUT`, `SUPERVISOR_CANCEL_TIMEOUT` (see the table above; an invalid value stops the start with an error naming the variable), `RESEND_API_KEY`, `EMAIL_FROM`, `REGISTRATION_ENABLED`, `JWT_SESSION_MAX_HOURS` (default 720: players log in again every 30 days).
- Single worker: the backend runs one uvicorn process (in-process game locks and task supervisor). Do not set `WEB_CONCURRENCY` or `UVICORN_WORKERS` above 1: the backend refuses to start. `stop_grace_period: 30s` in the compose file gives the shutdown drain of background jobs (`supervisor_drain_timeout`) time to finish before the container is killed: keep `SUPERVISOR_DRAIN_TIMEOUT` (default 20 s) plus the 5 s cancel grace under it.
- Database timeouts: every pooled connection sets `idle_in_transaction_session_timeout` to 30 s and `statement_timeout` to 60 s (`POOL_SERVER_SETTINGS` in `main.py`).
- Leave `DEBUG` unset (`false`), and do not set `DEV_USER_*`.

Images: both run as an unprivileged user (backend `app`, uid 10001; frontend `node`, uid 1000). dbmate is pinned in one place, `db/dbmate-release.env` (version and the SHA-256 of the linux amd64 and arm64 binaries, from the GitHub release asset digests), and installed by `db/install-dbmate.sh` (download + `sha256sum -c`) in the backend image (`TARGETARCH`), CI and `scripts/test-backend.sh`: to upgrade, change that file only. `serve` comes from its own minimal manifest, `frontend/runtime/package.json` + committed `package-lock.json` (`npm ci --omit=dev` in the runner stage: serve and all its dependencies lock-pinned, without next/react); that manifest is the image's source of truth, and `tests/runtimeServe.test.mjs` checks the main lockfile (used by e2e and `npm start`) resolves the same version. To upgrade serve: change `runtime/package.json`, run `npm install --package-lock-only` in `frontend/runtime/`, and update the main `package.json`/lockfile to match. The backend image is built from the repo root: `/.dockerignore` keeps `.env` files, `backend/tests`, caches and the frontend out of it; it sets `PYTHONDONTWRITEBYTECODE=1` (the code is read-only for `app`). The backend has a compose healthcheck on `GET /health` (`docker compose ps` shows `healthy`; 30 s start period for the migrations run at boot).

### Before a data migration

Take a backup before deploying a migration that changes data (not needed for one that only adds an empty table or column):

```bash
docker compose exec -T db pg_dump -U ldvelh -Fc ldvelh > ldvelh-$(date +%F).dump
```

To go back, restore it over the database (the backend stopped; `-T` is needed so the binary dump is not altered by a TTY):

```bash
docker compose exec -T db pg_restore -U ldvelh -d ldvelh --clean --if-exists < ldvelh-<date>.dump
```

`*.dump` files are git-ignored: keep them out of the repository. dbmate never runs from the host against a real database; migrations run at backend boot inside the container.

After the #83 deploy every player is logged out once (tokens without `ver`/`orig_iat` are refused).

One-off check after this change (manual): debug mode used to seed `dev@ldvelh.local` with a known password. Make sure that account does not exist in the production database (`SELECT id FROM users WHERE email = 'dev@ldvelh.local';`) and delete it if it does.

## CI

GitHub Actions runs on every push to `main`/`dev`/`test`:
- **Unit tests** with coverage (uploaded to Codecov)
- **Integration tests** against a Postgres service container
- **Lint** of `pipeline/`, `api/routes.py` and `workers/` (ruff C901, F401)
- **Frontend**: lint, unit tests, build, then the Playwright e2e tests (results uploaded as the `e2e-results` artifact)
- **Docker images**: `docker build` of the backend (repo root context) and the frontend, run as non-root
