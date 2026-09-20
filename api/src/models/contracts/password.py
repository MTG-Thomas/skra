"""Password contracts (API request/response schemas)."""

from pydantic import BaseModel, Field, PrivateAttr, computed_field

from src.models.contracts.base import PublicEntityBase
from src.models.contracts.sync import SyncMetadata


class PasswordCreate(BaseModel):
    """Password creation request model."""

    name: str = Field(..., min_length=1, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    password: str = Field(..., min_length=1)
    totp_secret: str | None = None
    url: str | None = Field(default=None, max_length=2048)
    notes: str | None = None
    metadata: dict | None = None
    sync_metadata: SyncMetadata | None = None
    is_enabled: bool | None = None  # Defaults to True if not provided


class PasswordUpdate(BaseModel):
    """Password update request model."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=1)
    totp_secret: str | None = None
    url: str | None = Field(default=None, max_length=2048)
    notes: str | None = None
    metadata: dict | None = None
    sync_metadata: SyncMetadata | None = None
    is_enabled: bool | None = None  # Don't change if not provided


class PasswordPublic(PublicEntityBase):
    """Password public response model (without password value)."""

    name: str
    username: str | None = None
    url: str | None = None
    notes: str | None = None
    sync_metadata: SyncMetadata | None = None
    updated_by_user_id: str | None = None
    updated_by_user_name: str | None = None

    # Private attribute for internal use (not serialized)
    _totp_secret_encrypted: str | None = PrivateAttr(default=None)

    @computed_field
    @property
    def has_totp(self) -> bool:
        """Whether this password has TOTP configured."""
        return bool(self._totp_secret_encrypted)


class PasswordReveal(PasswordPublic):
    """Password response model with decrypted password and TOTP secret."""

    password: str
    totp_secret: str | None = None
    # Current TOTP code (if totp_secret is present)
    totp_code: str | None = None
    # Seconds remaining until code expires
    totp_time_remaining: int | None = None
