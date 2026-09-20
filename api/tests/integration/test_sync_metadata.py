"""Integration tests for Docs-owned sync provenance (issue #34).

Round-trips sync_metadata through the real migrated schema for the core
synced entity types, and proves provenance rows stay org-scoped.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

# Register UserFavorite for User.favorites relationship resolution.
import src.models.orm.user_favorite  # noqa: F401,E402
from src.models.orm.document import Document
from src.models.orm.location import Location
from src.models.orm.organization import Organization
from src.models.orm.password import Password
from src.repositories.document import DocumentRepository
from src.repositories.location import LocationRepository
from src.repositories.organization import OrganizationRepository
from src.repositories.password import PasswordRepository

SYNC_METADATA = {
    "source_system": "itglue",
    "source_tenant_id": "tenant-123",
    "external_id": "ext-001",
    "last_synced_at": "2026-09-19T00:00:00Z",
    "sync_status": "synced",
    "sync_hash": "sha256:abc123",
}


@pytest_asyncio.fixture
async def test_org(db_session: AsyncSession) -> Organization:
    """Create a test organization."""
    org_repo = OrganizationRepository(db_session)
    org = Organization(name=f"Test Org {uuid4()}")
    return await org_repo.create(org)


@pytest_asyncio.fixture
async def other_org(db_session: AsyncSession) -> Organization:
    """Create another organization for isolation tests."""
    org_repo = OrganizationRepository(db_session)
    org = Organization(name=f"Other Org {uuid4()}")
    return await org_repo.create(org)


@pytest.mark.integration
class TestSyncMetadataRoundTrip:
    """sync_metadata persists canonically per entity type."""

    async def test_organization_round_trip(
        self, db_session: AsyncSession, test_org: Organization
    ) -> None:
        """Organization provenance survives a write/read cycle."""
        org_repo = OrganizationRepository(db_session)
        test_org.sync_metadata = dict(SYNC_METADATA)
        await org_repo.update(test_org)

        fetched = await org_repo.get_by_id(test_org.id)

        assert fetched is not None
        assert fetched.sync_metadata is not None
        assert fetched.sync_metadata["external_id"] == "ext-001"
        assert fetched.sync_metadata["source_system"] == "itglue"

    async def test_location_round_trip(
        self, db_session: AsyncSession, test_org: Organization
    ) -> None:
        """Location provenance survives a write/read cycle."""
        repo = LocationRepository(db_session)
        location = await repo.create(
            Location(
                organization_id=test_org.id,
                name="HQ",
                sync_metadata=dict(SYNC_METADATA),
            )
        )

        fetched = await repo.get_by_id_and_organization(location.id, test_org.id)

        assert fetched is not None
        assert fetched.sync_metadata is not None
        assert fetched.sync_metadata["sync_hash"] == "sha256:abc123"

    async def test_document_round_trip(
        self, db_session: AsyncSession, test_org: Organization
    ) -> None:
        """Document provenance survives a write/read cycle."""
        repo = DocumentRepository(db_session)
        doc = await repo.create(
            Document(
                organization_id=test_org.id,
                path="/Runbooks",
                name="VPN",
                content="",
                sync_metadata=dict(SYNC_METADATA),
            )
        )

        fetched = await repo.get_by_id_and_org(doc.id, test_org.id)

        assert fetched is not None
        assert fetched.sync_metadata is not None
        assert fetched.sync_metadata["source_tenant_id"] == "tenant-123"

    async def test_password_round_trip_without_secret_material(
        self, db_session: AsyncSession, test_org: Organization
    ) -> None:
        """Password provenance persists alongside (not inside) secrets."""
        repo = PasswordRepository(db_session)
        password = await repo.create(
            Password(
                organization_id=test_org.id,
                name="Admin",
                password_encrypted="encrypted-placeholder",
                sync_metadata=dict(SYNC_METADATA),
            )
        )

        fetched = await repo.get_by_id_and_org(password.id, test_org.id)

        assert fetched is not None
        assert fetched.sync_metadata is not None
        assert fetched.sync_metadata["external_id"] == "ext-001"
        assert "encrypted-placeholder" not in str(fetched.sync_metadata)

    async def test_provenance_does_not_leak_across_orgs(
        self,
        db_session: AsyncSession,
        test_org: Organization,
        other_org: Organization,
    ) -> None:
        """Org-scoped reads never expose another org's provenanced rows."""
        repo = LocationRepository(db_session)
        location = await repo.create(
            Location(
                organization_id=test_org.id,
                name="HQ",
                sync_metadata=dict(SYNC_METADATA),
            )
        )

        assert await repo.get_by_id_and_organization(location.id, other_org.id) is None
