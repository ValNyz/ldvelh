#!/bin/sh
set -e

echo "→ Synchronising the language packs..."
# Before the migrations: the identity migration's data section reads lang_packs (#152).
dbmate wait
python -m scripts.sync_lang_packs

echo "→ Running database migrations..."
dbmate --migrations-dir /app/db/migrations --no-dump-schema --wait up

echo "→ Backfilling entity identities..."
# Games written before the identity migration (no language, names without norm): the
# startup check refuses to serve until this ran. Idempotent; nothing to do afterwards.
# IDENTITY_BACKFILL_EXCEPTIONS: the owner-reviewed corrections of the dry-run report
# (YAML path), applied once (CONTRIBUTING, "Deploying the identity migration").
python -m scripts.identity_backfill

echo "→ Starting app..."
# One worker only: game locks and the task supervisor live in this process (see CONTRIBUTING, Deployment).
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
