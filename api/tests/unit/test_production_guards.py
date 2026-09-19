"""Tests for the production database-credential guard."""

import pytest
from pydantic import ValidationError

from src.config import Settings


def test_production_rejects_default_database_url():
    """Production must fail fast instead of running on dev defaults."""
    with pytest.raises(ValidationError, match="database_url"):
        Settings(environment="production", secret_key="x" * 32)


def test_production_rejects_default_sync_database_url():
    """The sync URL default is guarded independently."""
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


def test_non_production_keeps_dev_database_defaults():
    """Development and testing still boot on defaults."""
    for environment in ("development", "testing"):
        settings = Settings(environment=environment, secret_key="x" * 32)

        assert ":skradev@" in settings.database_url
