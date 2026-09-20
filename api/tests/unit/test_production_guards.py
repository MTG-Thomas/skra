"""Tests for mandatory database configuration and the retired-credential guard.

Both database URLs are required settings with no code defaults: every
runtime (compose files, CI, test fixtures) provides explicit values, and
a missing value fails fast at startup in any environment. Production
additionally refuses any URL whose password verifies against the stored
PBKDF2-HMAC reference of the retired development credential, so the
password itself never appears in Python source.
"""

import hashlib
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

import src.config as config_module
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


def _dev_compose_default_password() -> str:
    """Parse the dev database password default from docker-compose.dev.yml.

    The retired credential must not appear as a Python literal (secret
    rules), so tests read the value production must refuse from the same
    dev compose default an operator would actually copy into production.
    Fails loudly if that default ever moves.
    """
    compose = Path(__file__).resolve().parents[3] / "docker-compose.dev.yml"
    match = re.search(r"\$\{POSTGRES_PASSWORD:-([^}]+)\}", compose.read_text())
    assert match, "dev compose must define a POSTGRES_PASSWORD default"
    return match.group(1)


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


def test_production_refuses_matching_credential(monkeypatch):
    """The PBKDF2 mechanism refuses a known-bad password without naming it."""
    synthetic = "test-only-synthetic-credential"
    salt = b"test-only-salt"
    monkeypatch.setattr(config_module, "_RETIRED_DEV_DB_SALT", salt)
    monkeypatch.setattr(config_module, "_RETIRED_DEV_DB_ITERATIONS", 1_000)
    monkeypatch.setattr(
        config_module,
        "_RETIRED_DEV_DB_DIGEST",
        hashlib.pbkdf2_hmac("sha256", synthetic.encode(), salt, 1_000).hex(),
    )
    with pytest.raises(ValidationError, match="retired development"):
        Settings(
            environment="production",
            secret_key="x" * 32,
            database_url=f"postgresql+asyncpg://skra:{synthetic}@db:5432/skra",
            database_url_sync=CLEAN_URL_SYNC,
        )


def test_production_refuses_dev_compose_default_credential(monkeypatch):
    """End to end: production refuses the actual dev default credential."""
    _isolate_database_urls(monkeypatch)
    dev_password = _dev_compose_default_password()
    with pytest.raises(ValidationError, match="retired development"):
        Settings(
            environment="production",
            secret_key="x" * 32,
            database_url=f"postgresql+asyncpg://skra:{dev_password}@pgbouncer:5432/skra",
            database_url_sync=CLEAN_URL_SYNC,
        )


def test_non_production_allows_dev_compose_default_credential(monkeypatch):
    """Development still boots on the dev default (no behavior change)."""
    _isolate_database_urls(monkeypatch)
    dev_password = _dev_compose_default_password()
    for environment in ("development", "testing"):
        settings = Settings(
            environment=environment,
            secret_key="x" * 32,
            database_url=f"postgresql+asyncpg://skra:{dev_password}@pgbouncer:5432/skra",
            database_url_sync=CLEAN_URL_SYNC,
        )
        assert settings.is_production is False
