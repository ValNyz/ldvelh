FROM python:3.13-slim

WORKDIR /app

# dbmate, pinned and checksum-verified (#41): same version as CI and scripts/test-backend.sh.
# The checksum is for the linux-amd64 binary.
ARG DBMATE_VERSION=v2.36.0
ARG DBMATE_SHA256=47e284b3d8cbad1ba5f090495aa05afd1bbd5f35e2ed5577aad06da74ce780ce
RUN apt-get update \
	&& apt-get install -y --no-install-recommends curl ca-certificates \
	&& curl -fsSL -o /usr/local/bin/dbmate \
	"https://github.com/amacneil/dbmate/releases/download/${DBMATE_VERSION}/dbmate-linux-amd64" \
	&& echo "${DBMATE_SHA256}  /usr/local/bin/dbmate" | sha256sum -c - \
	&& chmod +x /usr/local/bin/dbmate \
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
