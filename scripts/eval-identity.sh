#!/usr/bin/env bash
# Run the identity evaluation (backend/scripts/eval_identity.py) in Docker, like test-backend.sh:
# a throwaway Postgres (TEST_DATABASE_URL, read from the v2 adapter on), the repo mounted
# read-only, the host's API keys passed through.
# Usage: scripts/eval-identity.sh ARGS...   e.g. --adapter legacy --split test --runs 1 --provider anthropic
# The report goes to backend/tests/reports/identity/ (EVAL_OUT=host dir to change it). The
# directories of --emit-prompts / --import-responses are read relative to EVAL_IO (host dir,
# mounted at /io; default: the current directory): pass them as /io/<path>.
set -euo pipefail

REPO="$(git rev-parse --show-toplevel)"
OUT="${EVAL_OUT:-$REPO/backend/tests/reports/identity}"
IO="${EVAL_IO:-$PWD}"
SUFFIX="$$"
PG="ldvelh-eval-pg-${SUFFIX}"
NET="ldvelh-eval-${SUFFIX}"
mkdir -p "$OUT"

cleanup() {
  docker rm -f "$PG" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "$NET" >/dev/null
docker run -d --rm --name "$PG" --network "$NET" \
  -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=ldvelh_test \
  postgres:18 -c fsync=off >/dev/null
ready=0
for _ in $(seq 1 60); do
  if docker exec "$PG" pg_isready -U test >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then echo "Postgres not ready after 60s" >&2; exit 1; fi
sleep 2

docker run --rm --network "$NET" -e PG_HOST="$PG" -e HOST_IDS="$(id -u):$(id -g)" \
  -e ANTHROPIC_API_KEY -e MISTRAL_API_KEY -e WANDB_API_KEY -e NEBIUS_API_KEY -e NOUS_API_KEY \
  -v "$REPO":/src:ro -v "$OUT":/out -v "$IO":/io python:3.13-slim bash -c '
set -euo pipefail
mkdir /w && tar -C /src --exclude=.git --exclude=node_modules -cf - . | tar -C /w -xf -
cd /w/backend
apt-get update -qq >/dev/null && apt-get install -y -qq curl >/dev/null
/w/db/install-dbmate.sh /w/db/dbmate-release.env /usr/local/bin/dbmate
pip install -q -r requirements.txt
DATABASE_URL="postgresql://test:test@${PG_HOST}:5432/ldvelh_test?sslmode=disable" \
  dbmate --migrations-dir ../db/migrations --no-dump-schema up >/dev/null
export DATABASE_URL="postgresql://test:test@${PG_HOST}:5432/ldvelh_test"
export TEST_DATABASE_URL="$DATABASE_URL"
export JWT_SECRET="$(python -c "import secrets; print(secrets.token_hex(32))")"
export ENCRYPTION_KEY="$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")"
status=0
python -m scripts.eval_identity --out /out "$@" || status=$?
chown -R "$HOST_IDS" /out /io 2>/dev/null || true
exit $status
' _ "$@"
