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
└── main.py

frontend/
├── app/            # Next.js pages
├── components/     # React components
├── hooks/          # Custom hooks
└── lib/            # API client, game logic

schema.sql          # PostgreSQL schema
```

## Setup

### Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env  # Configure DATABASE_URL, API keys
uvicorn main:app --reload
```

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
| `JWT_SECRET` | JWT signing key | dev default |
| `ENCRYPTION_KEY` | Fernet key for stored API keys | — |
| `REGISTRATION_ENABLED` | Enable/disable registration | `true` |
| `DEBUG` | Debug mode (seeds dev user) | `false` |
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

`pipeline/` and `api/routes.py` are also linted for complexity (McCabe 15 at most) and unused imports, with the same command as CI (ruff 0.8.4):

```bash
cd backend && pip install ruff==0.8.4
ruff check --select C901,F401 --config "lint.mccabe.max-complexity = 15" pipeline/ api/routes.py
```

Errors reaching the player come from `pipeline/errors.py` (one French message, a `code`, a `ref`); never send raw exception text, and use `logger.exception` rather than `traceback.print_exc`. Prompts are logged only with `LOG_PROMPTS=true`.

## CI

GitHub Actions runs on every push to `main`/`dev`/`test`:
- **Unit tests** with coverage (uploaded to Codecov)
- **Integration tests** against a Postgres service container
- **Lint** of `pipeline/` and `api/routes.py` (ruff C901, F401)
- **Frontend**: lint, unit tests, build, then the Playwright e2e tests (results uploaded as the `e2e-results` artifact)
