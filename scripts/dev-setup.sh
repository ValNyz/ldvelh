#!/usr/bin/env bash
# One-step local setup for `docker compose up` (run from anywhere in the repo, safe to re-run).
#  - docker-compose.override.yml from docker-compose.override.example.yml (ports, DEBUG=true, dev user)
#  - .env from .env.example, with a random JWT_SECRET and ENCRYPTION_KEY when missing or placeholder
# Existing values are kept; only empty or placeholder secrets are replaced.
set -euo pipefail

REPO="$(git rev-parse --show-toplevel)"
cd "$REPO"

if [ -e docker-compose.override.yml ]; then
  echo "docker-compose.override.yml already exists: kept"
else
  cp docker-compose.override.example.yml docker-compose.override.yml
  echo "docker-compose.override.yml created"
fi

if [ ! -e .env ]; then
  cp .env.example .env
  echo ".env created from .env.example"
fi

# Value of NAME in .env, without an inline " # comment" and surrounding blanks.
env_value() {
  sed -n "s/^$1=//p" .env | tail -n 1 | sed -e 's/[[:space:]]#.*$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

# Replace (or append) NAME=VALUE in .env.
set_env() {
  if grep -q "^$1=" .env; then
    local tmp
    tmp="$(mktemp)"
    awk -v name="$1" -v value="$2" 'index($0, name "=") == 1 { print name "=" value; next } { print }' .env > "$tmp"
    cat "$tmp" > .env && rm -f "$tmp"
  else
    printf '%s=%s\n' "$1" "$2" >> .env
  fi
  echo "$1 set in .env"
}

jwt="$(env_value JWT_SECRET)"
if [ "${#jwt}" -lt 32 ] || printf '%s' "$jwt" | grep -qiE 'change-?me'; then
  set_env JWT_SECRET "$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
fi

new_fernet_key() {
  # Fernet key: 32 random bytes, url-safe base64 (44 characters ending with "=").
  head -c 32 /dev/urandom | base64 | tr '+/' '-_'
}

warned=0
key="$(env_value ENCRYPTION_KEY)"
if [ -z "$key" ]; then
  set_env ENCRYPTION_KEY "$(new_fernet_key)"
elif ! printf '%s' "$key" | grep -qE '^[A-Za-z0-9_-]{43}=$'; then
  # Never overwrite a set key: API keys already saved with it would become unreadable.
  echo "WARNING: ENCRYPTION_KEY in .env is not a valid Fernet key; the backend will refuse to start." >&2
  echo "  Replace it (players' saved API keys encrypted with the old value are lost) with:" >&2
  echo "  sed -i 's|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$(new_fernet_key)|' .env" >&2
  warned=1
fi

if [ -z "$(env_value DB_PASSWORD)" ]; then
  # Local database only; it must match the password the pgdata volume was created with.
  set_env DB_PASSWORD ldvelh
fi

if [ "$warned" -eq 1 ]; then
  echo "Fix the warning above, then: docker compose up --build"
else
  echo "Ready: docker compose up --build"
fi
