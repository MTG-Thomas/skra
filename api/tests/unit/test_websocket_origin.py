"""Unit tests for WebSocket Origin validation on cookie auth (issue #90).

Cookie credentials are ambient, so cookie-authenticated WebSocket handshakes
must present an allowlisted Origin header to prevent cross-site WebSocket
hijacking. Explicit query-param tokens are presented deliberately per
connection and stay exempt for non-browser clients.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

ALLOWED_ORIGINS = ["http://localhost:3000", "https://docs.example.com"]


class _FakeWebSocket:
    """Minimal stub exposing what authenticate_websocket reads."""

    def __init__(self, cookies=None, query_params=None, headers=None):
        self.cookies = cookies or {}
        self.query_params = query_params or {}
        self.headers = headers or {}


@pytest.fixture
def allowed_settings(monkeypatch):
    import src.routers.websocket as ws_router

    monkeypatch.setattr(
        ws_router,
        "get_settings",
        lambda: SimpleNamespace(cors_origins_list=list(ALLOWED_ORIGINS)),
    )


def _access_token():
    from src.core.security import create_access_token

    return create_access_token(
        {
            "sub": str(uuid4()),
            "email": "ws-tech@example.com",
            "role": "owner",
        }
    )


class TestWebsocketCookieOrigin:
    """Origin allowlist for cookie-authenticated WebSocket handshakes."""

    async def test_cookie_with_allowed_origin_authenticates(self, allowed_settings):
        from src.routers.websocket import authenticate_websocket

        ws = _FakeWebSocket(
            cookies={"access_token": _access_token()},
            headers={"origin": "http://localhost:3000"},
        )

        principal = await authenticate_websocket(ws)

        assert principal is not None
        assert principal.email == "ws-tech@example.com"

    async def test_cookie_with_cross_site_origin_rejected(self, allowed_settings):
        from src.routers.websocket import authenticate_websocket

        ws = _FakeWebSocket(
            cookies={"access_token": _access_token()},
            headers={"origin": "https://evil.example.net"},
        )

        assert await authenticate_websocket(ws) is None

    async def test_cookie_with_missing_origin_rejected(self, allowed_settings):
        from src.routers.websocket import authenticate_websocket

        ws = _FakeWebSocket(cookies={"access_token": _access_token()})

        assert await authenticate_websocket(ws) is None

    async def test_explicit_token_without_origin_authenticates(self, allowed_settings):
        from src.routers.websocket import authenticate_websocket

        ws = _FakeWebSocket(query_params={"token": _access_token()})

        principal = await authenticate_websocket(ws)

        assert principal is not None
        assert principal.email == "ws-tech@example.com"

    async def test_explicit_token_with_cross_site_origin_authenticates(self, allowed_settings):
        from src.routers.websocket import authenticate_websocket

        ws = _FakeWebSocket(
            query_params={"token": _access_token()},
            headers={"origin": "https://evil.example.net"},
        )

        principal = await authenticate_websocket(ws)

        assert principal is not None
        assert principal.email == "ws-tech@example.com"

    async def test_no_credentials_rejected(self, allowed_settings):
        from src.routers.websocket import authenticate_websocket

        ws = _FakeWebSocket(headers={"origin": "http://localhost:3000"})

        assert await authenticate_websocket(ws) is None
