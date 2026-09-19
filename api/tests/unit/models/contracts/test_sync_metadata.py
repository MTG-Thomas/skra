"""Tests for sync provenance metadata contracts."""

from datetime import UTC, datetime
from typing import TypeVar
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from src.models.contracts.configuration import ConfigurationPublic
from src.models.contracts.custom_asset import CustomAssetPublic
from src.models.contracts.document import (
    DocumentCreate,
    DocumentPublic,
    DocumentUpdate,
)
from src.models.contracts.location import (
    LocationCreate,
    LocationPublic,
    LocationUpdate,
)
from src.models.contracts.organization import (
    OrganizationCreate,
    OrganizationPublic,
    OrganizationUpdate,
)
from src.models.contracts.password import (
    PasswordCreate,
    PasswordPublic,
    PasswordUpdate,
)
from src.models.contracts.sync import SyncMetadata, sync_metadata_to_storage


def test_sync_metadata_accepts_plan_fields() -> None:
    """Sync metadata stores the plan's source/provenance fields."""
    synced_at = datetime.now(UTC)

    metadata = SyncMetadata(
        source_system="itglue",
        source_tenant_id="tenant-123",
        external_id="config-456",
        last_synced_at=synced_at,
        sync_status="synced",
        sync_hash="sha256:abc123",
        source_url="https://example.test/configs/456",
    )

    assert metadata.source_system == "itglue"
    assert metadata.source_tenant_id == "tenant-123"
    assert metadata.external_id == "config-456"
    assert metadata.last_synced_at == synced_at
    assert metadata.sync_status == "synced"
    assert metadata.sync_hash == "sha256:abc123"
    assert metadata.source_url == "https://example.test/configs/456"


def test_sync_metadata_accepts_source_record_aliases() -> None:
    """Older source-record names are normalized to the Docs sync fields."""
    observed_at = datetime.now(UTC)

    metadata = SyncMetadata.model_validate(
        {
            "source_system": "bifrost",
            "source_tenant_id": "tenant-123",
            "source_record_id": "asset-789",
            "observed_at": observed_at,
            "sync_status": "observed",
            "payload_hash": "hash-from-payload",
        }
    )

    assert metadata.external_id == "asset-789"
    assert metadata.last_synced_at == observed_at
    assert metadata.sync_hash == "hash-from-payload"
    assert "source_record_id" not in metadata.model_dump()
    assert "observed_at" not in metadata.model_dump()
    assert "payload_hash" not in metadata.model_dump()


def test_sync_metadata_requires_identifying_fields() -> None:
    """A provenance record must identify the source, record, state, and hash."""
    with pytest.raises(ValidationError):
        SyncMetadata.model_validate({"source_system": "itglue"})


def test_sync_metadata_storage_shape_is_json_safe() -> None:
    """Sync metadata is stored with canonical field names and JSON-safe datetimes."""
    synced_at = datetime.now(UTC)

    metadata = SyncMetadata(
        source_system="itglue",
        source_tenant_id="tenant-123",
        external_id="config-456",
        last_synced_at=synced_at,
        sync_status="synced",
        sync_hash="sha256:abc123",
    )

    storage = sync_metadata_to_storage(metadata)

    assert storage == {
        "source_system": "itglue",
        "source_tenant_id": "tenant-123",
        "external_id": "config-456",
        "last_synced_at": synced_at.isoformat().replace("+00:00", "Z"),
        "sync_status": "synced",
        "sync_hash": "sha256:abc123",
        "source_url": None,
    }


def test_configuration_public_exposes_sync_metadata_from_orm_attribute() -> None:
    """Configuration responses expose non-secret sync provenance."""
    now = datetime.now(UTC)

    class FakeConfiguration:
        id = uuid4()
        organization_id = uuid4()
        configuration_type_id = None
        configuration_status_id = None
        name = "Firewall"
        serial_number = None
        asset_tag = None
        manufacturer = None
        model = None
        ip_address = None
        mac_address = None
        notes = None
        interfaces = []
        is_enabled = True
        created_at = now
        updated_at = now
        metadata_ = {}
        sync_metadata = {
            "source_system": "itglue",
            "source_tenant_id": "tenant-123",
            "external_id": "config-456",
            "last_synced_at": now,
            "sync_status": "synced",
            "sync_hash": "sha256:abc123",
        }

    public = ConfigurationPublic.model_validate(FakeConfiguration())

    assert public.sync_metadata is not None
    assert public.sync_metadata.external_id == "config-456"
    assert public.model_dump()["sync_metadata"]["source_system"] == "itglue"


def test_custom_asset_public_exposes_sync_metadata_from_orm_attribute() -> None:
    """Custom asset responses expose non-secret sync provenance."""
    now = datetime.now(UTC)

    class FakeCustomAsset:
        id = uuid4()
        organization_id = uuid4()
        custom_asset_type_id = str(uuid4())
        values = {"name": "Tenant"}
        is_enabled = True
        created_at = now
        updated_at = now
        metadata_ = {}
        sync_metadata = {
            "source_system": "halo",
            "source_tenant_id": "tenant-abc",
            "external_id": "asset-789",
            "last_synced_at": now,
            "sync_status": "synced",
            "sync_hash": "sha256:def456",
        }

    public = CustomAssetPublic.model_validate(FakeCustomAsset())

    assert public.sync_metadata is not None
    assert public.sync_metadata.source_system == "halo"
    assert public.model_dump()["sync_metadata"]["external_id"] == "asset-789"


SYNC_ATTRS = {
    "source_system": "itglue",
    "source_tenant_id": "tenant-123",
    "external_id": "ext-001",
    "last_synced_at": datetime.now(UTC),
    "sync_status": "synced",
    "sync_hash": "sha256:abc123",
}


def _base_attrs(**overrides: object) -> dict[str, object]:
    now = datetime.now(UTC)
    attrs: dict[str, object] = {
        "id": uuid4(),
        "organization_id": uuid4(),
        "is_enabled": True,
        "created_at": now,
        "updated_at": now,
        "metadata_": {},
        "sync_metadata": dict(SYNC_ATTRS),
    }
    attrs.update(overrides)
    return attrs


T = TypeVar("T", bound=BaseModel)


def _public_from_attrs(public_cls: type[T], attrs: dict[str, object]) -> T:
    fake = type("FakeOrm", (), attrs)()
    return public_cls.model_validate(fake)


def test_organization_public_exposes_sync_metadata() -> None:
    """Organization responses expose non-secret sync provenance (issue #34)."""
    public = _public_from_attrs(OrganizationPublic, _base_attrs(name="Acme"))

    assert public.sync_metadata is not None
    assert public.sync_metadata.external_id == "ext-001"


def test_location_public_exposes_sync_metadata() -> None:
    """Location responses expose non-secret sync provenance (issue #34)."""
    public = _public_from_attrs(LocationPublic, _base_attrs(name="HQ"))

    assert public.sync_metadata is not None
    assert public.sync_metadata.source_system == "itglue"


def test_document_public_exposes_sync_metadata() -> None:
    """Document responses expose non-secret sync provenance (issue #34)."""
    public = _public_from_attrs(
        DocumentPublic, _base_attrs(path="/Runbooks", name="VPN", content="")
    )

    assert public.sync_metadata is not None
    assert public.sync_metadata.sync_hash == "sha256:abc123"


def test_password_public_exposes_sync_metadata_without_secrets() -> None:
    """Password responses expose provenance but never secret material (issue #34)."""
    public = _public_from_attrs(PasswordPublic, _base_attrs(name="Admin"))

    assert public.sync_metadata is not None
    assert public.sync_metadata.external_id == "ext-001"
    assert not hasattr(public, "password")


def test_public_contracts_default_sync_metadata_to_none() -> None:
    """Entities without provenance serialize sync_metadata as null."""
    for public_cls, extra in [
        (OrganizationPublic, {"name": "Acme"}),
        (LocationPublic, {"name": "HQ"}),
        (DocumentPublic, {"path": "/R", "name": "D", "content": ""}),
        (PasswordPublic, {"name": "P"}),
    ]:
        attrs = _base_attrs(**extra)
        attrs["sync_metadata"] = None
        public = _public_from_attrs(public_cls, attrs)

        assert public.sync_metadata is None


def test_create_update_contracts_accept_sync_metadata() -> None:
    """Write contracts accept provenance for later migrator use (issue #34)."""
    payload = {"sync_metadata": dict(SYNC_ATTRS)}

    assert OrganizationCreate(name="Acme", **payload).sync_metadata is not None
    assert OrganizationUpdate(**payload).sync_metadata is not None
    assert LocationCreate(name="HQ", **payload).sync_metadata is not None
    assert LocationUpdate(**payload).sync_metadata is not None
    assert DocumentCreate(path="/R", name="D", **payload).sync_metadata is not None
    assert DocumentUpdate(**payload).sync_metadata is not None
    assert PasswordCreate(name="P", password="secret", **payload).sync_metadata is not None
    assert PasswordUpdate(**payload).sync_metadata is not None
