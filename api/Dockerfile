# syntax=docker/dockerfile:1.7
# Bifrost Docs API Dockerfile
# Multi-stage build for production

FROM python:3.11-slim AS builder

# Pinned uv binary for reproducible, lockfile-driven installs. `pip install .`
# resolved floating versions from pyproject.toml, so uv.lock bumps (e.g. #80)
# never controlled the published image (see issue #82).
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv

# Install build dependencies
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Locked dependency install into the runtime venv path. --locked fails the
# build if uv.lock drifts from pyproject.toml, proving lock freshness.
ENV UV_PROJECT_ENVIRONMENT="/opt/venv" UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
# Copy src directory so setuptools can find the package
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Production stage
FROM python:3.11-slim

# Install runtime dependencies
# Apply Debian security updates for perl-base (CVE-2026-42496, CVE-2026-8376,
# CVE-2026-13221, fixed in 5.40.1-6+deb13u1). The base image floats, so upgrade
# explicitly instead of relying on the base snapshot date.
#
# Retained runtime tooling (issue #84: remove only with VM-gated proof):
# - curl: required by the HEALTHCHECK below.
# - pip/setuptools/wheel in system site-packages: base-image tooling, kept so
#   the image stays debuggable with standard Python tooling; the application
#   itself runs from /opt/venv and never invokes them. Removal (which would
#   also drop pip's vendored SBOM manifests flagged in issue #82) is deferred
#   to VM-gated evaluation, tracked in issue #91.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && apt-get install -y --only-upgrade perl-base \
    && python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set working directory and Python path
WORKDIR /app
ENV PYTHONPATH="/app"

# Copy application code
COPY --chown=app:app . .

# Switch to non-root user
USER app

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
