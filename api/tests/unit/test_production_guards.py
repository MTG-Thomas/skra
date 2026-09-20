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


REQUIRE_URL = CLEAN_URL + "?sslmode=require"
REQUIRE_URL_SYNC = CLEAN_URL_SYNC + "?sslmode=require"
VERIFY_CA_URL = CLEAN_URL + "?sslmode=verify-ca"
VERIFY_CA_URL_SYNC = CLEAN_URL_SYNC + "?sslmode=verify-ca"
VERIFY_FULL_URL = CLEAN_URL + "?sslmode=verify-full"
VERIFY_FULL_URL_SYNC = CLEAN_URL_SYNC + "?sslmode=verify-full"


def test_production_rejects_sslmode_require_in_async_url():
    """Unverified TLS must fail fast, not silently downgrade (issue #131)."""
    with pytest.raises(ValidationError, match="sslmode=verify-full"):
        Settings(
            environment="production",
            secret_key="x" * 32,
            database_url=REQUIRE_URL,
            database_url_sync=CLEAN_URL_SYNC,
        )


def test_production_rejects_sslmode_require_in_sync_url():
    """The sync URL is held to the same bar as the async URL."""
    with pytest.raises(ValidationError, match="database_url_sync"):
        Settings(
            environment="production",
            secret_key="x" * 32,
            database_url=CLEAN_URL,
            database_url_sync=REQUIRE_URL_SYNC,
        )


def test_production_rejects_sslmode_verify_ca():
    """verify-ca skips hostname verification, so production rejects it too."""
    with pytest.raises(ValidationError, match="sslmode=verify-full"):
        Settings(
            environment="production",
            secret_key="x" * 32,
            database_url=VERIFY_CA_URL,
            database_url_sync=CLEAN_URL_SYNC,
        )
    with pytest.raises(ValidationError, match="database_url_sync"):
        Settings(
            environment="production",
            secret_key="x" * 32,
            database_url=CLEAN_URL,
            database_url_sync=VERIFY_CA_URL_SYNC,
        )


def test_production_rejects_downgrade_and_plaintext_sslmodes():
    """prefer/allow/disable also skip verification (or TLS) — reject all."""
    for mode in ("prefer", "allow", "disable"):
        with pytest.raises(ValidationError, match="sslmode=verify-full"):
            Settings(
                environment="production",
                secret_key="x" * 32,
                database_url=CLEAN_URL + f"?sslmode={mode}",
                database_url_sync=CLEAN_URL_SYNC,
            )
        with pytest.raises(ValidationError, match="database_url_sync"):
            Settings(
                environment="production",
                secret_key="x" * 32,
                database_url=CLEAN_URL,
                database_url_sync=CLEAN_URL_SYNC + f"?sslmode={mode}",
            )


def test_production_rejects_legacy_ssl_query_parameter():
    """The former documented ?ssl=require typo must not bypass the guard."""
    with pytest.raises(ValidationError, match="legacy ssl"):
        Settings(
            environment="production",
            secret_key="x" * 32,
            database_url=CLEAN_URL + "?ssl=require",
            database_url_sync=CLEAN_URL_SYNC,
        )
    with pytest.raises(ValidationError, match="database_url_sync"):
        Settings(
            environment="production",
            secret_key="x" * 32,
            database_url=CLEAN_URL,
            database_url_sync=CLEAN_URL_SYNC + "?ssl=require",
        )


def test_production_accepts_verify_full_and_absent_sslmode():
    """verify-full (managed DB) and absent sslmode (compose network) boot."""
    verified = Settings(
        environment="production",
        secret_key="x" * 32,
        database_url=VERIFY_FULL_URL,
        database_url_sync=VERIFY_FULL_URL_SYNC,
    )
    assert verified.is_production is True


def test_non_production_keeps_permissive_tls_for_dev_and_tests():
    """Local dev and tests keep working with any TLS params (incl. none)."""
    for environment in ("development", "testing"):
        for db_url, db_url_sync in (
            (CLEAN_URL, CLEAN_URL_SYNC),
            (REQUIRE_URL, REQUIRE_URL_SYNC),
            (VERIFY_CA_URL, VERIFY_CA_URL_SYNC),
            (VERIFY_FULL_URL, VERIFY_FULL_URL_SYNC),
            (CLEAN_URL + "?sslmode=prefer", CLEAN_URL_SYNC + "?sslmode=disable"),
            (CLEAN_URL + "?ssl=require", CLEAN_URL_SYNC + "?ssl=require"),
        ):
            settings = Settings(
                environment=environment,
                secret_key="x" * 32,
                database_url=db_url,
                database_url_sync=db_url_sync,
            )
            assert settings.environment == environment
