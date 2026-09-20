"""Tests for mandatory database configuration.

Both database URLs are required settings with no code defaults: every
runtime (compose files, CI, test fixtures) provides explicit values, and
a missing value fails fast at startup in any environment.
"""

import pytest
from pydantic import ValidationError

from src.config import Settings

CLEAN_URL = "postgresql+asyncpg://skra:prod-secret@example.invalid/skra"
CLEAN_URL_SYNC = "postgresql://skra:prod-secret@example.invalid/skra"


def _isolate_database_urls(monkeypatch):
    """Drop ambient DB URL env so required-field behavior is deterministic."""
    for var in (
        "SKRA_DATABASE_URL",
        "SKRA_DATABASE_URL_SYNC",
        "BIFROST_DOCS_DATABASE_URL",
        "BIFROST_DOCS_DATABASE_URL_SYNC",
    ):
        monkeypatch.delenv(var, raising=False)


def test_missing_database_urls_fail_fast(monkeypatch):
    """No code defaults: a missing URL is a loud startup error, any env."""
    _isolate_database_urls(monkeypatch)
    for environment in ("development", "testing", "production"):
        with pytest.raises(ValidationError, match="database_url"):
            Settings(environment=environment, secret_key="x" * 32)


def test_each_database_url_is_individually_mandatory(monkeypatch):
    """Async and sync URLs are each required; one does not imply the other."""
    _isolate_database_urls(monkeypatch)
    with pytest.raises(ValidationError, match="database_url_sync"):
        Settings(
            environment="production",
            secret_key="x" * 32,
            database_url=CLEAN_URL,
        )
    with pytest.raises(ValidationError, match="database_url"):
        Settings(
            environment="production",
            secret_key="x" * 32,
            database_url_sync=CLEAN_URL_SYNC,
        )


def test_production_boots_with_explicit_urls():
    """Production boots normally once both URLs are configured."""
    settings = Settings(
        environment="production",
        secret_key="x" * 32,
        database_url=CLEAN_URL,
        database_url_sync=CLEAN_URL_SYNC,
    )

    assert settings.is_production is True
