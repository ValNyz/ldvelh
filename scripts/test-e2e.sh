#!/usr/bin/env bash
# Run the frontend Playwright e2e tests in Docker; test-results/ is copied to $E2E_OUT.
# Usage: scripts/test-e2e.sh   (E2E_OUT defaults to /tmp/ldvelh-e2e)
set -euo pipefail

REPO="$(git rev-parse --show-toplevel)"
OUT="${E2E_OUT:-/tmp/ldvelh-e2e}"
mkdir -p "$OUT"
rm -rf "$OUT/test-results"  # only the subdirectory this script owns

docker run --rm --ipc=host -v "$REPO/frontend":/src:ro -v "$OUT":/out \
  mcr.microsoft.com/playwright:v1.48.2-jammy bash -c '
cp -r /src /w && cd /w && rm -rf node_modules
npm ci --silent
status=0
npm run test:e2e || status=$?
if [ -d test-results ]; then   # absent when the run produced no artifacts; a failed copy must still fail the script
  cp -r test-results /out/ || { echo "copy of test-results to /out failed" >&2; exit 1; }
  chmod -R a+rwX /out/test-results || { echo "chmod of /out/test-results failed" >&2; exit 1; }
fi
exit $status
'
