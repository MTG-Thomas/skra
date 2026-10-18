"""Router tests for database-bounded global upcoming expirations."""

from datetime import date
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from starlette.requests import Request

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


def _request() -> Request:
    return Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/api/global/expirations/upcoming",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )


def _endpoint_handler():
    """Return the endpoint body without requiring live rate-limit storage."""
    endpoint = global_view.list_global_upcoming_expirations
    return getattr(endpoint, "__wrapped__", endpoint)


def _item(org_id, **overrides) -> UpcomingExpiration:
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
async def test_global_expirations_maps_only_the_database_page_and_exact_total():
    """The route maps the returned page and does not materialize a full result."""
    org_a, org_b = uuid4(), uuid4()
    db = AsyncMock()
    page = [
        (_item(org_b, days_until=1, window_days=1), "Org B"),
        (_item(org_a, days_until=7, window_days=7), "Org A"),
    ]
    query = AsyncMock(return_value=(page, 250))

    with patch(
        "src.routers.global_view.find_global_upcoming_expirations_page_projected",
        new=query,
    ):
        result = await _endpoint_handler()(
            _request(),
            _user(),
            db,
            within_days=30,
            search=None,
            sort_by="days_until",
            sort_dir="asc",
            limit=2,
            offset=40,
            show_disabled=False,
        )

    assert result.total == 250
    assert result.within_days == 30
    assert result.limit == 2
    assert result.offset == 40
    assert [item.days_until for item in result.items] == [1, 7]
    assert [item.organization_name for item in result.items] == ["Org B", "Org A"]


@pytest.mark.asyncio
async def test_global_expirations_forwards_search_sort_page_and_visibility_to_database():
    """Every potentially expensive operation is delegated to the bounded query."""
    db = AsyncMock()
    query = AsyncMock(return_value=([], 0))

    with patch(
        "src.routers.global_view.find_global_upcoming_expirations_page_projected",
        new=query,
    ):
        result = await _endpoint_handler()(
            _request(),
            _user(),
            db,
            within_days=365,
            search="ACME%_literal",
            sort_by="organization_name",
            sort_dir="desc",
            limit=100,
            offset=10_000,
            show_disabled=True,
        )

    assert result.items == []
    assert result.total == 0
    query.assert_awaited_once_with(
        db,
        within_days=365,
        search="ACME%_literal",
        sort_by="organization_name",
        sort_dir="desc",
        limit=100,
        offset=10_000,
        show_disabled=True,
    )


def test_global_expiration_openapi_bounds_search_and_offset():
    """The public contract rejects oversized search and pathological offsets."""
    operation = app.openapi()["paths"]["/api/global/expirations/upcoming"]["get"]
    parameters = {parameter["name"]: parameter["schema"] for parameter in operation["parameters"]}

    search_schemas = [parameters["search"], *parameters["search"].get("anyOf", [])]
    assert any(schema.get("maxLength") == 200 for schema in search_schemas)
    assert parameters["offset"]["maximum"] == 10_000
    assert parameters["limit"]["maximum"] == 100


@pytest.mark.asyncio
async def test_global_expirations_requires_authentication():
    """Unauthenticated requests fail closed with 401."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/global/expirations/upcoming")

    assert response.status_code == 401
