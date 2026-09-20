"""Router tests for upcoming expirations (issue #40)."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.core.auth import UserPrincipal
from src.models.enums import UserRole
from src.routers import organizations
from src.services.expiration import UpcomingExpiration


def _user() -> UserPrincipal:
    return UserPrincipal(
        user_id=uuid4(),
        email="test@example.com",
        name="Test User",
        role=UserRole.CONTRIBUTOR,
        is_active=True,
        is_verified=True,
    )


def _item(org_id, **overrides):
    base = {
        "organization_id": org_id,
        "asset_id": uuid4(),
        "asset_display": "Wildcard Cert",
        "asset_type_id": uuid4(),
        "asset_type_name": "SSL Certificate",
        "field_key": "expires_on",
        "field_name": "Expires On",
        "expires_on": date(2026, 9, 26),
        "days_until": 7,
        "window_days": 7,
    }
    base.update(overrides)
    return UpcomingExpiration(**base)


@pytest.mark.asyncio
async def test_get_upcoming_expirations_returns_items():
    """Org members see flagged expirations ordered by urgency."""
    org_id = uuid4()
    org_repo = AsyncMock()
    org_repo.get_by_id = AsyncMock(return_value=MagicMock(id=org_id))
    items = [_item(org_id), _item(org_id, days_until=1, window_days=1)]

    with (
        patch(
            "src.routers.organizations.OrganizationRepository",
            return_value=org_repo,
        ),
        patch(
            "src.routers.organizations.find_upcoming_expirations",
            new=AsyncMock(return_value=items),
        ),
    ):
        result = await organizations.get_upcoming_expirations(
            org_id, _user(), AsyncMock(), 30
        )

    assert result.total == 2
    assert result.within_days == 30
    assert result.items[0].field_key == "expires_on"
    assert result.items[0].window_days == 7


@pytest.mark.asyncio
async def test_get_upcoming_expirations_unknown_org_404s():
    """Unknown organizations fail closed."""
    from fastapi import HTTPException

    org_repo = AsyncMock()
    org_repo.get_by_id = AsyncMock(return_value=None)

    with patch(
        "src.routers.organizations.OrganizationRepository",
        return_value=org_repo,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await organizations.get_upcoming_expirations(
                uuid4(), _user(), AsyncMock(), 30
            )

    assert exc_info.value.status_code == 404
