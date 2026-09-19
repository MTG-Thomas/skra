"""Tests for the SKRA_ env prefix and the one-release BIFROST_DOCS_ fallback."""

import pytest

import src.config as config_module
from src.config import Settings


@pytest.fixture
def clean_legacy_warnings():
    """Reset the one-time legacy-key warning registry for determinism."""
    config_module._warned_legacy_keys.clear()
    yield
    config_module._warned_legacy_keys.clear()


def test_skra_prefix_takes_precedence_over_legacy(monkeypatch, clean_legacy_warnings):
    monkeypatch.setenv("SKRA_SECRET_KEY", "x" * 32)
    monkeypatch.setenv("BIFROST_DOCS_SECRET_KEY", "y" * 32)

    settings = Settings()

    assert settings.secret_key == "x" * 32


def test_legacy_prefix_used_as_fallback_with_warning(monkeypatch, clean_legacy_warnings):
    monkeypatch.delenv("SKRA_MFA_TRUSTED_DEVICE_DAYS", raising=False)
    monkeypatch.setenv("BIFROST_DOCS_MFA_TRUSTED_DEVICE_DAYS", "45")

    with pytest.warns(DeprecationWarning, match="BIFROST_DOCS_MFA_TRUSTED_DEVICE_DAYS"):
        settings = Settings()

    assert settings.mfa_trusted_device_days == 45


def test_dotenv_file_values_keep_working(monkeypatch, tmp_path, clean_legacy_warnings):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SKRA_SECRET_KEY", raising=False)
    monkeypatch.delenv("SKRA_MFA_TRUSTED_DEVICE_DAYS", raising=False)
    (tmp_path / ".env").write_text(
        "SKRA_SECRET_KEY=" + "s" * 32 + "\nSKRA_MFA_TRUSTED_DEVICE_DAYS=21\n"
    )

    settings = Settings()

    assert settings.secret_key == "s" * 32
    assert settings.mfa_trusted_device_days == 21


def test_legacy_prefix_read_from_dotenv_file(monkeypatch, tmp_path, clean_legacy_warnings):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SKRA_SECRET_KEY", raising=False)
    monkeypatch.delenv("BIFROST_DOCS_SECRET_KEY", raising=False)
    (tmp_path / ".env").write_text("BIFROST_DOCS_SECRET_KEY=" + "l" * 32 + "\n")

    with pytest.warns(DeprecationWarning, match="BIFROST_DOCS_SECRET_KEY"):
        settings = Settings()

    assert settings.secret_key == "l" * 32


def test_api_key_prefix_helpers():
    from src.core.security import (
        LEGACY_API_KEY_PREFIX,
        generate_api_key,
        is_api_key_token,
    )

    assert generate_api_key().startswith("skra_")
    assert is_api_key_token(generate_api_key()) is True
    assert is_api_key_token(f"{LEGACY_API_KEY_PREFIX}abc123") is True
    assert is_api_key_token("eyJhbGciOiJIUzI1NiJ9.payload.sig") is False
