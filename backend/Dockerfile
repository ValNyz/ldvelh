FROM python:3.13-slim

WORKDIR /app

# No .pyc written at runtime (the code directory is read-only for the app user).
ENV PYTHONDONTWRITEBYTECODE=1

# dbmate, pinned and checksum-verified (#41): version and SHA-256 in db/dbmate-release.env,
# shared with CI and scripts/test-backend.sh. amd64 and arm64 (TARGETARCH, set by BuildKit;
# the machine's architecture otherwise).
ARG TARGETARCH
COPY db/dbmate-release.env db/install-dbmate.sh /tmp/dbmate/
RUN apt-get update \
	&& apt-get install -y --no-install-recommends curl ca-certificates \
	&& /tmp/dbmate/install-dbmate.sh /tmp/dbmate/dbmate-release.env /usr/local/bin/dbmate "${TARGETARCH}" \
	&& rm -rf /tmp/dbmate \
	&& apt-get purge -y curl \
	&& apt-get autoremove -y \
	&& rm -rf /var/lib/apt/lists/*

# Python dependencies (cached separately from source for faster rebuilds)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application source (secrets, tests and caches are kept out by /.dockerignore)
COPY backend/ /app/

# Migrations (from repo root — build context must be the repo root)
COPY db /app/db

# Entrypoint script
COPY backend/entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh

# Unprivileged runtime user (#41). The code stays owned by root: the app cannot rewrite it.
RUN useradd --system --uid 10001 --user-group --create-home --home-dir /home/app app
USER app

EXPOSE 8000

CMD ["/entrypoint.sh"]
