"""
Integration tests for checklist/SOP custom asset endpoints (issue #37).

Calls the router create/update functions directly with a real database
session: server-owned completion stamps on create, item-level merge with
row locking on update, and client-supplied stamps being ignored. HTTP
wiring for the same flows is covered by the Playwright spec
(client/e2e/tests/checklist.spec.ts).
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import UserPrincipal
from src.models.contracts.custom_asset import CustomAssetCreate, CustomAssetUpdate
from src.models.enums import UserRole
from src.models.orm.custom_asset_type import CustomAssetType
from src.models.orm.organization import Organization
from src.models.orm.user import User
from src.routers.custom_assets import create_custom_asset, update_custom_asset


@pytest_asyncio.fixture
async def contributor():
    return UserPrincipal(
        user_id=uuid4(),
        email="checklist-tech@example.com",
        name="Checklist Tech",
        role=UserRole.CONTRIBUTOR,
        is_active=True,
        is_verified=True,
    )


@pytest_asyncio.fixture
async def sop_setup(clean_db: AsyncSession, contributor):
    """Persisted user row (audit FK), org, and checklist-only asset type."""
    clean_db.add(
        User(
            id=contributor.user_id,
            email=contributor.email,
            name=contributor.name,
            role=contributor.role,
            is_active=True,
            is_verified=True,
        )
    )
    org = Organization(name=f"SOP Org {uuid4()}")
    clean_db.add(org)
    await clean_db.flush()
    asset_type = CustomAssetType(
        name=f"SOP Type {uuid4()}",
        fields=[
            {
                "id": "fld-steps",
                "key": "sop",
                "name": "Procedure",
                "type": "checklist",
                "show_in_list": True,
                "checklist_items": [
                    {"id": "s1", "label": "First step"},
                    {"id": "s2", "label": "Second step", "required": True},
                ],
            }
        ],
    )
    clean_db.add(asset_type)
    await clean_db.commit()
    return org, asset_type


@pytest.mark.integration
class TestChecklistAssetEndpoints:
    async def test_create_stamps_completion_and_ignores_client_stamps(
        self, clean_db: AsyncSession, sop_setup, contributor
    ):
        """Create stamps newly completed items with the acting user and
        server time; forged client stamps are overwritten."""
        org, asset_type = sop_setup
        before = datetime.now(UTC)
        created = await create_custom_asset(
            org.id,
            asset_type.id,
            CustomAssetCreate(
                values={
                    "sop": {
                        "items": [
                            {
                                "id": "s1",
                                "completed": True,
                                "completed_by": "attacker",
                                "completed_at": "2000-01-01T00:00:00+00:00",
                            }
                        ]
                    }
                }
            ),
            contributor,
            clean_db,
        )
        (entry,) = [e for e in created.values["sop"]["items"] if e["id"] == "s1"]
        assert entry["completed"] is True
        assert entry["completed_by"] == str(contributor.user_id)
        stamped_at = datetime.fromisoformat(entry["completed_at"])
        assert before <= stamped_at <= datetime.now(UTC)

    async def test_create_initializes_empty_checklist(
        self, clean_db: AsyncSession, sop_setup, contributor
    ):
        """Omitting the checklist key still stores an empty state."""
        org, asset_type = sop_setup
        created = await create_custom_asset(
            org.id, asset_type.id, CustomAssetCreate(values={}), contributor, clean_db
        )
        assert created.values["sop"] == {"items": []}

    async def test_update_toggle_stamps_and_preserves_concurrent_item(
        self, clean_db: AsyncSession, sop_setup, contributor
    ):
        """Toggling one item stamps it with the acting user while the
        other item's stored state survives (row lock + item-level merge)."""
        org, asset_type = sop_setup
        created = await create_custom_asset(
            org.id,
            asset_type.id,
            CustomAssetCreate(values={"sop": {"items": [{"id": "s1", "completed": True}]}}),
            contributor,
            clean_db,
        )

        updated = await update_custom_asset(
            org.id,
            asset_type.id,
            created.id,
            CustomAssetUpdate(values={"sop": {"items": [{"id": "s2", "completed": True}]}}),
            contributor,
            clean_db,
        )
        by_id = {e["id"]: e for e in updated.values["sop"]["items"]}
        # Untouched item keeps its earlier server stamp.
        assert by_id["s1"]["completed"] is True
        assert by_id["s1"]["completed_by"] == str(contributor.user_id)
        assert "completed_at" in by_id["s1"]
        # Toggled item is freshly stamped.
        assert by_id["s2"]["completed"] is True
        assert by_id["s2"]["completed_by"] == str(contributor.user_id)
        assert "completed_at" in by_id["s2"]

    async def test_update_rejects_unknown_item(
        self, clean_db: AsyncSession, sop_setup, contributor
    ):
        """Checklist validation still applies on partial updates."""
        org, asset_type = sop_setup
        created = await create_custom_asset(
            org.id, asset_type.id, CustomAssetCreate(values={}), contributor, clean_db
        )

        with pytest.raises(HTTPException) as exc_info:
            await update_custom_asset(
                org.id,
                asset_type.id,
                created.id,
                CustomAssetUpdate(values={"sop": {"items": [{"id": "nope", "completed": True}]}}),
                contributor,
                clean_db,
            )
        assert exc_info.value.status_code == 422
