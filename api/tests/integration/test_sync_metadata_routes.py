"""Router-level provenance round trips with mocked repositories (issue #34).

Proves sync_metadata flows through create/update/get responses for the
core synced entity types, and serializes as null when absent.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.core.auth import UserPrincipal, get_current_active_user
from src.main import app
from src.models.enums import UserRole
from src.models.orm.document import Document
from src.models.orm.location import Location
from src.models.orm.organization import Organization
from src.models.orm.password import Password

SYNC_METADATA = {
    "source_system": "itglue",
    "source_tenant_id": "tenant-123",
    "external_id": "ext-001",
    "last_synced_at": "2026-09-19T00:00:00Z",
    "sync_status": "synced",
    "sync_hash": "sha256:abc123",
}


def _mock_user(role: UserRole = UserRole.CONTRIBUTOR) -> UserPrincipal:
    return UserPrincipal(
        user_id=uuid4(),
        email="test@example.com",
        name="Test User",
        role=role,
        is_active=True,
        is_verified=True,
    )


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@contextmanager
def _patched_passwords_side_effects():
    audit_service = MagicMock()
    audit_service.log = AsyncMock()
    with (
        patch("src.routers.passwords.get_audit_service", return_value=audit_service),
        patch("src.routers.passwords.index_entity_for_search", new=AsyncMock()),
        patch("src.routers.passwords.remove_entity_from_search", new=AsyncMock()),
        patch("src.routers.passwords.decrypt_secret", return_value="secret123"),
    ):
        yield


@contextmanager
def _patched_documents_side_effects():
    audit_service = MagicMock()
    audit_service.log = AsyncMock()
    with (
        patch("src.routers.documents.get_audit_service", return_value=audit_service),
        patch("src.routers.documents.index_entity_for_search", new=AsyncMock()),
    ):
        yield


@contextmanager
def _patched_locations_side_effects():
    audit_service = MagicMock()
    audit_service.log = AsyncMock()
    with (
        patch("src.routers.locations.get_audit_service", return_value=audit_service),
        patch("src.routers.locations.index_entity_for_search", new=AsyncMock()),
    ):
        yield


@contextmanager
def _patched_organizations_side_effects():
    audit_service = MagicMock()
    audit_service.log = AsyncMock()
    with patch("src.routers.organizations.get_audit_service", return_value=audit_service):
        yield


def _base_mock(spec: object, org_id: object) -> MagicMock:
    mock = MagicMock(spec=spec)
    mock.id = uuid4()
    mock.organization_id = org_id
    mock.is_enabled = True
    mock.created_at = datetime.now(UTC)
    mock.updated_at = datetime.now(UTC)
    mock.metadata_ = {}
    mock.sync_metadata = dict(SYNC_METADATA)
    mock.updated_by_user_id = None
    mock.updated_by_user = None
    return mock


@pytest.mark.integration
class TestLocationProvenanceRoutes:
    async def test_create_returns_provenance(self, client: AsyncClient) -> None:
        """POST stores canonical provenance and returns it (issue #34)."""
        app.dependency_overrides[get_current_active_user] = _mock_user
        org_id = uuid4()
        created = _base_mock(Location, org_id)
        created.name = "HQ"
        created.notes = None
        created.address_1 = None
        created.address_2 = None
        created.city = None
        created.region = None
        created.postal_code = None
        created.country = None
        created.phone = None
        repo = AsyncMock()
        repo.create = AsyncMock(return_value=created)
        try:
            with (
                patch("src.routers.locations.LocationRepository", return_value=repo),
                _patched_locations_side_effects(),
            ):
                response = await client.post(
                    f"/api/organizations/{org_id}/locations",
                    json={"name": "HQ", "sync_metadata": SYNC_METADATA},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 201
        stored = repo.create.call_args[0][0]
        assert stored.sync_metadata["external_id"] == "ext-001"
        assert stored.sync_metadata["last_synced_at"].endswith("Z")
        assert response.json()["sync_metadata"]["source_system"] == "itglue"

    async def test_update_returns_provenance(self, client: AsyncClient) -> None:
        """PUT replaces provenance and returns it."""
        app.dependency_overrides[get_current_active_user] = _mock_user
        org_id = uuid4()
        existing = _base_mock(Location, org_id)
        existing.name = "HQ"
        existing.notes = None
        existing.sync_metadata = None
        existing.address_1 = None
        existing.address_2 = None
        existing.city = None
        existing.region = None
        existing.postal_code = None
        existing.country = None
        existing.phone = None
        repo = AsyncMock()
        repo.get_by_id_and_organization = AsyncMock(return_value=existing)
        repo.update = AsyncMock(return_value=existing)
        try:
            with (
                patch("src.routers.locations.LocationRepository", return_value=repo),
                _patched_locations_side_effects(),
            ):
                response = await client.put(
                    f"/api/organizations/{org_id}/locations/{existing.id}",
                    json={"sync_metadata": SYNC_METADATA},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert existing.sync_metadata["external_id"] == "ext-001"
        assert response.json()["sync_metadata"]["external_id"] == "ext-001"

    async def test_get_without_provenance_returns_null(self, client: AsyncClient) -> None:
        """Absent provenance serializes as null, never fails the read."""
        app.dependency_overrides[get_current_active_user] = _mock_user
        org_id = uuid4()
        existing = _base_mock(Location, org_id)
        existing.name = "HQ"
        existing.notes = None
        existing.sync_metadata = None
        existing.address_1 = None
        existing.address_2 = None
        existing.city = None
        existing.region = None
        existing.postal_code = None
        existing.country = None
        existing.phone = None
        repo = AsyncMock()
        repo.get_by_id_and_organization = AsyncMock(return_value=existing)
        try:
            with (
                patch("src.routers.locations.LocationRepository", return_value=repo),
                _patched_locations_side_effects(),
            ):
                response = await client.get(f"/api/organizations/{org_id}/locations/{existing.id}")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["sync_metadata"] is None


@pytest.mark.integration
class TestDocumentProvenanceRoutes:
    async def test_create_returns_provenance(self, client: AsyncClient) -> None:
        """POST stores canonical provenance and returns it."""
        app.dependency_overrides[get_current_active_user] = _mock_user
        org_id = uuid4()
        created = _base_mock(Document, org_id)
        created.path = "/Runbooks"
        created.name = "VPN"
        created.content = ""
        repo = AsyncMock()
        repo.create = AsyncMock(return_value=created)
        try:
            with (
                patch("src.routers.documents.DocumentRepository", return_value=repo),
                _patched_documents_side_effects(),
            ):
                response = await client.post(
                    f"/api/organizations/{org_id}/documents",
                    json={
                        "path": "/Runbooks",
                        "name": "VPN",
                        "sync_metadata": SYNC_METADATA,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 201
        assert repo.create.call_args[0][0].sync_metadata["sync_hash"] == ("sha256:abc123")
        assert response.json()["sync_metadata"]["external_id"] == "ext-001"

    async def test_get_returns_provenance(self, client: AsyncClient) -> None:
        """GET exposes stored provenance."""
        app.dependency_overrides[get_current_active_user] = _mock_user
        org_id = uuid4()
        existing = _base_mock(Document, org_id)
        existing.path = "/Runbooks"
        existing.name = "VPN"
        existing.content = ""
        repo = AsyncMock()
        repo.get_by_id_and_org = AsyncMock(return_value=existing)
        try:
            with (
                patch("src.routers.documents.DocumentRepository", return_value=repo),
                _patched_documents_side_effects(),
            ):
                response = await client.get(f"/api/organizations/{org_id}/documents/{existing.id}")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["sync_metadata"]["source_system"] == "itglue"


@pytest.mark.integration
class TestPasswordProvenanceRoutes:
    async def test_create_returns_provenance_without_secrets(self, client: AsyncClient) -> None:
        """POST returns provenance but never secret material."""
        app.dependency_overrides[get_current_active_user] = _mock_user
        org_id = uuid4()
        created = _base_mock(Password, org_id)
        created.name = "Admin"
        created.username = None
        created.url = None
        created.notes = None
        created.totp_secret_encrypted = None
        repo = AsyncMock()
        repo.create = AsyncMock(return_value=created)
        try:
            with (
                patch("src.routers.passwords.PasswordRepository", return_value=repo),
                _patched_passwords_side_effects(),
            ):
                response = await client.post(
                    f"/api/organizations/{org_id}/passwords",
                    json={
                        "name": "Admin",
                        "password": "secret123",
                        "sync_metadata": SYNC_METADATA,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 201
        body = response.json()
        assert "password" not in body
        assert body["sync_metadata"]["external_id"] == "ext-001"

    async def test_reveal_includes_provenance(self, client: AsyncClient) -> None:
        """Reveal responses carry provenance unchanged."""
        app.dependency_overrides[get_current_active_user] = _mock_user
        org_id = uuid4()
        existing = _base_mock(Password, org_id)
        existing.name = "Admin"
        existing.username = None
        existing.url = None
        existing.notes = None
        existing.totp_secret_encrypted = None
        existing.password_encrypted = "encrypted-placeholder"
        repo = AsyncMock()
        repo.get_by_id_and_org = AsyncMock(return_value=existing)
        try:
            with (
                patch("src.routers.passwords.PasswordRepository", return_value=repo),
                _patched_passwords_side_effects(),
            ):
                response = await client.get(
                    f"/api/organizations/{org_id}/passwords/{existing.id}/reveal"
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["sync_metadata"]["external_id"] == "ext-001"


@pytest.mark.integration
class TestOrganizationProvenanceRoutes:
    async def test_create_returns_provenance(self, client: AsyncClient) -> None:
        """Admin-only POST stores and returns provenance."""
        app.dependency_overrides[get_current_active_user] = lambda: _mock_user(
            UserRole.ADMINISTRATOR
        )
        created = _base_mock(Organization, None)
        created.organization_id = None
        created.name = "Acme"
        repo = AsyncMock()
        repo.get_by_name = AsyncMock(return_value=None)
        repo.create = AsyncMock(return_value=created)
        try:
            with (
                patch(
                    "src.routers.organizations.OrganizationRepository",
                    return_value=repo,
                ),
                _patched_organizations_side_effects(),
            ):
                response = await client.post(
                    "/api/organizations",
                    json={"name": "Acme", "sync_metadata": SYNC_METADATA},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 201
        assert repo.create.call_args[0][0].sync_metadata["external_id"] == ("ext-001")
        assert response.json()["sync_metadata"]["source_system"] == "itglue"

    async def test_get_returns_provenance(self, client: AsyncClient) -> None:
        """GET exposes stored organization provenance."""
        app.dependency_overrides[get_current_active_user] = _mock_user
        existing = _base_mock(Organization, None)
        existing.organization_id = None
        existing.name = "Acme"
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=existing)
        try:
            with (
                patch(
                    "src.routers.organizations.OrganizationRepository",
                    return_value=repo,
                ),
                _patched_organizations_side_effects(),
            ):
                response = await client.get(f"/api/organizations/{existing.id}")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["sync_metadata"]["external_id"] == "ext-001"
