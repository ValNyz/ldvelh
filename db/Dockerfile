# Custom Postgres image with self-contained TLS certificate generation.
# Certs live in a Docker volume mounted at /certs and are shared read-only
# with the backend so it can verify the CA. Generated on first start, reused
# on subsequent restarts.

FROM postgres:18

# postgres:18 (Debian-based) ships the openssl CLI we need for generating
# the self-signed CA + server cert. Trades ~300MB image size for reliability
# (Alpine apk repos are flaky on some Docker networks).

# Init script: runs once on first DB init (when the data dir is empty).
# Appends SSL config to postgresql.conf and rewrites pg_hba.conf.
COPY ssl-config.sh /docker-entrypoint-initdb.d/ssl-config.sh

# Wrapper entrypoint: generates certs into /certs if they're missing,
# then chains to the upstream Postgres entrypoint.
COPY entrypoint.sh /usr/local/bin/ldvelh-entrypoint.sh
# 755 = rwxr-xr-x. We use 755 explicitly (not chmod +x) because the host's
# COPY may carry restrictive ACLs that block "others" from reading the script.
# Postgres runs as the "postgres" user, which is in "others" — so it needs
# both read AND execute bits set globally.
RUN chmod 755 /usr/local/bin/ldvelh-entrypoint.sh \
    && chmod 755 /docker-entrypoint-initdb.d/ssl-config.sh

ENTRYPOINT ["/usr/local/bin/ldvelh-entrypoint.sh"]
CMD ["postgres"]
