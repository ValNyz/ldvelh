#!/usr/bin/env bash
# One-step local setup for `docker compose up` (run from anywhere in the repo, safe to re-run).
#  - docker-compose.override.yml from docker-compose.override.example.yml (ports, DEBUG=true, dev user)
#  - .env from .env.example, with a random JWT_SECRET and ENCRYPTION_KEY when missing
# A JWT_SECRET the backend would refuse is regenerated (it only signs local sessions).
# A set ENCRYPTION_KEY is never overwritten: if invalid, the fix command is printed.
# The rules come from backend/startup_checks.py when python3 + cryptography are available.
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

# Value of NAME in .env, without an inline " # comment", surrounding blanks and quotes
# (what docker compose passes to the container).
env_value() {
  sed -n "s/^$1=//p" .env | tail -n 1 | sed -e 's/[[:space:]]#.*$//' -e 's/^[[:space:]]*//' \
    -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}

# Which secrets the backend would refuse: prints "jwt" and/or "key", one per line.
# Uses backend/startup_checks.py itself when possible, so the rules cannot drift.
refused_secrets() {
  if python3 -c "import cryptography" >/dev/null 2>&1; then
    JWT="$1" KEY="$2" python3 - <<'PY'
import os
import sys

sys.path.insert(0, "backend")
from startup_checks import startup_config_errors

for error in startup_config_errors(os.environ["JWT"], os.environ["KEY"], debug=True):
    print("jwt" if error.startswith("JWT_SECRET") else "key")
PY
    return
  fi
  # Fallback without python3/cryptography: the same length, placeholder, variety and
  # Fernet-shape rules; published values are read from the lists in startup_checks.py.
  local distinct
  distinct="$(printf '%s' "$1" | fold -w1 | sort -u | wc -l)"
  if [ "${#1}" -lt 32 ] || [ "$distinct" -lt 8 ] || printf '%s' "$1" | grep -qiE 'change-?me' \
     || grep -qiF "\"$1\"," backend/startup_checks.py; then
    echo jwt
  fi
  if [ -n "$2" ] && { ! printf '%s' "$2" | grep -qE '^[A-Za-z0-9_+/-]{43}=$' \
     || grep -qF "\"$2\"," backend/startup_checks.py; }; then
    echo key
  fi
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

new_fernet_key() {
  # Fernet key: 32 random bytes, url-safe base64 (44 characters ending with "=").
  head -c 32 /dev/urandom | base64 | tr '+/' '-_'
}

warned=0
key="$(env_value ENCRYPTION_KEY)"
refused="$(refused_secrets "$(env_value JWT_SECRET)" "$key")"

if printf '%s\n' "$refused" | grep -qx jwt; then
  set_env JWT_SECRET "$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
fi

if [ -z "$key" ]; then
  set_env ENCRYPTION_KEY "$(new_fernet_key)"
elif printf '%s\n' "$refused" | grep -qx key; then
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
