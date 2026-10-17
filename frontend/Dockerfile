FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies
COPY package*.json ./
RUN npm ci

# Build argument for API URL
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

# Copy source and build
COPY . .
RUN npm run build

# Production image
FROM node:20-alpine AS runner

WORKDIR /app

# Static server pinned by the lockfile (#41): package-lock.json is the only source of its
# version. Installed alone (npm ci --omit=dev would also pull next and react: 4x the image).
COPY package-lock.json /tmp/package-lock.json
RUN npm install -g --ignore-scripts \
	"serve@$(node -p "require('/tmp/package-lock.json').packages['node_modules/serve'].version")" \
	&& rm /tmp/package-lock.json && npm cache clean --force

# Copy static export
COPY --from=builder /app/out ./out

# Unprivileged runtime user shipped with the node image (#41)
USER node

EXPOSE 3000

CMD ["sh", "-c", "exec serve out -l ${PORT:-3000}"]
