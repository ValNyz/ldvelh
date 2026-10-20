#!/usr/bin/env bash
# Run the identity evaluation (backend/scripts/eval_identity.py) in Docker.
# Usage: scripts/eval-identity.sh ARGS...   e.g. --adapter legacy --split test --runs 1 --provider anthropic
#
# - The repo is mounted read-only and copied inside the container.
# - The report is written to EVAL_OUT (host dir, default backend/tests/reports/identity), the
#   only directory written besides EVAL_IO.
# - EVAL_IO (host dir, no default) is mounted at /io for --emit-prompts / --import-responses:
#   pass those directories as /io/<path>. It is writable with either flag (the v2 adapter's
#   staged replay writes the next requests and pending.json next to the answers).
# - Setup (tar, pip, apt, dbmate) runs in a container started without any key. The host's
#   provider keys are given only to the final `docker exec` of the evaluation, as the host
#   user (files written are the user's, nothing is chowned).
# - A throwaway Postgres (TEST_DATABASE_URL) is started only when the adapter reads the
#   database (its `needs_db`, asked to the script itself).
set -euo pipefail

REPO="$(git rev-parse --show-toplevel)"
OUT="${EVAL_OUT:-$REPO/backend/tests/reports/identity}"
SUFFIX="$$"
PG="ldvelh-eval-pg-${SUFFIX}"
BOX="ldvelh-eval-${SUFFIX}"
NET="ldvelh-eval-${SUFFIX}"
# Keep in step with KEY_FIELDS of backend/scripts/smoke_providers.py (a new provider
# key goes in both places).
KEY_VARS=(ANTHROPIC_API_KEY MISTRAL_API_KEY WANDB_API_KEY NEBIUS_API_KEY NOUS_API_KEY)
mkdir -p "$OUT"

io_mode=ro
for arg in "$@"; do
  case "$arg" in --emit-prompts|--emit-prompts=*|--import-responses|--import-responses=*) io_mode=rw ;; esac
done
IO_ARGS=()
if [ -n "${EVAL_IO:-}" ]; then
  mkdir -p "$EVAL_IO"
  IO_ARGS=(-v "$(cd "$EVAL_IO" && pwd)":/io:"$io_mode")
fi

cleanup() {
  docker rm -f "$BOX" "$PG" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "$NET" >/dev/null
# No key in this container's environment: setup code never sees one.
docker run -d --rm --name "$BOX" --network "$NET" \
  -v "$REPO":/src:ro -v "$OUT":/out ${IO_ARGS[@]+"${IO_ARGS[@]}"} \
  python:3.13-slim sleep infinity >/dev/null
docker exec "$BOX" bash -c '
set -euo pipefail
mkdir /w && tar -C /src --exclude=.git --exclude=node_modules -cf - . | tar -C /w -xf -
pip install -q --root-user-action=ignore -r /w/backend/requirements.txt
'

run() {  # run the script as the host user, with `docker exec` options before `--`
  local opts=()
  while [ "$1" != "--" ]; do opts+=("$1"); shift; done
  shift
  docker exec -u "$(id -u):$(id -g)" -w /w/backend -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
    ${opts[@]+"${opts[@]}"} "$BOX" bash -c '
export JWT_SECRET="$(python -c "import secrets; print(secrets.token_hex(32))")"
export ENCRYPTION_KEY="$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")"
exec python -m scripts.eval_identity "$@"
' _ "$@"
}

DB_OPTS=()
if [ "$(run -- --needs-db "$@")" = "1" ]; then
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
  docker exec -e DB_URL="$DB_URL" "$BOX" bash -c '
set -euo pipefail
apt-get update -qq >/dev/null && apt-get install -y -qq curl >/dev/null
/w/db/install-dbmate.sh /w/db/dbmate-release.env /usr/local/bin/dbmate
DATABASE_URL="${DB_URL}?sslmode=disable" \
  dbmate --migrations-dir /w/db/migrations --no-dump-schema up >/dev/null
'
  DB_OPTS=(-e DATABASE_URL="$DB_URL" -e TEST_DATABASE_URL="$DB_URL")
fi

# The keys (value from the host environment) reach this process only.
KEY_OPTS=()
for v in "${KEY_VARS[@]}"; do KEY_OPTS+=(-e "$v"); done
run ${DB_OPTS[@]+"${DB_OPTS[@]}"} "${KEY_OPTS[@]}" -- --out /out "$@"
