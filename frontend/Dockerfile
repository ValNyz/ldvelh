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

RUN npm install -g serve

# Copy static export
COPY --from=builder /app/out ./out

EXPOSE 3000

CMD ["sh", "-c", "serve out -l ${PORT:-3000}"]
