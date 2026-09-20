"""Location contracts (API request/response schemas)."""

from pydantic import BaseModel, Field

from src.models.contracts.base import PublicEntityBase
from src.models.contracts.sync import SyncMetadata


class LocationCreate(BaseModel):
    """Location creation request model."""

    name: str = Field(..., min_length=1, max_length=255)
    notes: str | None = None
    metadata: dict | None = None
    sync_metadata: SyncMetadata | None = None
    is_enabled: bool | None = None  # Defaults to True if not provided
    address_1: str | None = Field(None, max_length=255)
    address_2: str | None = Field(None, max_length=255)
    city: str | None = Field(None, max_length=100)
    region: str | None = Field(None, max_length=100)
    postal_code: str | None = Field(None, max_length=20)
    country: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=50)


class LocationUpdate(BaseModel):
    """Location update request model."""

    name: str | None = Field(None, min_length=1, max_length=255)
    notes: str | None = None
    metadata: dict | None = None
    sync_metadata: SyncMetadata | None = None
    is_enabled: bool | None = None  # Don't change if not provided
    address_1: str | None = Field(None, max_length=255)
    address_2: str | None = Field(None, max_length=255)
    city: str | None = Field(None, max_length=100)
    region: str | None = Field(None, max_length=100)
    postal_code: str | None = Field(None, max_length=20)
    country: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=50)


class LocationPublic(PublicEntityBase):
    """Location public response model."""

    name: str
    notes: str | None = None
    sync_metadata: SyncMetadata | None = None
    address_1: str | None = None
    address_2: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str | None = None
    phone: str | None = None
    updated_by_user_id: str | None = None
    updated_by_user_name: str | None = None
