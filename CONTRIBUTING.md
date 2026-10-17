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
├── pipeline/       # Turn pipeline: steps/{load,arbitrate,narrate,commit,respond,schedule}, init_flow
├── repos/          # SQL (games, turns, users, llm_models)
├── prompts/        # LLM prompt templates
├── schema/         # Pydantic models
├── services/       # Business logic (game, LLM, extraction, auth)
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

`docker-compose.yml` is the production file (deployed by Coolify) and is fail-closed: without `JWT_SECRET` or `DB_PASSWORD`, `docker compose` stops with `required variable JWT_SECRET is missing a value`, and `DEBUG` defaults to `false`. Everything that only makes sense locally lives in `docker-compose.override.yml`, which `docker compose up` applies automatically: published ports, `DEBUG=true` and the dev user (`dev@ldvelh.local` / `devpassword`, seeded in debug mode only).

That override is git-ignored and created from the committed `docker-compose.override.example.yml`, so a server that runs a plain `docker compose up` on a fresh clone never gets debug mode or the dev account by accident. `scripts/dev-setup.sh` is safe to re-run: it keeps an existing override and existing values in `.env`, and only fills `JWT_SECRET` (when empty, shorter than 32 characters or a `change-me` placeholder), `ENCRYPTION_KEY` and `DB_PASSWORD` (`ldvelh`, the password of existing local `pgdata` volumes). After pulling this change, run it once: the tracked `docker-compose.override.yml` is replaced by your own copy.

### Backend

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example .env  # set DATABASE_URL, a random JWT_SECRET (openssl rand -hex 32), API keys
uvicorn main:app --reload
```

The backend refuses to start when `JWT_SECRET` is shorter than 32 characters, contains `change-me` or is a published default, whatever `DEBUG` says, and when `ENCRYPTION_KEY` is empty outside debug mode (`backend/startup_checks.py`).

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
| `JWT_SECRET` | JWT signing key, required: 32+ random characters, no `change-me`, not a published default (checked at startup, even in debug) | — |
| `ENCRYPTION_KEY` | Fernet key for stored API keys, required at startup unless `DEBUG=true` | — |
| `DB_PASSWORD` | Postgres password, required by `docker-compose.yml` | — |
| `REGISTRATION_ENABLED` | Enable/disable registration | `true` |
| `DEBUG` | Debug mode (seeds dev user, streams debug payloads): local only, set by `docker-compose.override.yml` | `false` |
| `DEV_USER_EMAIL` / `DEV_USER_PASSWORD` | Dev account seeded in debug mode | `dev@ldvelh.local` / `devpassword` |
| `LOG_PROMPTS` | Log narrator prompts and JSON (DEBUG level) | `false` |
| `CORS_ORIGINS` | Allowed origins | `http://localhost:3000` |

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

`backend/tests/test_architecture.py` enforces the dependency rule (`domain` imports no other layer; `pipeline` never imports `api`; `services`, `repos`, `kg`, `llm`, `schema` and `prompts` import neither `api` nor `pipeline`; no SQL in `api/routes.py`) and that `_handle_chat` stays under 80 lines. A violation fails the suite, so add new code in the right layer rather than editing the test.

Every route that takes a game id (`gameId` / `game_id` in path, query or body) must call `GameService.verify_ownership` before touching the game. `backend/tests/test_game_ownership_guard.py` discovers these routes from the OpenAPI schema and fails until a new one is added to its `GAME_SCOPED_CALLS` table, which then checks that another user gets a 403.

`pipeline/` and `api/routes.py` are also linted for complexity (McCabe 15 at most) and unused imports, with the same command as CI (ruff 0.8.4):

```bash
cd backend && pip install ruff==0.8.4
ruff check --select C901,F401 --config "lint.mccabe.max-complexity = 15" pipeline/ api/routes.py
```

Errors reaching the player come from `pipeline/errors.py` (one French message, a `code`, a `ref`); never send raw exception text, and use `logger.exception` rather than `traceback.print_exc`. Prompts are logged only with `LOG_PROMPTS=true`.

## Deployment

Coolify deploys `docker-compose.yml` alone (no override). Set at least `JWT_SECRET`, `DB_PASSWORD` and `ENCRYPTION_KEY` in its environment: a missing `JWT_SECRET` or `DB_PASSWORD` fails the deploy, and a weak `JWT_SECRET` or missing `ENCRYPTION_KEY` stops the backend at startup. Leave `DEBUG` unset (`false`).

## CI

GitHub Actions runs on every push to `main`/`dev`/`test`:
- **Unit tests** with coverage (uploaded to Codecov)
- **Integration tests** against a Postgres service container
- **Lint** of `pipeline/` and `api/routes.py` (ruff C901, F401)
- **Frontend**: lint, unit tests, build, then the Playwright e2e tests (results uploaded as the `e2e-results` artifact)
