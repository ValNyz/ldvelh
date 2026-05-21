#!/bin/sh
# Configure Postgres to enforce SSL on all connections.
# Runs ONCE on first initialization (when /var/lib/postgresql/data is empty),
# via Postgres's standard /docker-entrypoint-initdb.d/ mechanism.
set -e

CONF="${PGDATA}/postgresql.conf"
HBA="${PGDATA}/pg_hba.conf"

echo "[db] Enabling SSL in ${CONF}"
cat >> "${CONF}" <<EOF

# === LDVELH TLS configuration ===
ssl = on
ssl_cert_file = '/certs/server.crt'
ssl_key_file = '/certs/server.key'
ssl_ca_file = '/certs/rootCA.crt'
EOF

# Replace pg_hba.conf entirely: only allow encrypted connections.
# We use scram-sha-256 (password) over SSL -- no client certs to distribute.
# Keep the local socket as trust so the upstream entrypoint scripts still work.
echo "[db] Enforcing SSL in ${HBA}"
cat > "${HBA}" <<EOF
# === LDVELH pg_hba -- SSL-only ===
# TYPE      DATABASE   USER   ADDRESS         METHOD
local       all        all                    trust
hostssl     all        all    0.0.0.0/0       scram-sha-256
hostssl     all        all    ::/0            scram-sha-256
# Plain "host" entries omitted on purpose: non-SSL connections are refused.
EOF
