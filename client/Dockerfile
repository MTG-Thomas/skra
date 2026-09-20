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
COPY --from=builder --chown=nginx:nginx /app/dist /usr/share/nginx/html

# Copy nginx configurations
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx-ssl.conf /app/nginx-ssl.conf

# Run as non-root nginx user (uid 101 in nginx:alpine).
# Main /etc/nginx/nginx.conf already sets `user nginx`; the master process
# only stays root for privileged ports and root-owned paths, so this stage
# listens on unprivileged ports and owns its runtime paths instead.
# NOTE: operator-mounted TLS certs under /etc/nginx/ssl must be readable by
# uid 101 (e.g. mount with :ro and group/other read or chown 101).
RUN mkdir -p /etc/nginx/ssl && \
    chown -R nginx:nginx /usr/share/nginx/html /etc/nginx/conf.d /etc/nginx/ssl \
        /var/cache/nginx /var/log/nginx && \
    chown nginx:nginx /app/nginx-ssl.conf && \
    sed -i 's|^pid .*|pid /tmp/nginx.pid;|' /etc/nginx/nginx.conf

EXPOSE 8080 8443

USER nginx

# /tmp is world-writable so the non-root master can write its pid file
# (/run is root-owned and the pid directive cannot be set from conf.d).
CMD ["nginx", "-g", "daemon off;"]
