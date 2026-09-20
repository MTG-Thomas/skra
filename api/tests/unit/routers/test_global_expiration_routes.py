"""Router tests for global upcoming expirations (issue #39).

Single server-side aggregation over readable organizations (no client
N+1): enabled orgs by default, archived orgs opted in with show_disabled.
Mock-based (no database), following test_expiration_routes.py conventions.
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.core.auth import UserPrincipal
from src.main import app
from src.models.enums import UserRole
from src.routers import global_view
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


def _mock_db(org_rows):
    """Mock DbSession whose execute yields the given (id, name) org rows."""
    db = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = org_rows
    db.execute.return_value = result
    return db


@pytest.mark.asyncio
async def test_global_expirations_merge_orgs_with_names_and_limit():
    """Items merge across orgs ordered by urgency, capped by limit."""
    org_a, org_b = uuid4(), uuid4()
    db = _mock_db([(org_a, "Org A"), (org_b, "Org B")])
    merged = [
        _item(org_b, days_until=1, window_days=1),
        _item(org_a, days_until=7, window_days=7),
        _item(org_a, days_until=14, window_days=14),
    ]

    with patch(
        "src.routers.global_view.find_global_upcoming_expirations",
        new=AsyncMock(return_value=merged),
    ):
        result = await global_view.list_global_upcoming_expirations(
            _user(), db, within_days=30, limit=2, offset=0, show_disabled=False
        )

    assert result.total == 3
    assert result.within_days == 30
    assert result.limit == 2
    assert result.offset == 0
    assert [i.days_until for i in result.items] == [1, 7]
    assert result.items[0].organization_name == "Org B"
    assert result.items[1].organization_name == "Org A"


@pytest.mark.asyncio
async def test_global_expirations_offset_preserves_total():
    """Offset pages through the merged list without changing the total."""
    org_a = uuid4()
    db = _mock_db([(org_a, "Org A")])
    merged = [_item(org_a, days_until=d, window_days=7) for d in (1, 7, 14)]

    with patch(
        "src.routers.global_view.find_global_upcoming_expirations",
        new=AsyncMock(return_value=merged),
    ):
        result = await global_view.list_global_upcoming_expirations(
            _user(), db, within_days=30, limit=2, offset=2, show_disabled=False
        )

    assert result.total == 3
    assert [i.days_until for i in result.items] == [14]


@pytest.mark.asyncio
async def test_global_expirations_hide_disabled_by_default():
    """Default org query filters to enabled organizations (issue #93)."""
    org_a = uuid4()
    db = _mock_db([(org_a, "Org A")])

    with patch(
        "src.routers.global_view.find_global_upcoming_expirations",
        new=AsyncMock(return_value=[]),
    ):
        result = await global_view.list_global_upcoming_expirations(
            _user(), db, within_days=30, limit=20, offset=0, show_disabled=False
        )

    assert result.total == 0
    assert result.items == []
    (stmt,) = db.execute.await_args[0]
    assert "is_enabled" in str(stmt)


@pytest.mark.asyncio
async def test_global_expirations_show_disabled_includes_all():
    """show_disabled=true drops the enabled filter (opt-in, any role)."""
    org_a, org_b = uuid4(), uuid4()
    db = _mock_db([(org_a, "Org A"), (org_b, "Org B")])
    merged = [_item(org_b, days_until=1, window_days=1)]

    with patch(
        "src.routers.global_view.find_global_upcoming_expirations",
        new=AsyncMock(return_value=merged),
    ):
        result = await global_view.list_global_upcoming_expirations(
            _user(), db, within_days=30, limit=20, offset=0, show_disabled=True
        )

    assert result.total == 1
    assert result.items[0].organization_name == "Org B"
    (stmt,) = db.execute.await_args[0]
    assert "is_enabled" not in str(stmt)


@pytest.mark.asyncio
async def test_global_expirations_scans_only_visible_orgs():
    """Aggregation receives exactly the readable organization IDs."""
    org_a, org_b = uuid4(), uuid4()
    db = _mock_db([(org_a, "Org A"), (org_b, "Org B")])
    scan = AsyncMock(return_value=[])

    with patch("src.routers.global_view.find_global_upcoming_expirations", new=scan):
        await global_view.list_global_upcoming_expirations(
            _user(), db, within_days=14, limit=20, offset=0, show_disabled=False
        )

    assert scan.await_args[0][1] == [org_a, org_b]
    assert scan.await_args[1] == {"within_days": 14}


@pytest.mark.asyncio
async def test_global_expirations_requires_authentication():
    """Unauthenticated requests fail closed with 401."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/global/expirations/upcoming")

    assert response.status_code == 401
