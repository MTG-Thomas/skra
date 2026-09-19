"""
Application Configuration

Uses pydantic-settings for environment variable loading with validation.
All configuration is centralized here for easy management.
"""

import os
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, computed_field, model_validator
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

#: Previous env prefix, honored as a one-release fallback (see _LegacyEnvSource).
#: Remove after all operators have migrated to SKRA_*.
LEGACY_ENV_PREFIX = "BIFROST_DOCS_"

_warned_legacy_keys: set[str] = set()


class _LegacyEnvSource(EnvSettingsSource):
    """
    Fallback source that reads BIFROST_DOCS_* variables for fields not set
    via SKRA_* (or init kwargs). Emits a one-time DeprecationWarning per key.
    """

    def __call__(self) -> dict[str, Any]:
        values = super().__call__() or {}
        dotenv_values = self._legacy_dotenv_values()
        for field_name in self.settings_cls.model_fields:
            if field_name in values:
                continue
            legacy_key = f"{LEGACY_ENV_PREFIX}{field_name.upper()}"
            if legacy_key in os.environ:
                values[field_name] = os.environ[legacy_key]
            elif field_name in dotenv_values:
                values[field_name] = dotenv_values[field_name]
            else:
                continue
            if legacy_key not in _warned_legacy_keys:
                _warned_legacy_keys.add(legacy_key)
                warnings.warn(
                    f"{legacy_key} is deprecated, use SKRA_{field_name.upper()} instead",
                    DeprecationWarning,
                    stacklevel=2,
                )
        return values

    def _legacy_dotenv_values(self) -> dict[str, Any]:
        """Legacy-prefixed values from the .env file (field-mapped)."""
        env_file = self.settings_cls.model_config.get("env_file")
        if not env_file:
            return {}
        source = DotEnvSettingsSource(
            self.settings_cls, env_file=env_file, env_prefix=LEGACY_ENV_PREFIX
        )
        return source() or {}  # type: ignore[no-any-return]


def _read_env_file(path: str) -> dict[str, str]:
    """Read a KEY=VALUE credentials file (blank lines and # comments ignored).

    Raises:
        ValueError: If the file cannot be read.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"S3 credentials file unreadable: {path}: {e}") from e
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("\"'")
    return values


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Environment variables can be set directly or via .env file.
    All secrets should be provided via environment variables in production.
    """

    model_config = SettingsConfigDict(
        env_prefix="SKRA_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Legacy BIFROST_DOCS_* vars apply only when SKRA_* is unset.
        # dotenv_settings is kept so .env-file values keep working as before.
        return (init_settings, env_settings, dotenv_settings, _LegacyEnvSource(settings_cls))

    # ==========================================================================
    # Environment
    # ==========================================================================
    environment: Literal["development", "testing", "production"] = Field(
        default="development", description="Runtime environment"
    )

    debug: bool = Field(default=False, description="Enable debug mode")

    # ==========================================================================
    # Database (PostgreSQL)
    # ==========================================================================
    database_url: str = Field(
        default="postgresql+asyncpg://skra:skradev@localhost:5433/skra",
        description="Async PostgreSQL connection URL",
    )

    database_url_sync: str = Field(
        default="postgresql://skra:skradev@localhost:5433/skra",
        description="Sync PostgreSQL connection URL (for Alembic)",
    )

    database_pool_size: int = Field(default=5, description="Database connection pool size")

    database_max_overflow: int = Field(
        default=10, description="Max overflow connections beyond pool size"
    )

    # ==========================================================================
    # Redis
    # ==========================================================================
    redis_url: str = Field(default="redis://localhost:6380/0", description="Redis connection URL")
    rate_limiting_enabled: bool = Field(
        default=True,
        description="Enable Redis-backed API rate limiting. Disable for deployments without Redis.",
    )

    # ==========================================================================
    # Security
    # ==========================================================================
    secret_key: str = Field(
        description="Secret key for JWT signing and encryption (SKRA_SECRET_KEY env var required)",
        min_length=32,
    )

    algorithm: str = Field(default="HS256", description="JWT signing algorithm")

    access_token_expire_minutes: int = Field(
        default=30, description="Access token expiration time in minutes"
    )

    refresh_token_expire_days: int = Field(
        default=7, description="Refresh token expiration time in days"
    )

    jwt_issuer: str = Field(default="skra-api", description="JWT issuer claim for token validation")

    jwt_audience: str = Field(
        default="skra-client", description="JWT audience claim for token validation"
    )

    # NOTE: default retained from bifrost-docs on purpose. It feeds HKDF key
    # derivation together with the info string in core/security.py — changing
    # either default silently destroys access to already-encrypted secrets.
    fernet_salt: str = Field(
        default="bifrost_docssecrets_v1",
        description="Salt for Fernet key derivation (override for different encryption keys)",
    )

    # ==========================================================================
    # CORS
    # ==========================================================================
    cors_origins: str = Field(
        default="http://localhost:3000", description="Comma-separated list of allowed CORS origins"
    )

    @computed_field
    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins into a list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    # ==========================================================================
    # Default User (for automated deployments and development)
    # ==========================================================================
    default_user_email: str | None = Field(
        default=None, description="Default admin user email (creates user on startup if set)"
    )

    default_user_password: str | None = Field(
        default=None, description="Default admin user password"
    )

    # ==========================================================================
    # MFA Settings
    # ==========================================================================
    mfa_enabled: bool = Field(
        default=True, description="Whether MFA is required for password authentication"
    )

    mfa_totp_issuer: str = Field(default="Skra", description="Issuer name for TOTP QR codes")

    mfa_recovery_code_count: int = Field(
        default=10, description="Number of recovery codes to generate for MFA"
    )

    mfa_trusted_device_days: int = Field(
        default=30, description="Number of days a device stays trusted after MFA verification"
    )

    mfa_setup_token_expire_minutes: int = Field(
        default=15,
        description="MFA setup token expiration time in minutes (longer than verify for setup flow)",
    )

    mfa_verify_token_expire_minutes: int = Field(
        default=5, description="MFA verify token expiration time in minutes (during login)"
    )

    # ==========================================================================
    # WebAuthn/Passkeys
    # ==========================================================================
    webauthn_rp_id: str = Field(
        default="localhost", description="WebAuthn Relying Party ID (must match origin domain)"
    )

    webauthn_rp_name: str = Field(default="Skra", description="WebAuthn Relying Party display name")

    webauthn_origin: str = Field(
        default="http://localhost:3000",
        description="WebAuthn expected origin URLs (comma-separated for multiple)",
    )

    @property
    def webauthn_origins(self) -> list[str]:
        """Parse webauthn_origin into a list of origins."""
        return [o.strip() for o in self.webauthn_origin.split(",") if o.strip()]

    # ==========================================================================
    # File Storage (Local)
    # ==========================================================================
    temp_location: str = Field(
        default="/tmp/skra", description="Path to temporary storage directory"
    )

    storage_backend: Literal["s3", "azure_blob"] = Field(
        default="s3",
        description="Attachment/export storage backend. Use 'azure_blob' for Azure Storage.",
    )

    # ==========================================================================
    # S3/MinIO Storage
    # ==========================================================================
    s3_endpoint: str = Field(
        default="http://localhost:9000",
        description="S3-compatible endpoint URL (MinIO in development)",
    )

    s3_public_endpoint: str | None = Field(
        default=None,
        description="Public S3 endpoint for presigned URLs (defaults to s3_endpoint if not set). "
        "Use this when S3/MinIO is behind a proxy or in Docker.",
    )

    s3_access_key: str | None = Field(
        default=None, description="S3 access key (required for S3 operations)"
    )

    s3_secret_key: str | None = Field(
        default=None, description="S3 secret key (required for S3 operations)"
    )

    s3_credentials_file: str | None = Field(
        default=None,
        description="Path to a KEY=VALUE file (S3_ACCESS_KEY_ID, "
        "S3_SECRET_ACCESS_KEY) written by garage-init in managed mode. "
        "Explicit s3_access_key/s3_secret_key always win.",
    )

    @model_validator(mode="after")
    def _load_s3_credentials_file(self) -> "Settings":
        """Resolve S3 credentials as one atomic pair.

        Explicit credentials must both be set and non-empty, or both be
        absent: half a pair (or an empty half, e.g. from an unset env
        interpolation) mixed with file values yields mismatched credentials
        while s3_configured reports true. The file is only consulted when
        neither explicit value is set, and must then contain both non-empty
        values — otherwise startup fails closed instead of running with S3
        silently disabled.
        """
        explicit = (self.s3_access_key, self.s3_secret_key)
        if any(v is not None for v in explicit):
            if not all(v and v.strip() for v in explicit):
                raise ValueError("s3_access_key and s3_secret_key must both be set and non-empty")
            return self
        if self.s3_credentials_file:
            creds = _read_env_file(self.s3_credentials_file)
            access_key = creds.get("S3_ACCESS_KEY_ID")
            secret_key = creds.get("S3_SECRET_ACCESS_KEY")
            if not access_key or not secret_key:
                raise ValueError(
                    f"S3 credentials file must contain both S3_ACCESS_KEY_ID and "
                    f"S3_SECRET_ACCESS_KEY: {self.s3_credentials_file}"
                )
            self.s3_access_key = access_key
            self.s3_secret_key = secret_key
        return self

    s3_bucket: str = Field(default="skra", description="S3 bucket name for file storage")

    s3_region: str = Field(default="us-east-1", description="S3 region (use us-east-1 for MinIO)")

    s3_presigned_url_expiry: int = Field(
        default=600, description="Presigned URL expiry in seconds (default 10 minutes)"
    )

    s3_download_url_expiry: int = Field(
        default=3600, description="Download URL expiry in seconds (default 1 hour)"
    )

    @computed_field
    @property
    def s3_configured(self) -> bool:
        """Check if S3 storage is properly configured."""
        return self.s3_access_key is not None and self.s3_secret_key is not None

    # ==========================================================================
    # Azure Blob Storage
    # ==========================================================================
    azure_storage_account_url: str | None = Field(
        default=None,
        description="Azure Blob service URL, e.g. https://account.blob.core.windows.net",
    )

    azure_storage_connection_string: str | None = Field(
        default=None,
        description="Azure Storage connection string. Prefer managed identity for production.",
    )

    azure_storage_account_key: str | None = Field(
        default=None,
        description="Azure Storage account key for SAS generation when not using a connection string.",
    )

    azure_blob_container: str = Field(
        default="skra",
        description="Azure Blob container name for file storage.",
    )

    azure_blob_sas_expiry: int = Field(
        default=600,
        description="Azure Blob upload SAS expiry in seconds.",
    )

    azure_blob_download_sas_expiry: int = Field(
        default=3600,
        description="Azure Blob download SAS expiry in seconds.",
    )

    @computed_field
    @property
    def azure_blob_configured(self) -> bool:
        """Check if Azure Blob storage is configured."""
        return self.azure_storage_connection_string is not None or (
            self.azure_storage_account_url is not None
            and self.azure_storage_account_key is not None
        )

    @computed_field
    @property
    def storage_configured(self) -> bool:
        """Check if the selected storage backend is configured."""
        if self.storage_backend == "azure_blob":
            return self.azure_blob_configured
        return self.s3_configured

    # ==========================================================================
    # OpenAI (for embeddings)
    # ==========================================================================
    openai_api_key: str | None = Field(
        default=None, description="OpenAI API key for embeddings generation"
    )

    openai_embedding_model: str = Field(
        default="text-embedding-ada-002",
        description="OpenAI embedding model (default: text-embedding-ada-002)",
    )

    # ==========================================================================
    # Server
    # ==========================================================================
    host: str = Field(default="0.0.0.0", description="Server host")

    port: int = Field(default=8000, description="Server port")

    # ==========================================================================
    # Computed Properties
    # ==========================================================================
    @computed_field
    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.environment == "development"

    @computed_field
    @property
    def is_testing(self) -> bool:
        """Check if running in testing mode."""
        return self.environment == "testing"

    @computed_field
    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.environment == "production"

    def validate_paths(self) -> None:
        """
        Validate that required filesystem paths exist.

        Creates temp directory if it doesn't exist.
        """
        temp = Path(self.temp_location)
        temp.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses lru_cache to ensure settings are only loaded once.
    Settings are loaded from environment variables via pydantic-settings.
    """
    return Settings()  # type: ignore[call-arg]  # pydantic-settings loads from env


def clear_settings_cache() -> None:
    """Clear the settings cache (useful for testing)."""
    get_settings.cache_clear()
