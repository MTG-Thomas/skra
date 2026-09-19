# syntax=docker/dockerfile:1.7
# Bifrost Docs API Dockerfile
# Multi-stage build for production

FROM python:3.11-slim AS builder

# Install build dependencies
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies from pyproject.toml
WORKDIR /app
COPY pyproject.toml ./
# Copy src directory so setuptools can find the package
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel && \
    pip install .

# Production stage
FROM python:3.11-slim

# Install runtime dependencies
# Apply Debian security updates for perl-base (CVE-2026-42496, CVE-2026-8376,
# CVE-2026-13221, fixed in 5.40.1-6+deb13u1). The base image floats, so upgrade
# explicitly instead of relying on the base snapshot date.
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
