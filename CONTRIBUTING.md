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
├── api/            # FastAPI routes (auth, game, chat)
├── kg/             # Knowledge graph (populator, reader)
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
| `CORS_ORIGINS` | Allowed origins | `http://localhost:3000` |

## Testing

```bash
cd backend

# Unit tests (no DB needed)
pytest tests/ -m "not integration" -q

# Integration tests (requires ldvelh_test database)
pytest tests/ -m integration -q

# With coverage
pytest tests/ -m "not integration" --cov=. --cov-branch -q
```

## CI

GitHub Actions runs on every push to `main`/`dev`/`test`:
- **Unit tests** with coverage (uploaded to Codecov)
- **Integration tests** against a Postgres 16 service container
