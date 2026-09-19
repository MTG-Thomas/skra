"""Tests for storage backend and rate-limiting configuration."""

import importlib

import pytest
from pydantic import ValidationError

from src.config import Settings, _read_env_file


def test_storage_configured_uses_s3_backend_by_default():
    settings = Settings(secret_key="x" * 32, s3_access_key="key", s3_secret_key="secret")

    assert settings.storage_backend == "s3"
    assert settings.s3_configured is True
    assert settings.storage_configured is True


def test_storage_configured_uses_azure_blob_backend():
    settings = Settings(
        secret_key="x" * 32,
        storage_backend="azure_blob",
        azure_storage_account_url="https://docsproof.blob.core.windows.net",
        azure_storage_account_key="account-key",
    )

    assert settings.azure_blob_configured is True
    assert settings.storage_configured is True


def test_storage_configured_is_false_for_incomplete_azure_blob_backend():
    settings = Settings(
        secret_key="x" * 32,
        storage_backend="azure_blob",
        azure_storage_account_url="https://docsproof.blob.core.windows.net",
    )

    assert settings.azure_blob_configured is False
    assert settings.storage_configured is False


def test_rate_limiting_can_be_disabled(monkeypatch):
    monkeypatch.setenv("SKRA_SECRET_KEY", "x" * 32)
    monkeypatch.setenv("SKRA_RATE_LIMITING_ENABLED", "false")

    import src.config as config
    import src.core.rate_limiting as rate_limiting

    config.clear_settings_cache()
    reloaded = importlib.reload(rate_limiting)

    assert reloaded.RATE_LIMITING_ENABLED is False
    assert reloaded.limiter.middleware_class is None


def test_s3_credentials_file_fills_unset_keys(tmp_path):
    """Managed credentials file supplies keys the env did not set."""
    creds = tmp_path / "s3.env"
    creds.write_text(
        "# written by garage-init\nS3_ACCESS_KEY_ID=GKfilekey\nS3_SECRET_ACCESS_KEY=filesecret\n"
    )
    settings = Settings(secret_key="x" * 32, s3_credentials_file=str(creds))

    assert settings.s3_access_key == "GKfilekey"
    assert settings.s3_secret_key == "filesecret"
    assert settings.s3_configured is True


def test_explicit_s3_keys_win_over_credentials_file(tmp_path):
    """Explicit env/kwarg credentials are never overwritten by the file."""
    creds = tmp_path / "s3.env"
    creds.write_text("S3_ACCESS_KEY_ID=GKfilekey\nS3_SECRET_ACCESS_KEY=filesecret\n")
    settings = Settings(
        secret_key="x" * 32,
        s3_access_key="explicit",
        s3_secret_key="explicit-secret",
        s3_credentials_file=str(creds),
    )

    assert settings.s3_access_key == "explicit"
    assert settings.s3_secret_key == "explicit-secret"


def test_missing_s3_credentials_file_fails_closed(tmp_path):
    """A configured-but-absent file is a startup error, not silent S3-off."""
    with pytest.raises(ValidationError):
        Settings(
            secret_key="x" * 32,
            s3_credentials_file=str(tmp_path / "absent.env"),
        )


def test_partial_explicit_s3_pair_fails_closed(tmp_path):
    """Half an explicit pair never mixes with the other half from the file."""
    creds = tmp_path / "s3.env"
    creds.write_text("S3_ACCESS_KEY_ID=GKfilekey\nS3_SECRET_ACCESS_KEY=filesecret\n")
    with pytest.raises(ValidationError, match="both be set and non-empty"):
        Settings(
            secret_key="x" * 32,
            s3_access_key="explicit-only",
            s3_credentials_file=str(creds),
        )
    with pytest.raises(ValidationError, match="both be set and non-empty"):
        Settings(
            secret_key="x" * 32,
            s3_secret_key="explicit-only",
            s3_credentials_file=str(creds),
        )


def test_empty_explicit_s3_pair_fails_closed(tmp_path):
    """Empty-string halves (e.g. unset env interpolation) fail, not fallback."""
    creds = tmp_path / "s3.env"
    creds.write_text("S3_ACCESS_KEY_ID=GKfilekey\nS3_SECRET_ACCESS_KEY=filesecret\n")
    with pytest.raises(ValidationError, match="both be set and non-empty"):
        Settings(secret_key="x" * 32, s3_access_key="", s3_secret_key="set")
    with pytest.raises(ValidationError, match="both be set and non-empty"):
        Settings(secret_key="x" * 32, s3_access_key="set", s3_secret_key="   ")
    with pytest.raises(ValidationError, match="both be set and non-empty"):
        Settings(
            secret_key="x" * 32,
            s3_access_key="",
            s3_secret_key="",
            s3_credentials_file=str(creds),
        )


def test_incomplete_s3_credentials_file_fails_closed(tmp_path):
    """A file naming only one credential is a startup error, not S3-off."""
    creds = tmp_path / "s3.env"
    creds.write_text("S3_ACCESS_KEY_ID=GKfilekey\n")
    with pytest.raises(ValidationError, match="must contain both"):
        Settings(secret_key="x" * 32, s3_credentials_file=str(creds))


def test_read_env_file_ignores_comments_and_blank_lines(tmp_path):
    """Parser tolerates comments, blanks, and quoted values."""
    creds = tmp_path / "s3.env"
    creds.write_text(
        "\n# comment\nS3_ACCESS_KEY_ID = GKabc\nS3_SECRET_ACCESS_KEY='quoted'\nNOEQUALS\n"
    )

    assert _read_env_file(str(creds)) == {
        "S3_ACCESS_KEY_ID": "GKabc",
        "S3_SECRET_ACCESS_KEY": "quoted",
    }


def test_noop_limiter_decorator_returns_original_function():
    import src.core.rate_limiting as rate_limiting

    limiter = rate_limiting._NoOpLimiter()

    def endpoint():
        return "ok"

    assert limiter.limit("1/minute")(endpoint) is endpoint
