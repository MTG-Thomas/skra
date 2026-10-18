"""First-owner bootstrap authorization regressions (security ledger row 126)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from src.core.database import get_db
from src.core.rate_limiting import limiter
from src.models.enums import UserRole
from src.routers import auth

TOKEN = "b" * 32
DENIED = {"detail": "Initial platform setup is not authorized."}


class FakeDb:
    async def flush(self) -> None:
        pass


def _settings(*, production: bool = True, token: str | None = TOKEN) -> SimpleNamespace:
    return SimpleNamespace(
        is_production=production,
        is_development=not production,
        is_testing=False,
        bootstrap_token=SecretStr(token) if token is not None else None,
    )


def test_bootstrap_guard_fails_closed_and_uses_constant_secret_contract(monkeypatch):
    valid_token = SecretStr(TOKEN)
    wrong_token = SecretStr("w" * 32)

    monkeypatch.setattr(auth, "get_settings", lambda: _settings(token=None))
    with pytest.raises(HTTPException) as missing_config:
        auth._require_bootstrap_authorization(valid_token)
    assert missing_config.value.status_code == 403

    monkeypatch.setattr(auth, "get_settings", lambda: _settings())
    with pytest.raises(HTTPException) as missing_request:
        auth._require_bootstrap_authorization(None)
    with pytest.raises(HTTPException) as wrong_request:
        auth._require_bootstrap_authorization(wrong_token)
    assert missing_request.value.detail == wrong_request.value.detail

    auth._require_bootstrap_authorization(valid_token)
    monkeypatch.setattr(auth, "get_settings", lambda: _settings(production=False, token=None))
    auth._require_bootstrap_authorization(None)


@pytest.mark.asyncio
@pytest.mark.parametrize("supplied", [None, "w" * 32])
async def test_password_first_owner_denies_missing_or_wrong_token(monkeypatch, supplied):
    monkeypatch.setattr(limiter, "enabled", False)
    monkeypatch.setattr(auth, "get_settings", lambda: _settings())
    repo = SimpleNamespace(
        has_any_users=AsyncMock(return_value=False),
        get_by_email=AsyncMock(return_value=None),
        create_user=AsyncMock(),
    )
    monkeypatch.setattr(auth, "UserRepository", lambda _db: repo)
    app = FastAPI()
    app.include_router(auth.router)
    app.dependency_overrides[get_db] = lambda: FakeDb()
    body = {"email": "owner@example.com", "password": "strong-password"}
    if supplied is not None:
        body["bootstrap_token"] = supplied

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/auth/register", json=body)

    assert response.status_code == 403
    assert response.json() == DENIED
    repo.create_user.assert_not_awaited()


@pytest.mark.asyncio
async def test_password_first_owner_accepts_authorized_token(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)
    monkeypatch.setattr(auth, "get_settings", lambda: _settings())
    user = SimpleNamespace(
        id="00000000-0000-4000-8000-000000000001",
        email="owner@example.com",
        name="Owner",
        role=UserRole.OWNER,
        is_active=True,
        is_verified=True,
        mfa_enabled=False,
    )
    repo = SimpleNamespace(
        has_any_users=AsyncMock(return_value=False),
        get_by_email=AsyncMock(return_value=None),
        create_user=AsyncMock(return_value=user),
    )
    audit = SimpleNamespace(log=AsyncMock())
    monkeypatch.setattr(auth, "UserRepository", lambda _db: repo)
    monkeypatch.setattr(auth, "get_password_hash", lambda _password: "hashed")
    monkeypatch.setattr(auth, "get_audit_service", lambda _db: audit)
    app = FastAPI()
    app.include_router(auth.router)
    app.dependency_overrides[get_db] = lambda: FakeDb()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/register",
            json={
                "email": "owner@example.com",
                "password": "strong-password",
                "name": "Owner",
                "bootstrap_token": TOKEN,
            },
        )

    assert response.status_code == 201
    assert response.json()["role"] == "owner"
    repo.create_user.assert_awaited_once()


@pytest.mark.asyncio
async def test_passkey_setup_options_and_verify_require_token(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)
    monkeypatch.setattr(auth, "get_settings", lambda: _settings())
    app = FastAPI()
    app.include_router(auth.router)
    app.dependency_overrides[get_db] = lambda: FakeDb()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        options = await client.post(
            "/auth/setup/passkey/options",
            json={"email": "owner@example.com"},
        )
        verify = await client.post(
            "/auth/setup/passkey/verify",
            json={"registration_token": "attacker", "credential": {}},
        )

    assert options.status_code == 403
    assert options.json() == DENIED
    assert verify.status_code == 403
    assert verify.json() == DENIED


@pytest.mark.asyncio
async def test_passkey_setup_options_accept_authorized_token(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)
    monkeypatch.setattr(auth, "get_settings", lambda: _settings())

    class FakePasskeyService:
        def __init__(self, _db):
            pass

        async def generate_setup_registration_options(self, email, name=None):
            assert email == "owner@example.com"
            return "registration-token", {"challenge": "synthetic"}

    monkeypatch.setattr("src.services.passkey_service.PasskeyService", FakePasskeyService)
    app = FastAPI()
    app.include_router(auth.router)
    app.dependency_overrides[get_db] = lambda: FakeDb()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/setup/passkey/options",
            json={"email": "owner@example.com", "bootstrap_token": TOKEN},
        )

    assert response.status_code == 200
    assert response.json()["registration_token"] == "registration-token"
