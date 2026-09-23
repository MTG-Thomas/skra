"""Unit tests for expiration projection jobs and projected reads (issue #136).

Covers the paging tails, unknown-type guards, and projected-reader
branches that the scanner-equivalence integration tests do not reach:
multi-page org/asset/type iteration, empty stores, out-of-horizon row
mapping, and merged global ordering. All repositories are faked; no
database, no network.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import src.repositories.custom_asset as custom_asset_repo_module
import src.repositories.custom_asset_type as custom_asset_type_repo_module
import src.repositories.expiration_projection as projection_repo_module
import src.repositories.organization as organization_repo_module
import src.services.expiration as expiration_service
import src.services.expiration_projection as projection_service

ORG_ID = uuid4()
TYPE_ID = uuid4()
ASSET_ID = uuid4()


def _asset(values=None, enabled=True):
    return SimpleNamespace(
        id=uuid4(),
        organization_id=ORG_ID,
        custom_asset_type_id=TYPE_ID,
        values=values or {},
        is_enabled=enabled,
        updated_at=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
    )


def _asset_type():
    return SimpleNamespace(id=TYPE_ID, name="SSL Certificate", fields=[])


def _row(expires_on, org_id=ORG_ID, asset_id=None):
    return SimpleNamespace(
        organization_id=org_id,
        asset_id=asset_id or uuid4(),
        asset_type_id=TYPE_ID,
        asset_type_name="SSL Certificate",
        field_key="expires_on",
        field_name="Expires On",
        expires_on=expires_on,
        display_label="web cert",
    )


@pytest.mark.asyncio
async def test_rederive_unknown_type_returns_zero_without_touching_repos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown types prune nothing: only the type lookup runs."""
    org_repo = AsyncMock()
    org_repo.get_all = AsyncMock(side_effect=AssertionError("must not page orgs"))
    monkeypatch.setattr(
        custom_asset_type_repo_module,
        "CustomAssetTypeRepository",
        lambda db: SimpleNamespace(get_by_id=AsyncMock(return_value=None)),
    )
    monkeypatch.setattr(
        organization_repo_module,
        "OrganizationRepository",
        lambda db: org_repo,
    )

    assert await projection_service.rederive_type_projection(object(), uuid4()) == 0
    org_repo.get_all.assert_not_awaited()


@pytest.mark.asyncio
async def test_rederive_pages_orgs_and_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full org/asset pages advance offsets; short pages stop iteration."""
    type_obj = _asset_type()
    monkeypatch.setattr(
        custom_asset_type_repo_module,
        "CustomAssetTypeRepository",
        lambda db: SimpleNamespace(get_by_id=AsyncMock(return_value=type_obj)),
    )
    orgs = [SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())]
    org_calls: list[tuple[int, int]] = []

    async def fake_get_all(limit: int, offset: int):
        org_calls.append((limit, offset))
        if offset == 0:
            return orgs
        return []

    monkeypatch.setattr(
        organization_repo_module,
        "OrganizationRepository",
        lambda db: SimpleNamespace(get_all=fake_get_all),
    )
    refreshed: list[int] = []

    async def fake_refresh(repository: object, asset: object, asset_type: object) -> int:
        refreshed.append(1)
        return 1

    monkeypatch.setattr(
        projection_service, "refresh_asset_projection", fake_refresh
    )
    async def fake_list(type_id, org_id, limit: int, offset: int):
        if offset == 0:
            return [_asset(), _asset()]
        return [_asset()]

    monkeypatch.setattr(
        custom_asset_repo_module,
        "CustomAssetRepository",
        lambda db: SimpleNamespace(list_by_type_and_organization=fake_list),
    )
    monkeypatch.setattr(
        projection_repo_module,
        "ExpirationProjectionRepository",
        lambda db: SimpleNamespace(),
    )

    assert (
        await projection_service.rederive_type_projection(
            object(), TYPE_ID, page_size=2
        )
        == 6
    )
    assert org_calls == [(2, 0), (2, 2)]
    assert len(refreshed) == 6


@pytest.mark.asyncio
async def test_backfill_paginates_types_and_commits_each(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full type pages advance the offset; every type commits once."""
    type_calls: list[tuple[int, int]] = []

    async def fake_get_all(limit: int, offset: int):
        type_calls.append((limit, offset))
        if offset == 0:
            return [_asset_type()]
        return []

    monkeypatch.setattr(
        custom_asset_type_repo_module,
        "CustomAssetTypeRepository",
        lambda db: SimpleNamespace(get_all_with_inactive=fake_get_all),
    )
    rederived: list[object] = []

    async def fake_rederive(db: object, type_id: object, page_size: int = 500) -> int:
        rederived.append(type_id)
        return 3

    monkeypatch.setattr(
        projection_service, "rederive_type_projection", fake_rederive
    )
    commits: list[int] = []
    db = SimpleNamespace(commit=AsyncMock(side_effect=lambda: commits.append(1)))

    result = await projection_service.backfill_all_projections(db, page_size=1)

    assert result == {"types": 1, "assets": 3}
    assert type_calls == [(1, 0), (1, 1)]
    assert len(commits) == 1


@pytest.mark.asyncio
async def test_backfill_empty_store_returns_zeros_without_commit() -> None:
    """No types: no work, no commit."""
    db = SimpleNamespace(commit=AsyncMock())
    type_repo = SimpleNamespace(
        get_all_with_inactive=AsyncMock(return_value=[]),
    )

    import src.repositories.custom_asset_type as type_module

    orig = type_module.CustomAssetTypeRepository
    type_module.CustomAssetTypeRepository = lambda db: type_repo  # type: ignore[assignment]
    try:
        assert await projection_service.backfill_all_projections(db) == {
            "types": 0,
            "assets": 0,
        }
    finally:
        type_module.CustomAssetTypeRepository = orig
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_prunes_even_when_nothing_projects() -> None:
    """Cleared dates still delete stale rows."""
    repo = SimpleNamespace(
        delete_stale_for_asset=AsyncMock(return_value=2),
        upsert_row=AsyncMock(),
    )
    asset = _asset(values={})
    assert (
        await projection_service.refresh_asset_projection(repo, asset, _asset_type())
        == 0
    )
    repo.delete_stale_for_asset.assert_awaited_once_with(asset.id, set())
    repo.upsert_row.assert_not_awaited()


def test_row_to_upcoming_returns_none_out_of_horizon() -> None:
    """Rows past every alert window map to None, like the scanner skip."""
    row = _row(date(2027, 6, 1))
    assert (
        expiration_service._row_to_upcoming(row, date(2026, 9, 20)) is None
    )


def test_row_to_upcoming_maps_valid_row() -> None:
    """In-horizon rows keep the shared contract fields."""
    asset_id = uuid4()
    row = _row(date(2026, 10, 5), asset_id=asset_id)
    item = expiration_service._row_to_upcoming(row, date(2026, 9, 20))
    assert item is not None
    assert item.days_until == 15
    assert item.window_days == 30
    assert item.asset_id == asset_id
    assert item.asset_display == "web cert"


@pytest.mark.asyncio
async def test_find_upcoming_projected_filters_sorts_and_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Out-of-horizon rows drop; the rest sort by (days, asset)."""
    today = date(2026, 9, 20)
    far = _row(date(2027, 6, 1))
    near_b = _row(date(2026, 10, 5))
    near_a = _row(date(2026, 9, 25))
    seen: dict[str, object] = {}

    async def fake_query(org_ids, cutoff):
        seen["org_ids"] = org_ids
        seen["cutoff"] = cutoff
        return [far, near_b, near_a]

    monkeypatch.setattr(
        projection_repo_module,
        "ExpirationProjectionRepository",
        lambda db: SimpleNamespace(query_upcoming=fake_query),
    )

    items = await expiration_service.find_upcoming_expirations_projected(
        object(), ORG_ID, today=today
    )

    assert seen["org_ids"] == [ORG_ID]
    assert seen["cutoff"] == date(2026, 10, 20)
    assert [i.days_until for i in items] == [5, 15]


@pytest.mark.asyncio
async def test_find_global_projected_merges_orgs_by_urgency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Global reads merge organizations ordered like the scanner merge."""
    today = date(2026, 9, 20)
    org_b = uuid4()
    rows = [
        _row(date(2026, 10, 5), org_id=org_b),
        _row(date(2026, 10, 5), org_id=ORG_ID),
        _row(date(2026, 9, 25), org_id=org_b),
    ]

    monkeypatch.setattr(
        projection_repo_module,
        "ExpirationProjectionRepository",
        lambda db: SimpleNamespace(
            query_upcoming=AsyncMock(return_value=rows)
        ),
    )

    items = await expiration_service.find_global_upcoming_expirations_projected(
        object(), [ORG_ID, org_b], today=today
    )

    assert [i.days_until for i in items] == [5, 15, 15]
    tied = [i.organization_id for i in items if i.days_until == 15]
    assert tied == sorted(tied, key=str)
