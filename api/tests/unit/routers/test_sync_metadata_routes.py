"""Router-level provenance read/write coverage (issue #34).

Calls route handlers directly with mocked repositories so Sonar unit
coverage counts the sync_metadata serialize and write-through branches.
"""

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.core.auth import UserPrincipal
from src.models.contracts.document import DocumentCreate
from src.models.contracts.location import LocationCreate, LocationUpdate
from src.models.contracts.organization import OrganizationCreate
from src.models.contracts.password import PasswordCreate, PasswordUpdate
from src.models.enums import UserRole
from src.routers import documents, locations, organizations, passwords

SYNC_METADATA = {
    "source_system": "itglue",
    "source_tenant_id": "tenant-123",
    "external_id": "ext-001",
    "last_synced_at": "2026-09-19T00:00:00Z",
    "sync_status": "synced",
    "sync_hash": "sha256:abc123",
}


def _persist(entity):
    """Mimic DB persistence for entities constructed by route handlers."""
    entity.id = uuid4()
    now = datetime.now(UTC)
    entity.created_at = now
    entity.updated_at = now
    return entity


def _user(role: UserRole = UserRole.CONTRIBUTOR) -> UserPrincipal:
    return UserPrincipal(
        user_id=uuid4(),
        email="test@example.com",
        name="Test User",
        role=role,
        is_active=True,
        is_verified=True,
    )


@contextmanager
def _patched_audit(module: str):
    """Patch audit logging in one router module."""
    audit_service = MagicMock()
    audit_service.log = AsyncMock()
    with patch(f"src.routers.{module}.get_audit_service", return_value=audit_service):
        yield


def _location_entity(org_id, **overrides):
    now = "2026-09-19T00:00:00Z"
    attrs = {
        "id": uuid4(),
        "organization_id": org_id,
        "name": "HQ",
        "notes": None,
        "metadata_": {},
        "sync_metadata": None,
        "is_enabled": True,
        "created_at": now,
        "updated_at": now,
        "address_1": None,
        "address_2": None,
        "city": None,
        "region": None,
        "postal_code": None,
        "country": None,
        "phone": None,
        "updated_by_user_id": None,
        "updated_by_user": None,
    }
    attrs.update(overrides)
    return SimpleNamespace(**attrs)


@pytest.mark.asyncio
async def test_create_location_stores_provenance():
    """POST writes canonical provenance and returns it."""
    org_id = uuid4()
    user = _user()
    repo = AsyncMock()
    repo.create = AsyncMock(side_effect=_persist)

    with (
        patch("src.routers.locations.LocationRepository", return_value=repo),
        _patched_audit("locations"),
        patch("src.routers.locations.index_entity_for_search", new=AsyncMock()),
    ):
        result = await locations.create_location(
            org_id,
            LocationCreate(name="HQ", sync_metadata=dict(SYNC_METADATA)),
            user,
            AsyncMock(),
        )

    stored = repo.create.call_args[0][0]
    assert stored.sync_metadata["external_id"] == "ext-001"
    assert result.sync_metadata is not None
    assert result.sync_metadata.source_system == "itglue"


@pytest.mark.asyncio
async def test_update_location_replaces_provenance():
    """PUT overwrites provenance and returns it."""
    org_id = uuid4()
    user = _user()
    entity = _location_entity(org_id)
    repo = AsyncMock()
    repo.get_by_id_and_organization = AsyncMock(return_value=entity)
    repo.update = AsyncMock(side_effect=lambda e: e)

    with (
        patch("src.routers.locations.LocationRepository", return_value=repo),
        _patched_audit("locations"),
        patch("src.routers.locations.index_entity_for_search", new=AsyncMock()),
    ):
        result = await locations.update_location(
            org_id,
            entity.id,
            LocationUpdate(sync_metadata=dict(SYNC_METADATA)),
            user,
            AsyncMock(),
        )

    assert entity.sync_metadata["external_id"] == "ext-001"
    assert result.sync_metadata is not None
    assert result.sync_metadata.external_id == "ext-001"


@pytest.mark.asyncio
async def test_get_location_without_provenance_returns_none():
    """Absent provenance serializes as null."""
    org_id = uuid4()
    entity = _location_entity(org_id)
    repo = AsyncMock()
    repo.get_by_id_and_organization = AsyncMock(return_value=entity)

    with patch("src.routers.locations.LocationRepository", return_value=repo):
        result = await locations.get_location(org_id, entity.id, _user(), AsyncMock())

    assert result.sync_metadata is None


def _document_entity(org_id, **overrides):
    now = "2026-09-19T00:00:00Z"
    attrs = {
        "id": uuid4(),
        "organization_id": org_id,
        "path": "/Runbooks",
        "name": "VPN",
        "content": "",
        "metadata_": {},
        "sync_metadata": None,
        "is_enabled": True,
        "created_at": now,
        "updated_at": now,
        "updated_by_user_id": None,
        "updated_by_user": None,
    }
    attrs.update(overrides)
    return SimpleNamespace(**attrs)


@pytest.mark.asyncio
async def test_create_document_stores_provenance():
    """POST writes canonical provenance and returns it."""
    org_id = uuid4()
    user = _user()
    repo = AsyncMock()
    repo.create = AsyncMock(side_effect=_persist)

    with (
        patch("src.routers.documents.DocumentRepository", return_value=repo),
        _patched_audit("documents"),
        patch("src.routers.documents.index_entity_for_search", new=AsyncMock()),
    ):
        result = await documents.create_document(
            org_id,
            DocumentCreate(path="/Runbooks", name="VPN", sync_metadata=dict(SYNC_METADATA)),
            user,
            AsyncMock(),
        )

    assert repo.create.call_args[0][0].sync_metadata["sync_hash"] == "sha256:abc123"
    assert result.sync_metadata is not None
    assert result.sync_metadata.external_id == "ext-001"


@pytest.mark.asyncio
async def test_get_document_returns_provenance():
    """GET exposes stored provenance."""
    org_id = uuid4()
    entity = _document_entity(org_id, sync_metadata=dict(SYNC_METADATA))
    repo = AsyncMock()
    repo.get_by_id_and_org = AsyncMock(return_value=entity)

    with patch("src.routers.documents.DocumentRepository", return_value=repo):
        result = await documents.get_document(org_id, entity.id, _user(), AsyncMock())

    assert result.sync_metadata is not None
    assert result.sync_metadata.source_system == "itglue"


def _password_entity(org_id, **overrides):
    now = "2026-09-19T00:00:00Z"
    attrs = {
        "id": uuid4(),
        "organization_id": org_id,
        "name": "Admin",
        "username": None,
        "url": None,
        "notes": None,
        "password_encrypted": "encrypted-placeholder",
        "totp_secret_encrypted": None,
        "metadata_": {},
        "sync_metadata": None,
        "is_enabled": True,
        "created_at": now,
        "updated_at": now,
        "updated_by_user_id": None,
        "updated_by_user": None,
    }
    attrs.update(overrides)
    return SimpleNamespace(**attrs)


@pytest.mark.asyncio
async def test_create_password_returns_provenance_without_secrets():
    """POST returns provenance but never secret material."""
    org_id = uuid4()
    user = _user()
    repo = AsyncMock()
    repo.create = AsyncMock(side_effect=_persist)

    with (
        patch("src.routers.passwords.PasswordRepository", return_value=repo),
        _patched_audit("passwords"),
        patch("src.routers.passwords.index_entity_for_search", new=AsyncMock()),
        patch("src.routers.passwords.remove_entity_from_search", new=AsyncMock()),
    ):
        result = await passwords.create_password(
            org_id,
            PasswordCreate(
                name="Admin",
                password="secret123",
                sync_metadata=dict(SYNC_METADATA),
            ),
            user,
            AsyncMock(),
        )

    stored = repo.create.call_args[0][0]
    assert stored.sync_metadata["external_id"] == "ext-001"
    assert stored.password_encrypted != "secret123"
    assert result.sync_metadata is not None
    assert result.sync_metadata.external_id == "ext-001"


@pytest.mark.asyncio
async def test_update_password_replaces_provenance():
    """PUT overwrites provenance and returns it."""
    org_id = uuid4()
    user = _user()
    entity = _password_entity(org_id)
    repo = AsyncMock()
    repo.get_by_id_and_org = AsyncMock(return_value=entity)
    repo.update = AsyncMock(side_effect=lambda e: e)

    with (
        patch("src.routers.passwords.PasswordRepository", return_value=repo),
        _patched_audit("passwords"),
        patch("src.routers.passwords.index_entity_for_search", new=AsyncMock()),
    ):
        result = await passwords.update_password(
            org_id,
            entity.id,
            PasswordUpdate(sync_metadata=dict(SYNC_METADATA)),
            user,
            AsyncMock(),
        )

    assert entity.sync_metadata["external_id"] == "ext-001"
    assert result.sync_metadata is not None


@pytest.mark.asyncio
async def test_reveal_password_includes_provenance():
    """Reveal responses carry provenance unchanged."""
    org_id = uuid4()
    entity = _password_entity(org_id, sync_metadata=dict(SYNC_METADATA))
    repo = AsyncMock()
    repo.get_by_id_and_org = AsyncMock(return_value=entity)

    with (
        patch("src.routers.passwords.PasswordRepository", return_value=repo),
        _patched_audit("passwords"),
        patch("src.routers.passwords.decrypt_secret", return_value="secret123"),
    ):
        result = await passwords.reveal_password(org_id, entity.id, _user(), AsyncMock())

    assert result.password == "secret123"
    assert result.sync_metadata is not None
    assert result.sync_metadata.external_id == "ext-001"


def _organization_entity(**overrides):
    now = "2026-09-19T00:00:00Z"
    attrs = {
        "id": uuid4(),
        "name": "Acme",
        "metadata_": {},
        "sync_metadata": None,
        "is_enabled": True,
        "created_at": now,
        "updated_at": now,
        "updated_by_user_id": None,
        "updated_by_user": None,
    }
    attrs.update(overrides)
    return SimpleNamespace(**attrs)


@pytest.mark.asyncio
async def test_create_organization_stores_provenance():
    """Admin-only POST stores and returns provenance."""
    user = _user(UserRole.ADMINISTRATOR)
    entity = _organization_entity(sync_metadata=dict(SYNC_METADATA))
    repo = AsyncMock()
    repo.get_by_name = AsyncMock(return_value=None)
    repo.create = AsyncMock(return_value=entity)

    with (
        patch("src.routers.organizations.OrganizationRepository", return_value=repo),
        _patched_audit("organizations"),
    ):
        result = await organizations.create_organization(
            OrganizationCreate(name="Acme", sync_metadata=dict(SYNC_METADATA)),
            user,
            AsyncMock(),
        )

    assert repo.create.call_args[0][0].sync_metadata["external_id"] == "ext-001"
    assert result.sync_metadata is not None
    assert result.sync_metadata.source_system == "itglue"


@pytest.mark.asyncio
async def test_get_organization_returns_provenance():
    """GET exposes stored organization provenance."""
    entity = _organization_entity(sync_metadata=dict(SYNC_METADATA))
    repo = AsyncMock()
    repo.get_by_id = AsyncMock(return_value=entity)

    with patch("src.routers.organizations.OrganizationRepository", return_value=repo):
        result = await organizations.get_organization(entity.id, _user(), AsyncMock(), [])

    assert result.sync_metadata is not None
    assert result.sync_metadata.external_id == "ext-001"
