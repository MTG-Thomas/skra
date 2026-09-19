"""Unit tests for cookie-session CSRF enforcement (issue #90).

Covers the auth-dependency matrix: Bearer/API-key requests are exempt,
cookie-authenticated safe methods pass without CSRF, and
cookie-authenticated mutations require the double-submit pair.
"""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request


def _make_request(method="GET", cookies=None, headers=None):
    """Fabricate a minimal Starlette request with cookies/headers."""
    raw_headers = []
    if cookies:
        cookie_value = "; ".join(f"{k}={v}" for k, v in cookies.items())
        raw_headers.append((b"cookie", cookie_value.encode()))
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode(), value.encode()))
    return Request(
        {
            "type": "http",
            "method": method,
            "headers": raw_headers,
            "server": ("test", 80),
            "scheme": "http",
            "path": "/",
            "query_string": b"",
        }
    )


def _access_token():
    from src.core.security import create_access_token

    return create_access_token(
        {
            "sub": str(uuid4()),
            "email": "e2e-tech@example.com",
            "role": "owner",
        }
    )


def _csrf_pair():
    from src.core.security import generate_csrf_token

    token = generate_csrf_token()
    return token, token


class TestCookieCsrfEnforcement:
    """CSRF matrix for get_current_user_optional."""

    async def test_bearer_mutation_without_csrf_is_exempt(self):
        from src.core.auth import get_current_user_optional

        token = _access_token()
        request = _make_request("POST")
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=token
        )

        principal = await get_current_user_optional(
            request=request, credentials=credentials, db=None
        )

        assert principal is not None
        assert principal.email == "e2e-tech@example.com"

    async def test_cookie_get_without_csrf_passes(self):
        from src.core.auth import get_current_user_optional

        token = _access_token()
        request = _make_request("GET", cookies={"access_token": token})

        principal = await get_current_user_optional(
            request=request, credentials=None, db=None
        )

        assert principal is not None

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    async def test_cookie_mutation_with_valid_pair_passes(self, method):
        from src.core.auth import get_current_user_optional

        token = _access_token()
        csrf_cookie, csrf_header = _csrf_pair()
        request = _make_request(
            method,
            cookies={"access_token": token, "csrf_token": csrf_cookie},
            headers={"X-CSRF-Token": csrf_header},
        )

        principal = await get_current_user_optional(
            request=request, credentials=None, db=None
        )

        assert principal is not None

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    async def test_cookie_mutation_without_csrf_raises_403(self, method):
        from src.core.auth import get_current_user_optional

        token = _access_token()
        request = _make_request(method, cookies={"access_token": token})

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_optional(
                request=request, credentials=None, db=None
            )

        assert exc_info.value.status_code == 403

    async def test_cookie_mutation_with_mismatched_pair_raises_403(self):
        from src.core.auth import get_current_user_optional

        token = _access_token()
        csrf_cookie, _ = _csrf_pair()
        other_cookie, _ = _csrf_pair()
        assert other_cookie != csrf_cookie
        request = _make_request(
            "POST",
            cookies={"access_token": token, "csrf_token": csrf_cookie},
            headers={"X-CSRF-Token": other_cookie},
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_optional(
                request=request, credentials=None, db=None
            )

        assert exc_info.value.status_code == 403

    async def test_no_credentials_returns_none(self):
        from src.core.auth import get_current_user_optional

        request = _make_request("POST")

        assert (
            await get_current_user_optional(
                request=request, credentials=None, db=None
            )
            is None
        )

    async def test_invalid_cookie_token_returns_none_not_403(self):
        from src.core.auth import get_current_user_optional

        request = _make_request(
            "POST", cookies={"access_token": "not-a-token"}
        )

        assert (
            await get_current_user_optional(
                request=request, credentials=None, db=None
            )
            is None
        )


class TestRefreshCookieCsrf:
    """CSRF matrix for POST /auth/refresh (issue #90 review finding).

    The endpoint reads the refresh cookie directly instead of going
    through get_current_user_optional, so it enforces the pair itself.
    Body-token (API client) callers stay exempt.
    """

    def _refresh_token_for(self, user_id):
        from src.core.security import create_refresh_token

        token, _jti = create_refresh_token(data={"sub": str(user_id)})
        return token

    def _active_user(self, user_id):
        from types import SimpleNamespace

        from src.models.enums import UserRole

        return SimpleNamespace(
            id=user_id,
            email="e2e-tech@example.com",
            name="E2E Technician",
            role=UserRole.OWNER,
            is_active=True,
        )

    async def _call_refresh(self, monkeypatch, user, cookies=None,
                            headers=None, body_token=None):
        from unittest.mock import AsyncMock

        from starlette.responses import Response

        import src.routers.auth as auth_router
        from src.models.contracts.auth import RefreshTokenRequest

        repo = AsyncMock()
        repo.get_by_id.return_value = user
        monkeypatch.setattr(
            auth_router.UserRepository, "get_by_id", repo.get_by_id
        )

        request = _make_request(
            "POST", cookies=cookies, headers=headers
        )
        token_data = (
            RefreshTokenRequest(refresh_token=body_token)
            if body_token is not None
            else None
        )
        # Bypass the slowapi rate-limit wrapper (needs live Redis); the
        # tests target the endpoint's auth logic, not rate limiting.
        handler = getattr(
            auth_router.refresh_token, "__wrapped__", auth_router.refresh_token
        )
        return await handler(
            request=request,
            response=Response(),
            db=AsyncMock(),
            token_data=token_data,
        )

    async def test_cookie_refresh_with_valid_pair_succeeds(self, monkeypatch):
        from uuid import uuid4

        user_id = uuid4()
        token = self._refresh_token_for(user_id)
        csrf_cookie, csrf_header = _csrf_pair()

        result = await self._call_refresh(
            monkeypatch,
            self._active_user(user_id),
            cookies={"refresh_token": token, "csrf_token": csrf_cookie},
            headers={"X-CSRF-Token": csrf_header},
        )

        assert result.access_token
        assert result.refresh_token

    async def test_cookie_refresh_without_csrf_raises_403(self, monkeypatch):
        from uuid import uuid4

        user_id = uuid4()
        token = self._refresh_token_for(user_id)

        with pytest.raises(HTTPException) as exc_info:
            await self._call_refresh(
                monkeypatch,
                self._active_user(user_id),
                cookies={"refresh_token": token},
            )

        assert exc_info.value.status_code == 403

    async def test_cookie_refresh_with_mismatched_pair_raises_403(
        self, monkeypatch
    ):
        from uuid import uuid4

        user_id = uuid4()
        token = self._refresh_token_for(user_id)
        csrf_cookie, _ = _csrf_pair()
        other_cookie, _ = _csrf_pair()
        assert other_cookie != csrf_cookie

        with pytest.raises(HTTPException) as exc_info:
            await self._call_refresh(
                monkeypatch,
                self._active_user(user_id),
                cookies={
                    "refresh_token": token,
                    "csrf_token": csrf_cookie,
                },
                headers={"X-CSRF-Token": other_cookie},
            )

        assert exc_info.value.status_code == 403

    async def test_body_refresh_without_csrf_succeeds(self, monkeypatch):
        from uuid import uuid4

        user_id = uuid4()
        token = self._refresh_token_for(user_id)

        result = await self._call_refresh(
            monkeypatch,
            self._active_user(user_id),
            body_token=token,
        )

        assert result.access_token
        assert result.refresh_token

    async def test_refresh_without_any_token_raises_401(self, monkeypatch):
        from uuid import uuid4

        with pytest.raises(HTTPException) as exc_info:
            await self._call_refresh(
                monkeypatch, self._active_user(uuid4())
            )

        assert exc_info.value.status_code == 401
