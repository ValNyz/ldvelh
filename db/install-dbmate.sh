#!/bin/sh
# Download the pinned dbmate (db/dbmate-release.env) for this machine and verify it.
# Usage: install-dbmate.sh <release env file> <destination> [amd64|arm64]
set -eu
. "$1"
arch="${3:-}"
if [ -z "$arch" ]; then
  case "$(uname -m)" in
    x86_64) arch=amd64 ;;
    aarch64|arm64) arch=arm64 ;;
    *) echo "dbmate: unsupported architecture $(uname -m)" >&2; exit 1 ;;
  esac
fi
case "$arch" in
  amd64) sha="$DBMATE_SHA256_amd64" ;;
  arm64) sha="$DBMATE_SHA256_arm64" ;;
  *) echo "dbmate: unsupported architecture $arch" >&2; exit 1 ;;
esac
curl -fsSL -o "$2" "https://github.com/amacneil/dbmate/releases/download/${DBMATE_VERSION}/dbmate-linux-${arch}"
echo "${sha}  $2" | sha256sum -c -
chmod 755 "$2"
