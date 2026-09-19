import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.core.database import get_db
from src.routers.oauth_sso import router
from src.services.oauth_sso import OAuthError


class FakeDb:
    pass


class FakeRedis:
    def __init__(self, value):
        self.value = value
        self.deleted = []

    async def get(self, key):
        return self.value

    async def delete(self, key):
        self.deleted.append(key)


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: FakeDb()
    return app


def _redis_factory(redis: FakeRedis):
    async def get_fake_redis():
        return redis

    return get_fake_redis


@pytest.mark.asyncio
async def test_oauth_callback_invalid_state_returns_400(monkeypatch):
    redis = FakeRedis(None)
    monkeypatch.setattr("src.routers.oauth_sso.get_redis", _redis_factory(redis))

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.post(
            "/auth/oauth/callback",
            json={"provider": "microsoft", "code": "code", "state": "missing"},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid or expired OAuth state"}
    assert redis.deleted == []


@pytest.mark.asyncio
async def test_oauth_callback_invalid_provider_returns_400_before_state_lookup(monkeypatch):
    redis = FakeRedis("should-not-be-read")
    monkeypatch.setattr("src.routers.oauth_sso.get_redis", _redis_factory(redis))

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.post(
            "/auth/oauth/callback",
            json={"provider": "provider", "code": "code", "state": "state"},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid OAuth provider"}
    assert redis.deleted == []


@pytest.mark.asyncio
async def test_oauth_callback_malformed_cached_state_returns_400_without_consuming_state(
    monkeypatch,
):
    redis = FakeRedis("not-json")
    monkeypatch.setattr("src.routers.oauth_sso.get_redis", _redis_factory(redis))

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.post(
            "/auth/oauth/callback",
            json={"provider": "microsoft", "code": "code", "state": "malformed"},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid OAuth state data"}
    assert redis.deleted == []


@pytest.mark.asyncio
async def test_oauth_callback_provider_mismatch_returns_400_without_consuming_state(
    monkeypatch,
):
    redis = FakeRedis(
        json.dumps(
            {
                "code_verifier": "verifier",
                "redirect_uri": "https://azure-docs.midtowntg.com/auth/callback",
                "provider": "microsoft",
            }
        )
    )
    monkeypatch.setattr("src.routers.oauth_sso.get_redis", _redis_factory(redis))

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.post(
            "/auth/oauth/callback",
            json={"provider": "google", "code": "code", "state": "state"},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "OAuth provider does not match initiated flow"}
    assert redis.deleted == []


@pytest.mark.asyncio
async def test_oauth_callback_provider_exchange_failure_returns_generic_400(monkeypatch):
    redis = FakeRedis(
        json.dumps(
            {
                "code_verifier": "verifier",
                "redirect_uri": "https://azure-docs.midtowntg.com/auth/callback",
                "provider": "microsoft",
            }
        )
    )
    monkeypatch.setattr("src.routers.oauth_sso.get_redis", _redis_factory(redis))

    class FakeOAuthService:
        def __init__(self, db):
            self.db = db

        async def exchange_code_for_tokens(self, provider, code, redirect_uri, code_verifier):
            raise OAuthError("upstream secret detail")

    monkeypatch.setattr("src.routers.oauth_sso.OAuthService", FakeOAuthService)

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.post(
            "/auth/oauth/callback",
            json={"provider": "microsoft", "code": "bad-code", "state": "state"},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "OAuth callback failed"}
    assert "upstream secret detail" not in response.text
    assert redis.deleted == ["oauth_state:state"]
