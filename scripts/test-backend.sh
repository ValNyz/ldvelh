#!/usr/bin/env bash
# Run the backend test suite in Docker (Postgres + python:3.13-slim), mirroring CI.
# Usage: scripts/test-backend.sh [pytest args...]   (default: tests/ --ignore=tests/benchmark)
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
until docker exec "$PG" pg_isready -U test >/dev/null 2>&1; do sleep 1; done
sleep 2

docker run --rm --network "$NET" -e PG_HOST="$PG" -v "$REPO":/src:ro python:3.13-slim bash -c '
set -euo pipefail
cp -r /src /w && cd /w/backend
apt-get update -qq >/dev/null && apt-get install -y -qq curl >/dev/null
curl -fsSL -o /usr/local/bin/dbmate https://github.com/amacneil/dbmate/releases/download/v2.36.0/dbmate-linux-amd64
echo "47e284b3d8cbad1ba5f090495aa05afd1bbd5f35e2ed5577aad06da74ce780ce  /usr/local/bin/dbmate" | sha256sum -c -
chmod +x /usr/local/bin/dbmate
pip install -q -r requirements.txt
DATABASE_URL="postgresql://test:test@${PG_HOST}:5432/ldvelh_test?sslmode=disable" \
  dbmate --migrations-dir ../db/migrations --no-dump-schema up >/dev/null
export DATABASE_URL="postgresql://test:test@${PG_HOST}:5432/ldvelh_test"
export TEST_DATABASE_URL="$DATABASE_URL"
export JWT_SECRET=ci-test-secret-0123456789abcdef0123
export REQUIRE_TEST_DB=1
export DEBUG=true
export ENCRYPTION_KEY="WkpQHs-KU7XuScnVGAxm35ucMGXCCGt1yLenNhtGqR0="
exec pytest "$@" -o asyncio_mode=auto -q -p no:cacheprovider
' _ "$@"
