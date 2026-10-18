"""
Rate Limiting Configuration

Provides Redis-backed rate limiting for the API using slowapi.
Different limits for different endpoint types (auth vs API).

Note: If slowapi is not installed, rate limiting is disabled (development mode).
"""

from collections.abc import Callable
from typing import Any, cast

from src.config import get_settings


class _NoOpLimiter:
    """Limiter-compatible no-op used when rate limiting is disabled."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def limit(self, limits: Any, *args: Any, **kwargs: Any) -> Callable[[Any], Any]:
        """Return a decorator that leaves the route handler unchanged."""

        def decorator(f: Any) -> Any:
            return f

        return decorator

    middleware_class: Any = None


# Try to import slowapi - if not available, use dummy implementations
try:
    from slowapi import Limiter as _Limiter  # noqa: F811
    from slowapi.util import get_remote_address as _get_remote_address  # noqa: F811

    SLOWAPI_AVAILABLE = True

    # Use the real implementations
    class Limiter(_Limiter):  # type: ignore[misc, no-redef]
        """Real Limiter from slowapi."""

        pass

    def get_remote_address(request: Any) -> str:  # type: ignore[misc, no-redef]
        """Get remote address from request using slowapi."""
        return _get_remote_address(request)  # type: ignore[no-any-return]

except ImportError:
    SLOWAPI_AVAILABLE = False

    # Create dummy limiter class and decorator for when slowapi is not installed
    class Limiter(_NoOpLimiter):  # type: ignore[no-redef]
        """Dummy Limiter class when slowapi is not installed."""

    def get_remote_address(request: Any) -> str:  # type: ignore[misc, no-redef]
        """Dummy get_remote_address when slowapi is not installed."""
        return "127.0.0.1"


def get_authenticated_user_or_remote_address(request: Any) -> str:
    """Key authenticated limits by user, falling back to the remote address."""
    state = getattr(request, "state", None)
    identity = getattr(state, "rate_limit_identity", None)
    if identity:
        return str(identity)
    return f"ip:{get_remote_address(request)}"


settings = get_settings()
RATE_LIMITING_ENABLED = SLOWAPI_AVAILABLE and settings.rate_limiting_enabled

# Create limiter with Redis storage, or a no-op limiter if disabled/unavailable.
if RATE_LIMITING_ENABLED:
    limiter = Limiter(
        key_func=get_remote_address,
        storage_uri=settings.redis_url,
        storage_options=cast(Any, {"socket_connect_timeout": 30}),
        default_limits=["100/minute"],  # Default: 100 requests per minute
    )
else:
    limiter = _NoOpLimiter(key_func=get_remote_address)


# Rate limit configurations by endpoint type
class RateLimits:
    """Rate limit configurations for different endpoint categories."""

    # Authentication endpoints - strict limits to prevent brute force
    AUTH_STRICT = "5/minute,20/hour"  # 5 per minute, 20 per hour
    AUTH_LOGIN = "10/minute,50/hour"  # Slightly higher for login

    # Passkey/WebAuthn endpoints
    PASSKEY = "10/minute,30/hour"

    # MFA endpoints
    MFA = "5/minute,20/hour"

    # API endpoints - moderate limits
    API_GENERAL = "100/minute,1000/hour"
    API_WRITE = "60/minute,500/hour"  # POST/PUT/DELETE

    # Search endpoints - can be expensive
    SEARCH = "30/minute,200/hour"
    EXPENSIVE_READ = "10/minute,100/hour"

    # Admin endpoints - very strict
    ADMIN = "20/minute,100/hour"

    # Health check - very permissive
    HEALTH = "1000/minute"

    # WebSocket connections
    WEBSOCKET = "10/minute"  # Connection attempts
