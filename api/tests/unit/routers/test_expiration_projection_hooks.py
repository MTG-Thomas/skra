"""Router hook tests for the expiration projection (issue #136, stage 1B).

Proves the custom-asset create path refreshes the projection in the
same database session: the real refresh/project code runs against a
mocked projection repository, and the repository must receive the
request's session so request commit stays atomic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.core.auth import UserPrincipal
from src.models.contracts.custom_asset import CustomAssetCreate
from src.models.enums import UserRole
from src.routers import custom_assets

ORG_ID = uuid4()
TYPE_ID = uuid4()
ASSET_ID = uuid4()
FIELD_ID = str(uuid4())


def _user() -> UserPrincipal:
    return UserPrincipal(
        user_id=uuid4(),
        email="test@example.com",
        name="Test User",
        role=UserRole.CONTRIBUTOR,
        is_active=True,
        is_verified=True,
    )


def _asset_type():
    return SimpleNamespace(
        id=TYPE_ID,
        name="SSL Certificate",
        fields=[
            {
                "id": FIELD_ID,
                "key": "expires_on",
                "name": "Expires On",
                "type": "date",
                "expiration_alert": True,
            },
            {
                "id": str(uuid4()),
                "key": "name",
                "name": "Name",
                "type": "text",
                "expiration_alert": False,
            },
        ],
        display_field_key="name",
    )


def _stored_asset():
    return SimpleNamespace(
        id=ASSET_ID,
        organization_id=ORG_ID,
        custom_asset_type_id=TYPE_ID,
        values={FIELD_ID: "2026-10-05"},
        metadata_={},
        sync_metadata=None,
        is_enabled=True,
        created_at=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
        updated_by_user_id=None,
        updated_by_user=None,
    )


@pytest.mark.asyncio
async def test_create_refreshes_projection_in_request_session():
    """Create runs the real projector with the request's db session."""
    db = AsyncMock()
    asset_type = _asset_type()
    asset = _stored_asset()

    type_repo = AsyncMock()
    type_repo.get_by_id = AsyncMock(return_value=asset_type)
    asset_repo = AsyncMock()
    asset_repo.create = AsyncMock(return_value=asset)
    proj_repo = AsyncMock()
    proj_repo.upsert_row = AsyncMock()
    proj_repo.delete_stale_for_asset = AsyncMock(return_value=0)
    audit = AsyncMock()
    audit.log = AsyncMock()

    with (
        patch.object(custom_assets, "CustomAssetTypeRepository", return_value=type_repo),
        patch.object(custom_assets, "CustomAssetRepository", return_value=asset_repo),
        patch.object(
            custom_assets, "ExpirationProjectionRepository", return_value=proj_repo
        ) as proj_cls,
        patch.object(custom_assets, "get_audit_service", return_value=audit),
        patch.object(custom_assets, "index_entity_for_search", new=AsyncMock()),
    ):
        public = await custom_assets.create_custom_asset(
            ORG_ID,
            TYPE_ID,
            CustomAssetCreate(values={"expires_on": "2026-10-05"}),
            _user(),
            db,
        )

    # Same session reaches the projection repository: one transaction.
    proj_cls.assert_called_once_with(db)
    proj_repo.upsert_row.assert_awaited_once()
    kwargs = proj_repo.upsert_row.await_args.kwargs
    assert kwargs["asset_id"] == ASSET_ID
    assert kwargs["organization_id"] == ORG_ID
    assert kwargs["field_id"] == FIELD_ID
    assert kwargs["field_key"] == "expires_on"
    assert kwargs["expires_on"] == date(2026, 10, 5)
    assert kwargs["is_asset_enabled"] is True
    proj_repo.delete_stale_for_asset.assert_awaited_once_with(ASSET_ID, {FIELD_ID})
    # Response contract unchanged.
    assert str(public.id) == str(ASSET_ID)
