"""Tests for production database-credential fail-closed behavior.

Database URLs have no code defaults: every runtime provides explicit
values, and a missing value fails fast. Production additionally refuses
any URL whose password matches the retired development credential (by
digest, so the password itself never appears in Python source).
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
    rules), so this test reads the value production must refuse from the
    same dev compose default an operator would actually copy into
    production. Fails loudly if that default ever moves.
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


def test_production_refuses_matching_password_digest(monkeypatch):
    """The digest mechanism refuses a known-bad password without naming it."""
    synthetic = "test-only-synthetic-credential"
    monkeypatch.setattr(
        config_module,
        "_RETIRED_DEV_DB_DIGEST",
        hashlib.sha256(synthetic.encode()).hexdigest(),
    )
    with pytest.raises(ValidationError, match="retired development"):
        Settings(
            environment="production",
            secret_key="x" * 32,
            database_url=f"postgresql+asyncpg://skra:{synthetic}@db:5432/skra",
            database_url_sync=CLEAN_URL_SYNC,
        )


def test_production_accepts_non_matching_password():
    """A different password passes the digest check."""
    Settings(
        environment="production",
        secret_key="x" * 32,
        database_url=CLEAN_URL,
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
