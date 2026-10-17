#!/usr/bin/env bash
# Run the backend test suite in Docker (Postgres + python:3.13-slim), mirroring CI.
# Usage: scripts/test-backend.sh [pytest args...]   (default: tests/ --ignore=tests/benchmark)
# UPDATE_SNAPSHOTS=1 scripts/test-backend.sh tests/characterization  rewrites snapshots on the host.
set -euo pipefail

REPO="$(git rev-parse --show-toplevel)"
SUFFIX="$$"
PG="ldvelh-test-pg-${SUFFIX}"
NET="ldvelh-test-${SUFFIX}"

if [ "$#" -eq 0 ]; then
  set -- tests/ --ignore=tests/benchmark
fi

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

SNAP_ARGS=()
if [ "${UPDATE_SNAPSHOTS:-}" = "1" ]; then
  SNAP_ARGS=(-e UPDATE_SNAPSHOTS=1 -e HOST_IDS="$(id -u):$(id -g)"
             -v "$REPO/backend/tests/characterization/snapshots":/snapshots)
fi

docker run --rm --network "$NET" -e PG_HOST="$PG" ${SNAP_ARGS[@]+"${SNAP_ARGS[@]}"} -v "$REPO":/src:ro python:3.13-slim bash -c '
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
# Random per-run secrets: a value published in the repo is rejected by startup_checks.
export JWT_SECRET="$(python -c "import secrets; print(secrets.token_hex(32))")"
export ENCRYPTION_KEY="$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")"
export REQUIRE_TEST_DB=1
export DEBUG=true
status=0
pytest "$@" -o asyncio_mode=auto -q -p no:cacheprovider || status=$?
if [ "${UPDATE_SNAPSHOTS:-}" = "1" ]; then
  cp -r tests/characterization/snapshots/. /snapshots/ && chown -R "$HOST_IDS" /snapshots
fi
exit $status
' _ "$@"
