"""Tests for the production database-credential guard."""

import pytest
from pydantic import ValidationError

from src.config import Settings


def _isolate_database_urls(monkeypatch):
    """Drop ambient DB URL env so Field defaults apply deterministically."""
    for var in (
        "SKRA_DATABASE_URL",
        "SKRA_DATABASE_URL_SYNC",
        "BIFROST_DOCS_DATABASE_URL",
        "BIFROST_DOCS_DATABASE_URL_SYNC",
    ):
        monkeypatch.delenv(var, raising=False)


def test_production_rejects_default_database_url(monkeypatch):
    """Production must fail fast instead of running on dev defaults."""
    _isolate_database_urls(monkeypatch)
    with pytest.raises(ValidationError, match="database_url"):
        Settings(environment="production", secret_key="x" * 32)


def test_production_rejects_default_sync_database_url(monkeypatch):
    """The sync URL default is guarded independently."""
    _isolate_database_urls(monkeypatch)
    with pytest.raises(ValidationError, match="database_url_sync"):
        Settings(
            environment="production",
            secret_key="x" * 32,
            database_url="postgresql+asyncpg://skra:prod-secret@example.invalid/skra",
        )


def test_production_accepts_configured_database_urls():
    """Explicit non-default credentials boot production normally."""
    settings = Settings(
        environment="production",
        secret_key="x" * 32,
        database_url="postgresql+asyncpg://skra:prod-secret@example.invalid/skra",
        database_url_sync="postgresql://skra:prod-secret@example.invalid/skra",
    )

    assert settings.is_production is True


def test_non_production_keeps_dev_database_defaults(monkeypatch):
    """Development and testing still boot on defaults."""
    _isolate_database_urls(monkeypatch)
    for environment in ("development", "testing"):
        settings = Settings(environment=environment, secret_key="x" * 32)

        assert ":skradev@" in settings.database_url
