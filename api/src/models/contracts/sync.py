"""Sync provenance metadata contracts."""

from datetime import datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class SyncMetadata(BaseModel):
    """Non-secret provenance and sync state for imported/synced records."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source_system: str
    source_tenant_id: str
    external_id: str = Field(validation_alias=AliasChoices("external_id", "source_record_id"))
    last_synced_at: datetime = Field(validation_alias=AliasChoices("last_synced_at", "observed_at"))
    sync_status: str
    sync_hash: str = Field(validation_alias=AliasChoices("sync_hash", "payload_hash"))
    source_url: str | None = None


def sync_metadata_to_storage(metadata: SyncMetadata | None) -> dict | None:
    """Convert sync metadata into a JSONB-safe storage dict."""
    if metadata is None:
        return None
    return metadata.model_dump(mode="json")


def sync_metadata_to_response(value: object) -> SyncMetadata | None:
    """Validate stored sync metadata for API responses.

    Returns a validated model when the stored value is a non-empty dict
    (passing through values that are already validated), else None so
    absent provenance serializes as null.
    """
    if isinstance(value, SyncMetadata):
        return value
    if isinstance(value, dict) and value:
        return SyncMetadata.model_validate(value)
    return None
