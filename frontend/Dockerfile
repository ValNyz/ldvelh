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

# Static server from its own minimal manifest (#41): runtime/package-lock.json pins serve
# and every dependency, without the app's build dependencies (next, react).
COPY runtime/package.json runtime/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts && npm cache clean --force

# Copy static export
COPY --from=builder /app/out ./out

# Unprivileged runtime user shipped with the node image (#41)
USER node

EXPOSE 3000

CMD ["sh", "-c", "exec node_modules/.bin/serve out -l ${PORT:-3000}"]
