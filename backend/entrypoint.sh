#!/bin/sh
set -e

echo "→ Running database migrations..."
dbmate --migrations-dir /app/db/migrations --no-dump-schema --wait up

echo "→ Starting app..."
# One worker only: game locks and the task supervisor live in this process (see CONTRIBUTING, Deployment).
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
