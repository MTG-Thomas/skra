"""
Integration tests for the expiration projection read path (issue #136).

Proves the projection-backed find functions return exactly what the
legacy full scanner returns on the same fixture data (backfill +
hooks keep them converged), and that the projection query honors the
active-type filter. Fixture covers upcoming, expired, out-of-window,
blank, unparseable, and disabled-asset rows.

Uses the truncating clean_db fixture: the backfill job commits, so the
rollback-only db_session fixture cannot isolate these tests.
"""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm.custom_asset import CustomAsset
from src.models.orm.custom_asset_type import CustomAssetType
from src.models.orm.organization import Organization
from src.models.orm.user_favorite import UserFavorite  # noqa: F401 (mapper registration)
from src.repositories.custom_asset import CustomAssetRepository
from src.repositories.custom_asset_type import CustomAssetTypeRepository
from src.repositories.expiration_projection import ExpirationProjectionRepository
from src.repositories.organization import OrganizationRepository
from src.services.expiration import (
    find_global_upcoming_expirations,
    find_global_upcoming_expirations_projected,
    find_upcoming_expirations,
    find_upcoming_expirations_projected,
)
from src.services.expiration_projection import backfill_all_projections


@pytest.mark.integration
class TestExpirationProjectionReads:
    """Scanner-vs-projection equivalence on shared fixture data."""

    @pytest_asyncio.fixture
    async def org(self, clean_db: AsyncSession) -> Organization:
        repo = OrganizationRepository(clean_db)
        return await repo.create(Organization(name=f"Proj Org {uuid4()}"))

    @pytest_asyncio.fixture
    async def other_org(self, clean_db: AsyncSession) -> Organization:
        repo = OrganizationRepository(clean_db)
        return await repo.create(Organization(name=f"Proj Other Org {uuid4()}"))

    @pytest_asyncio.fixture
    async def asset_type(self, clean_db: AsyncSession) -> CustomAssetType:
        repo = CustomAssetTypeRepository(clean_db)
        return await repo.create(
            CustomAssetType(
                name=f"Cert {uuid4()}",
                display_field_key="domain",
                fields=[
                    {
                        "id": "fld-domain",
                        "key": "domain",
                        "name": "Domain",
                        "type": "text",
                    },
                    {
                        "id": "fld-expiry",
                        "key": "expiry",
                        "name": "Expiry",
                        "type": "date",
                        "expiration_alert": True,
                    },
                ],
            )
        )

    async def _asset(
        self,
        session: AsyncSession,
        org_id: UUID,
        type_id: UUID,
        values: dict,
        *,
        is_enabled: bool = True,
    ) -> CustomAsset:
        repo = CustomAssetRepository(session)
        return await repo.create(
            CustomAsset(
                organization_id=org_id,
                custom_asset_type_id=type_id,
                values=values,
                is_enabled=is_enabled,
            )
        )

    @pytest_asyncio.fixture
    async def seeded(self, clean_db: AsyncSession, org, other_org, asset_type) -> dict:
        """Seed the full matrix and backfill the projection."""
        today = datetime.now(UTC).date()

        def iso(delta_days: int) -> str:
            return (today + timedelta(days=delta_days)).isoformat()

        await self._asset(
            clean_db,
            org.id,
            asset_type.id,
            {"fld-domain": "upcoming.example.com", "fld-expiry": iso(5)},
        )
        await self._asset(
            clean_db,
            org.id,
            asset_type.id,
            {"fld-domain": "expired.example.com", "fld-expiry": iso(-3)},
        )
        await self._asset(
            clean_db,
            org.id,
            asset_type.id,
            {"fld-domain": "far.example.com", "fld-expiry": iso(120)},
        )
        await self._asset(
            clean_db,
            org.id,
            asset_type.id,
            {"fld-domain": "blank.example.com", "fld-expiry": ""},
        )
        await self._asset(
            clean_db,
            org.id,
            asset_type.id,
            {"fld-domain": "bad.example.com", "fld-expiry": "not-a-date"},
        )
        await self._asset(
            clean_db,
            org.id,
            asset_type.id,
            {"fld-domain": "disabled.example.com", "fld-expiry": iso(9)},
            is_enabled=False,
        )
        await self._asset(
            clean_db,
            other_org.id,
            asset_type.id,
            {"fld-domain": "other.example.com", "fld-expiry": iso(2)},
        )
        await clean_db.commit()
        result = await backfill_all_projections(clean_db, page_size=50)
        await clean_db.commit()
        assert result["assets"] == 7
        return {"today": today}

    def _key(self, item) -> tuple:
        return (
            str(item.organization_id),
            str(item.asset_id),
            item.field_key,
            item.expires_on,
            item.days_until,
            item.window_days,
            item.asset_display,
        )

    async def test_org_read_matches_scanner(self, clean_db: AsyncSession, org, seeded) -> None:
        today: date = seeded["today"]
        scanned = await find_upcoming_expirations(clean_db, org.id, within_days=30, today=today)
        projected = await find_upcoming_expirations_projected(
            clean_db, org.id, within_days=30, today=today
        )
        assert [self._key(i) for i in projected] == [self._key(i) for i in scanned]
        # upcoming + expired + disabled-asset rows; far/blank/bad excluded.
        assert len(projected) == 3
        assert {i.asset_display for i in projected} == {
            "upcoming.example.com",
            "expired.example.com",
            "disabled.example.com",
        }

    async def test_global_read_matches_scanner(
        self, clean_db: AsyncSession, org, other_org, seeded
    ) -> None:
        today: date = seeded["today"]
        scanned = await find_global_upcoming_expirations(
            clean_db, [org.id, other_org.id], within_days=30, today=today
        )
        projected = await find_global_upcoming_expirations_projected(
            clean_db, [org.id, other_org.id], within_days=30, today=today
        )
        assert [self._key(i) for i in projected] == [self._key(i) for i in scanned]
        assert len(projected) == 4

    async def test_deactivated_type_hidden_from_projection_read(
        self, clean_db: AsyncSession, org, asset_type, seeded
    ) -> None:
        today: date = seeded["today"]
        type_repo = CustomAssetTypeRepository(clean_db)
        await type_repo.deactivate(asset_type.id)
        await clean_db.commit()

        projected = await find_upcoming_expirations_projected(
            clean_db, org.id, within_days=30, today=today
        )
        assert projected == []
        # Reactivate restores reads without a backfill rerun.
        await type_repo.activate(asset_type.id)
        await clean_db.commit()
        projected = await find_upcoming_expirations_projected(
            clean_db, org.id, within_days=30, today=today
        )
        assert len(projected) == 3

    async def test_empty_org_list_reads_nothing(self, clean_db: AsyncSession, seeded) -> None:
        today: date = seeded["today"]
        assert (
            await find_global_upcoming_expirations_projected(
                clean_db, [], within_days=30, today=today
            )
        ) == []
        rows = await ExpirationProjectionRepository(clean_db).query_upcoming([], today)
        assert rows == []
