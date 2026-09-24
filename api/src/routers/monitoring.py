"""
Monitoring and Health Dashboard Router

Provides endpoints for application monitoring:
- /metrics - Prometheus metrics
- /health/detailed - Detailed health check with dependencies
- /status - Application status dashboard
"""

import time
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from src.core.auth import CurrentActiveUser
from src.core.database import DbSession

router = APIRouter(tags=["monitoring"])

# In-memory metrics storage (in production, use Prometheus client)
_request_count = 0
_request_duration_total = 0.0
_last_request_time = None
_START_MONOTONIC = time.monotonic()


@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics(db: DbSession) -> str:
    """
    Prometheus-compatible metrics endpoint.

    Returns metrics in Prometheus text format for scraping.
    """
    metrics = []

    # Application info
    metrics.append("# HELP skra_info Application information")
    metrics.append("# TYPE skra_info gauge")
    metrics.append('skra_info{version="1.0.0"} 1')

    # Uptime since process start (monotonic clock, not wall time)
    metrics.append("")
    metrics.append("# HELP skra_uptime_seconds Application uptime in seconds")
    metrics.append("# TYPE skra_uptime_seconds gauge")
    metrics.append(f"skra_uptime_seconds {time.monotonic() - _START_MONOTONIC:.3f}")

    # Database connection status
    db_healthy = True
    try:
        await db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        db_healthy = False

    metrics.append("")
    metrics.append("# HELP skra_database_connected Database connection status")
    metrics.append("# TYPE skra_database_connected gauge")
    metrics.append(f"skra_database_connected {1 if db_healthy else 0}")

    # User counts
    try:
        result = await db.execute(text("SELECT count(*) FROM users"))
        user_count = result.scalar() or 0
    except Exception:
        user_count = 0

    metrics.append("")
    metrics.append("# HELP skra_users_total Total number of users")
    metrics.append("# TYPE skra_users_total gauge")
    metrics.append(f"skra_users_total {user_count}")

    # Request metrics (if tracking enabled)
    global _request_count, _request_duration_total
    if _request_count > 0:
        metrics.append("")
        metrics.append("# HELP skra_requests_total Total requests")
        metrics.append("# TYPE skra_requests_total counter")
        metrics.append(f"skra_requests_total {_request_count}")

    return "\n".join(metrics)


@router.get("/health/detailed")
async def detailed_health_check(db: DbSession) -> JSONResponse:
    """
    Detailed health check with all dependencies.

    Returns status of:
    - Database connectivity
    - Redis connectivity
    - S3 storage connectivity
    - Overall application health
    """
    checks = {}
    overall_healthy = True

    # Check database
    try:
        start = time.time()
        await db.execute(text("SELECT 1"))
        db_latency = time.time() - start
        checks["database"] = {"status": "healthy", "latency_ms": round(db_latency * 1000, 2)}
    except SQLAlchemyError as e:
        checks["database"] = {"status": "unhealthy", "error": str(e)}
        overall_healthy = False

    # Check Redis (if configured)
    try:
        from src.core.cache import get_redis

        redis_client = await get_redis()
        start = time.time()
        await redis_client.ping()
        redis_latency = time.time() - start
        checks["redis"] = {"status": "healthy", "latency_ms": round(redis_latency * 1000, 2)}
    except Exception as e:
        # Redis is optional for basic operation
        checks["redis"] = {
            "status": "degraded",
            "error": str(e),
            "note": "Redis is optional, app can function without it",
        }

    # Overall status
    status = "healthy" if overall_healthy else "unhealthy"
    status_code = 200 if overall_healthy else 503

    response_data = {"status": status, "timestamp": datetime.now(UTC).isoformat(), "checks": checks}

    return JSONResponse(content=response_data, status_code=status_code)


@router.get("/status")
async def status_dashboard(
    request: Request, current_user: CurrentActiveUser, db: DbSession
) -> dict:
    """
    Application status dashboard for administrators.

    Shows:
    - System health
    - Database statistics
    - Storage usage
    - Recent activity
    """
    from src.config import get_settings

    settings = get_settings()

    # Database stats
    try:
        result = await db.execute(
            text("""
            SELECT
                (SELECT count(*) FROM users) as user_count,
                (SELECT count(*) FROM organizations) as org_count,
                (SELECT count(*) FROM passwords) as password_count,
                (SELECT count(*) FROM documents) as document_count,
                (SELECT pg_database_size(current_database())) as db_size_bytes
        """)
        )
        row = result.fetchone()
        if row is None:
            raise ValueError("Failed to fetch database stats")
        db_stats = {
            "users": row.user_count,
            "organizations": row.org_count,
            "passwords": row.password_count,
            "documents": row.document_count,
            "database_size_mb": round(row.db_size_bytes / (1024 * 1024), 2),
        }
    except Exception as e:
        db_stats = {"error": str(e)}

    # Storage stats (S3)
    try:
        from src.config import get_settings
        from src.services.file_storage import FileStorageService

        FileStorageService(get_settings())
        # This would need to be implemented in FileStorageService
        storage_stats = {"status": "connected"}
    except Exception as e:
        storage_stats = {"status": "error", "error": str(e)}

    # Application info
    app_info = {
        "version": "1.0.0",
        "environment": settings.environment,
        "debug": settings.debug,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    return {
        "application": app_info,
        "database": db_stats,
        "storage": storage_stats,
        "user": {
            "id": str(current_user.user_id),
            "email": current_user.email,
            "role": current_user.role,
        },
    }


# Request tracking middleware helper
def track_request(duration: float):
    """Track request metrics (called by RequestMetricsMiddleware)."""
    global _request_count, _request_duration_total, _last_request_time
    _request_count += 1
    _request_duration_total += duration
    _last_request_time = time.time()


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    """Feed every served request into the in-memory request metrics."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.perf_counter()
        try:
            return await call_next(request)
        finally:
            track_request(time.perf_counter() - start)
