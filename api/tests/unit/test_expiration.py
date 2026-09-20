"""Unit tests for expiration computation (issue #40)."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.services.expiration import (
    ALERT_WINDOWS,
    expiration_window,
    find_upcoming_expirations,
    parse_expiration_value,
)

TODAY = date(2026, 9, 19)


def test_alert_windows_match_acceptance_criteria() -> None:
    """Alert windows are 30, 14, 7, and 1 days."""
    assert ALERT_WINDOWS == (30, 14, 7, 1)


@pytest.mark.parametrize(
    ("days_until", "expected"),
    [
        (-3, 0),
        (0, 1),
        (1, 1),
        (2, 7),
        (7, 7),
        (8, 14),
        (14, 14),
        (15, 30),
        (30, 30),
        (31, None),
    ],
)
def test_expiration_window_buckets(days_until: int, expected: int | None) -> None:
    """Days-until maps to the smallest containing window; 0 means expired."""
    assert expiration_window(days_until) == expected


@pytest.mark.parametrize(
    "raw",
    ["2026-12-31", "2026-12-31T00:00:00Z", "2026-12-31T00:00:00+00:00"],
)
def test_parse_expiration_value_accepts_iso_dates(raw: str) -> None:
    assert parse_expiration_value(raw) == date(2026, 12, 31)


@pytest.mark.parametrize("raw", [None, "", "not-a-date", 12345, "2026-13-40"])
def test_parse_expiration_value_rejects_garbage(raw: object) -> None:
    assert parse_expiration_value(raw) is None


def _type(type_id, *fields):
    mock = AsyncMock()
    mock.id = type_id
    mock.name = "SSL Certificate"
    mock.fields = list(fields)
    return mock


def _field(field_id, key="expires_on", alert=True):
    return {
        "id": field_id,
        "key": key,
        "name": "Expires On",
        "type": "date",
        "expiration_alert": alert,
    }


class _NS:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


async def _service(db, types, assets_by_type, today=None):
    from unittest.mock import patch

    type_repo = AsyncMock()
    type_repo.get_all_active = AsyncMock(return_value=types)
    asset_repo = AsyncMock()
    asset_repo.list_by_type_and_organization = AsyncMock(
        side_effect=lambda type_id, org_id: assets_by_type.get(type_id, [])
    )
    with (
        patch(
            "src.repositories.custom_asset_type.CustomAssetTypeRepository",
            return_value=type_repo,
        ),
        patch(
            "src.repositories.custom_asset.CustomAssetRepository",
            return_value=asset_repo,
        ),
    ):
        return await find_upcoming_expirations(db, uuid4(), today=today)


@pytest.mark.asyncio
async def test_finds_expiring_asset_with_window() -> None:
    """An asset expiring in 5 days lands in the 7-day window."""
    type_id = uuid4()
    field_id = str(uuid4())
    expires = (TODAY + timedelta(days=5)).isoformat()
    asset = _NS(id=uuid4(), values={field_id: expires})

    items = await _service(
        AsyncMock(), [_type(type_id, _field(field_id))], {type_id: [asset]}, TODAY
    )

    assert len(items) == 1
    assert items[0].days_until == 5
    assert items[0].window_days == 7
    assert items[0].field_key == "expires_on"


@pytest.mark.asyncio
async def test_ignores_non_alert_fields_and_blank_values() -> None:
    """Only date fields flagged expiration_alert participate."""
    type_id = uuid4()
    alert_field = str(uuid4())
    plain_field = str(uuid4())
    expires = (TODAY + timedelta(days=5)).isoformat()
    asset = _NS(
        id=uuid4(),
        values={alert_field: None, plain_field: expires},
    )

    items = await _service(
        AsyncMock(),
        [_type(type_id, _field(alert_field), _field(plain_field, alert=False))],
        {type_id: [asset]},
    )

    assert items == []


@pytest.mark.asyncio
async def test_expired_and_distant_items() -> None:
    """Past dates report window 0; dates beyond 30 days are excluded."""
    type_id = uuid4()
    field_id = str(uuid4())
    past = (TODAY - timedelta(days=2)).isoformat()
    far = (TODAY + timedelta(days=90)).isoformat()
    assets = [
        _NS(id=uuid4(), values={field_id: past}),
        _NS(id=uuid4(), values={field_id: far}),
    ]

    items = await _service(
        AsyncMock(), [_type(type_id, _field(field_id))], {type_id: assets}, TODAY
    )

    assert len(items) == 1
    assert items[0].days_until == -2
    assert items[0].window_days == 0


@pytest.mark.asyncio
async def test_within_days_filters_results() -> None:
    """Callers can narrow the horizon below 30 days."""
    from unittest.mock import patch

    type_id = uuid4()
    field_id = str(uuid4())
    soon = (TODAY + timedelta(days=3)).isoformat()
    later = (TODAY + timedelta(days=20)).isoformat()
    assets = [
        _NS(id=uuid4(), values={field_id: soon}),
        _NS(id=uuid4(), values={field_id: later}),
    ]
    type_repo = AsyncMock()
    type_repo.get_all_active = AsyncMock(return_value=[_type(type_id, _field(field_id))])
    asset_repo = AsyncMock()
    asset_repo.list_by_type_and_organization = AsyncMock(return_value=assets)

    with (
        patch(
            "src.repositories.custom_asset_type.CustomAssetTypeRepository",
            return_value=type_repo,
        ),
        patch(
            "src.repositories.custom_asset.CustomAssetRepository",
            return_value=asset_repo,
        ),
    ):
        from src.services.expiration import find_upcoming_expirations as find

        items = await find(AsyncMock(), uuid4(), within_days=7, today=TODAY)

    assert [i.days_until for i in items] == [3]
