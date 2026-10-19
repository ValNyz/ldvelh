#!/usr/bin/env bash
# Run the identity evaluation (backend/scripts/eval_identity.py) in Docker.
# Usage: scripts/eval-identity.sh ARGS...   e.g. --adapter legacy --split test --runs 1 --provider anthropic
#
# - The repo is mounted read-only and copied inside the container.
# - The report is written to EVAL_OUT (host dir, default backend/tests/reports/identity), the
#   only directory written besides EVAL_IO for --emit-prompts.
# - EVAL_IO (host dir, no default) is mounted at /io for --emit-prompts / --import-responses:
#   pass those directories as /io/<path>. It is writable only with --emit-prompts.
# - The script runs as the host user: files it writes are the user's, nothing is chowned.
# - The host's provider keys reach only the final python command, never apt, dbmate or pip.
# - A throwaway Postgres (TEST_DATABASE_URL) is started only for adapters that read the
#   database; the legacy adapter does not.
set -euo pipefail

REPO="$(git rev-parse --show-toplevel)"
OUT="${EVAL_OUT:-$REPO/backend/tests/reports/identity}"
SUFFIX="$$"
PG="ldvelh-eval-pg-${SUFFIX}"
NET="ldvelh-eval-${SUFFIX}"
mkdir -p "$OUT"

adapter=legacy
io_mode=ro
prev=""
for arg in "$@"; do
  [ "$prev" = "--adapter" ] && adapter="$arg"
  case "$arg" in
    --adapter=*) adapter="${arg#--adapter=}" ;;
    --emit-prompts|--emit-prompts=*) io_mode=rw ;;
  esac
  prev="$arg"
done

IO_ARGS=()
if [ -n "${EVAL_IO:-}" ]; then
  mkdir -p "$EVAL_IO"
  IO_ARGS=(-v "$(cd "$EVAL_IO" && pwd)":/io:"$io_mode")
fi

cleanup() {
  docker rm -f "$PG" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "$NET" >/dev/null
DB_URL=""
if [ "$adapter" != "legacy" ]; then
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
  DB_URL="postgresql://test:test@${PG}:5432/ldvelh_test"
fi

docker run --rm --network "$NET" -e DB_URL="$DB_URL" -e HOST_IDS="$(id -u):$(id -g)" \
  -e ANTHROPIC_API_KEY -e MISTRAL_API_KEY -e WANDB_API_KEY -e NEBIUS_API_KEY -e NOUS_API_KEY \
  -v "$REPO":/src:ro -v "$OUT":/out ${IO_ARGS[@]+"${IO_ARGS[@]}"} python:3.13-slim bash -c '
set -euo pipefail
# Keep the keys out of the environment of every setup step.
KEYS="$(env | grep -E "^(ANTHROPIC|MISTRAL|WANDB|NEBIUS|NOUS)_API_KEY=." || true)"
unset ANTHROPIC_API_KEY MISTRAL_API_KEY WANDB_API_KEY NEBIUS_API_KEY NOUS_API_KEY
mkdir /w && tar -C /src --exclude=.git --exclude=node_modules -cf - . | tar -C /w -xf -
cd /w/backend
pip install -q --root-user-action=ignore -r requirements.txt
export JWT_SECRET="$(python -c "import secrets; print(secrets.token_hex(32))")"
export ENCRYPTION_KEY="$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")"
if [ -n "$DB_URL" ]; then
  apt-get update -qq >/dev/null && apt-get install -y -qq curl >/dev/null
  /w/db/install-dbmate.sh /w/db/dbmate-release.env /usr/local/bin/dbmate
  DATABASE_URL="${DB_URL}?sslmode=disable" \
    dbmate --migrations-dir ../db/migrations --no-dump-schema up >/dev/null
  export DATABASE_URL="$DB_URL" TEST_DATABASE_URL="$DB_URL"
fi
while IFS= read -r line; do [ -n "$line" ] && export "$line"; done <<<"$KEYS"
export HOME=/tmp PYTHONDONTWRITEBYTECODE=1
exec setpriv --reuid="${HOST_IDS%:*}" --regid="${HOST_IDS#*:}" --clear-groups \
  python -m scripts.eval_identity --out /out "$@"
' _ "$@"
