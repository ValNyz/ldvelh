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

# Pinned static server (#41): same version as package-lock.json.
ARG SERVE_VERSION=14.2.5
RUN npm install -g "serve@${SERVE_VERSION}" && npm cache clean --force

# Copy static export
COPY --from=builder /app/out ./out

# Unprivileged runtime user shipped with the node image (#41)
USER node

EXPOSE 3000

CMD ["sh", "-c", "serve out -l ${PORT:-3000}"]
