from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.core.auth import UserPrincipal, get_current_active_user
from src.core.database import get_db
from src.core.rate_limiting import limiter
from src.models.enums import UserRole
from src.routers.passkeys import router
from src.services.passkey_service import PasskeyValidationError


class FakeDb:
    async def commit(self):
        pass


@pytest.mark.asyncio
async def test_registration_options_route_accepts_rate_limited_request(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)

    app = FastAPI()
    app.include_router(router)

    user = UserPrincipal(
        user_id=uuid4(),
        email="test@example.com",
        name="Test User",
        role=UserRole.OWNER,
        is_active=True,
        is_verified=True,
    )

    class FakePasskeyService:
        def __init__(self, db):
            self.db = db

        async def generate_registration_options(self, user_id):
            assert user_id == user.user_id
            return {"challenge": "abc123", "rp": {"name": "Skra"}}

    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: object()
    monkeypatch.setattr("src.routers.passkeys.PasskeyService", FakePasskeyService)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/auth/passkeys/register/options", json={})

    assert response.status_code == 200
    assert response.json() == {"options": {"challenge": "abc123", "rp": {"name": "Skra"}}}


@pytest.mark.asyncio
async def test_registration_options_rejects_api_key_principal(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)

    app = FastAPI()
    app.include_router(router)

    user = UserPrincipal(
        user_id=uuid4(),
        email="scanner@example.com",
        role=UserRole.READER,
        is_active=True,
        is_verified=True,
        api_key_id=uuid4(),
    )

    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: object()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/auth/passkeys/register/options", json={})

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Passkey enrollment requires interactive user authentication"
    }


@pytest.mark.asyncio
async def test_registration_verify_malformed_credential_returns_400(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)

    app = FastAPI()
    app.include_router(router)

    user = UserPrincipal(
        user_id=uuid4(),
        email="test@example.com",
        name="Test User",
        role=UserRole.OWNER,
        is_active=True,
        is_verified=True,
    )

    class FakePasskeyService:
        def __init__(self, db):
            self.db = db

        async def verify_registration(self, user_id, credential_json, device_name=None):
            raise PasskeyValidationError("parser detail that should not leak")

    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: FakeDb()
    monkeypatch.setattr("src.routers.passkeys.PasskeyService", FakePasskeyService)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/passkeys/register/verify",
            json={"credential": {"not": "webauthn"}},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid passkey registration response"}


@pytest.mark.asyncio
async def test_registration_verify_rejects_api_key_principal(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)

    app = FastAPI()
    app.include_router(router)

    user = UserPrincipal(
        user_id=uuid4(),
        email="scanner@example.com",
        role=UserRole.READER,
        is_active=True,
        is_verified=True,
        api_key_id=uuid4(),
    )

    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: FakeDb()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/passkeys/register/verify",
            json={"credential": {}},
        )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Passkey enrollment requires interactive user authentication"
    }


@pytest.mark.asyncio
async def test_authentication_verify_malformed_credential_returns_401(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)

    app = FastAPI()
    app.include_router(router)

    class FakePasskeyService:
        def __init__(self, db):
            self.db = db

        async def verify_authentication(self, challenge_id, credential_json):
            raise PasskeyValidationError("parser detail that should not leak")

    app.dependency_overrides[get_db] = lambda: FakeDb()
    monkeypatch.setattr("src.routers.passkeys.PasskeyService", FakePasskeyService)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/passkeys/authenticate/verify",
            json={"challenge_id": "challenge", "credential": {"not": "webauthn"}},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid passkey authentication response"}
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_authentication_verify_unexpected_error_remains_500(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)

    app = FastAPI()
    app.include_router(router)

    class FakePasskeyService:
        def __init__(self, db):
            self.db = db

        async def verify_authentication(self, challenge_id, credential_json):
            raise RuntimeError("database exploded")

    app.dependency_overrides[get_db] = lambda: FakeDb()
    monkeypatch.setattr("src.routers.passkeys.PasskeyService", FakePasskeyService)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/passkeys/authenticate/verify",
            json={"challenge_id": "challenge", "credential": {"not": "webauthn"}},
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "Failed to verify authentication"}
