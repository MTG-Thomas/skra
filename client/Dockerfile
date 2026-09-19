# syntax=docker/dockerfile:1.7
# Skra Client - Production Container Image
# Multi-stage build for optimized production image

# =============================================================================
# Stage 1: Base with dependencies
# =============================================================================
FROM node:20-slim AS base

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN --mount=type=cache,target=/root/.npm \
    npm ci

# =============================================================================
# Stage 2: Build for production
# =============================================================================
FROM base AS builder

# Copy source code
COPY . .

# Build the application
RUN npm run build

# =============================================================================
# Stage 3: Development with Vite dev server (explicit target only)
# =============================================================================
# Used by docker-compose.test.yml (target: development) for E2E runs:
# source comes from bind mounts, API proxy from API_URL/WS_URL env.
# Never the default: the final production stage below stays last.
FROM base AS development

WORKDIR /app

EXPOSE 3000

# Vite on 3000 to match the test-stack healthcheck (overrides the
# 5173 default in vite.config.ts).
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]

# =============================================================================
# Stage 4: Production with nginx
# =============================================================================
FROM nginx:alpine AS production

# Copy built assets from builder
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy nginx configurations
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx-ssl.conf /app/nginx-ssl.conf

# Create SSL directory
RUN mkdir -p /etc/nginx/ssl

EXPOSE 80 443

CMD ["nginx", "-g", "daemon off;"]
