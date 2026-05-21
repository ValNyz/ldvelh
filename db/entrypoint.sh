#!/bin/sh
# Generate self-signed CA + server certificates on first run.
# Certs are stored in /certs (a Docker volume shared with the backend).
# Once generated, subsequent restarts reuse them as long as the volume exists.
set -e

CERT_DIR="/certs"
SERVER_CN="${POSTGRES_SERVER_CN:-db}"  # CN of the server cert (CN of the service inside compose)
DAYS_VALID="${CERT_DAYS_VALID:-3650}"  # 10 years for the CA, plenty for a self-signed setup

mkdir -p "${CERT_DIR}"

if [ ! -f "${CERT_DIR}/server.key" ]; then
    echo "[db] No certs found — generating CA + server cert (CN=${SERVER_CN}, ${DAYS_VALID} days)"

    # Root CA — used to sign the server cert. Backend will trust this CA.
    openssl genrsa -out "${CERT_DIR}/rootCA.key" 2048
    openssl req -x509 -new -nodes \
        -key "${CERT_DIR}/rootCA.key" \
        -sha256 -days "${DAYS_VALID}" \
        -out "${CERT_DIR}/rootCA.crt" \
        -subj "/CN=LDVELH-LocalCA"

    # Server cert — signed by the CA. CN matches the service hostname in compose.
    openssl genrsa -out "${CERT_DIR}/server.key" 2048
    openssl req -new \
        -key "${CERT_DIR}/server.key" \
        -out "${CERT_DIR}/server.csr" \
        -subj "/CN=${SERVER_CN}"
    openssl x509 -req \
        -in "${CERT_DIR}/server.csr" \
        -CA "${CERT_DIR}/rootCA.crt" \
        -CAkey "${CERT_DIR}/rootCA.key" \
        -CAcreateserial \
        -out "${CERT_DIR}/server.crt" \
        -days "${DAYS_VALID}" \
        -sha256

    rm -f "${CERT_DIR}/server.csr" "${CERT_DIR}/rootCA.srl"
    echo "[db] Certificates generated successfully"
else
    echo "[db] Certs already present in ${CERT_DIR}, reusing"
fi

# Postgres requires server.key to be 0600 owned by the postgres user.
chmod 600 "${CERT_DIR}/server.key" "${CERT_DIR}/rootCA.key"
chown -R postgres:postgres "${CERT_DIR}"

# Ensure /var/lib/postgresql (the volume mount root) is writable by postgres.
# Fresh named volumes on some hosts (e.g. Coolify) mount as root:root 0755,
# which prevents the upstream entrypoint from creating its data subdirectory.
mkdir -p /var/lib/postgresql
chown -R postgres:postgres /var/lib/postgresql

# Chain to the upstream Postgres entrypoint, which handles initdb, env vars,
# and finally executes the CMD (postgres).
exec docker-entrypoint.sh "$@"
