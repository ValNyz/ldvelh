FROM python:3.13-slim

WORKDIR /app

# Install dbmate (needs curl + ca-certificates temporarily)
RUN apt-get update \
	&& apt-get install -y --no-install-recommends curl ca-certificates \
	&& curl -fsSL -o /usr/local/bin/dbmate \
	https://github.com/amacneil/dbmate/releases/latest/download/dbmate-linux-amd64 \
	&& chmod +x /usr/local/bin/dbmate \
	&& apt-get purge -y curl \
	&& apt-get autoremove -y \
	&& rm -rf /var/lib/apt/lists/*

# Python dependencies (cached separately from source for faster rebuilds)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application source
COPY backend/ /app/

# Migrations (from repo root — build context must be the repo root)
COPY db /app/db

# Entrypoint script
COPY backend/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

CMD ["/entrypoint.sh"]
