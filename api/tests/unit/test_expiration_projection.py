"""Unit tests for the expiration projection (issue #136, stage 1A)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.services.expiration_projection import ProjectedExpiration, project_asset

ORG_ID = uuid4()
TYPE_ID = uuid4()
ASSET_ID = uuid4()


def _field(field_id, key="expires_on", field_type="date", alert=True, name="Expires On"):
    return {
        "id": field_id,
        "key": key,
        "name": name,
        "type": field_type,
        "expiration_alert": alert,
    }


def _type(*fields, display_field_key=None, name="SSL Certificate"):
    mock = MagicMock()
    mock.id = TYPE_ID
    mock.name = name
    mock.fields = list(fields)
    mock.display_field_key = display_field_key
    return mock


def _asset(values, enabled=True):
    mock = MagicMock()
    mock.id = ASSET_ID
    mock.organization_id = ORG_ID
    mock.custom_asset_type_id = TYPE_ID
    mock.values = values
    mock.is_enabled = enabled
    mock.updated_at = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    return mock


def test_projects_flagged_date_field_by_stable_id():
    """Date lookup uses the stable field id; the row reports the field key."""
    field_id = str(uuid4())
    asset = _asset({field_id: "2026-10-05"})
    asset_type = _type(_field(field_id))

    rows = project_asset(asset, asset_type)

    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, ProjectedExpiration)
    assert row.field_id == field_id
    assert row.field_key == "expires_on"
    assert row.field_name == "Expires On"
    assert row.asset_type_name == "SSL Certificate"
    assert row.expires_on == date(2026, 10, 5)
    assert row.organization_id == ORG_ID
    assert row.asset_id == ASSET_ID
    assert row.asset_type_id == TYPE_ID
    assert row.is_asset_enabled is True
    assert row.asset_updated_at == asset.updated_at


def test_ignores_unflagged_and_non_date_fields():
    """Only date fields with expiration_alert project."""
    alert_id = str(uuid4())
    plain_id = str(uuid4())
    text_id = str(uuid4())
    asset = _asset({alert_id: None, plain_id: "2026-10-05", text_id: "2026-10-05"})
    asset_type = _type(
        _field(alert_id),
        _field(plain_id, key="reviewed_on", alert=False),
        _field(text_id, key="note", field_type="text", alert=True),
    )

    assert project_asset(asset, asset_type) == []


def test_skips_blank_and_unparseable_values():
    """Blank, null, and garbage date values project nothing, never raise."""
    field_id = str(uuid4())
    for raw in (None, "", "   ", "not-a-date", 12345, {"items": []}):
        asset = _asset({field_id: raw})

        assert project_asset(asset, _type(_field(field_id))) == []


def test_preserves_datetime_with_timezone_to_date():
    """Datetime strings collapse to dates exactly like the current scanner."""
    field_id = str(uuid4())
    asset = _asset({field_id: "2026-10-05T23:30:00+00:00"})

    (row,) = project_asset(asset, _type(_field(field_id)))

    assert row.expires_on == date(2026, 10, 5)


def test_display_label_uses_explicit_display_field():
    """The type's display field supplies the label when it holds plain text."""
    date_id = str(uuid4())
    name_id = str(uuid4())
    asset = _asset({date_id: "2026-10-05", name_id: "Wildcard Cert"})
    asset_type = _type(
        _field(date_id),
        _field(name_id, key="name", field_type="text", alert=False, name="Name"),
        display_field_key="name",
    )

    (row,) = project_asset(asset, asset_type)

    assert row.display_label == "Wildcard Cert"


def test_display_label_ignores_unconfigured_fields():
    """Scanner parity: without a display key, other fields never label the row."""
    date_id = str(uuid4())
    name_id = str(uuid4())
    asset = _asset({date_id: "2026-10-05", name_id: "Wildcard Cert"})
    asset_type = _type(
        _field(date_id),
        _field(name_id, key="name", field_type="text", alert=False, name="Name"),
    )

    (row,) = project_asset(asset, asset_type)

    assert row.display_label == str(ASSET_ID)


def test_display_label_uses_configured_date_field():
    """A display key pointing at the date field itself still qualifies."""
    date_id = str(uuid4())
    asset = _asset({date_id: "2026-10-05"})
    asset_type = _type(_field(date_id), display_field_key="expires_on")

    (row,) = project_asset(asset, asset_type)

    assert row.display_label == "2026-10-05"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(42, "42"), (3.5, "3.5"), ("", ""), (True, "True")],
)
def test_display_label_matches_scanner_for_non_string_values(raw, expected):
    """Scanner parity: any non-None display value stringifies, even falsy ones."""
    date_id = str(uuid4())
    count_id = str(uuid4())
    asset = _asset({date_id: "2026-10-05", count_id: raw})
    asset_type = _type(
        _field(date_id),
        _field(count_id, key="count", field_type="number", alert=False, name="Count"),
        display_field_key="count",
    )

    (row,) = project_asset(asset, asset_type)

    assert row.display_label == expected


def test_display_label_falls_back_to_asset_id():
    """No usable display value resolves to None, so the row stores the asset ID."""
    from src.services.expiration_projection import _resolve_display_label

    header = {
        "id": str(uuid4()),
        "key": "section",
        "name": "Section",
        "type": "header",
        "expiration_alert": False,
    }
    assert _resolve_display_label([header], {}, "missing-key") is None
    assert _resolve_display_label([header], {}, None) is None


@pytest.mark.parametrize("secret_type", ["password", "totp"])
def test_password_display_field_never_stored(secret_type):
    """A secret-typed display field falls back; encrypted blobs never project."""
    date_id = str(uuid4())
    secret_id = str(uuid4())
    asset = _asset({date_id: "2026-10-05", secret_id: "gAAAAABsecret-blob"})
    asset_type = _type(
        _field(date_id),
        _field(secret_id, key="secret", field_type=secret_type, alert=False, name="Secret"),
        display_field_key="secret",
    )

    (row,) = project_asset(asset, asset_type)

    assert row.display_label == str(ASSET_ID)
    assert "gAAAAABsecret-blob" not in str(row)


def test_disabled_asset_still_projected_with_flag():
    """Disabled assets project (current scanner includes them); flag is stored."""
    field_id = str(uuid4())
    asset = _asset({field_id: "2026-10-05"}, enabled=False)

    (row,) = project_asset(asset, _type(_field(field_id)))

    assert row.is_asset_enabled is False
    assert row.expires_on == date(2026, 10, 5)


def test_field_key_rename_with_stable_id_projects_new_key():
    """A renamed key over the same field id projects under the new key."""
    field_id = str(uuid4())
    asset = _asset({field_id: "2026-10-05"})
    asset_type = _type(_field(field_id, key="renewal_date", name="Renewal Date"))

    (row,) = project_asset(asset, asset_type)

    assert row.field_id == field_id
    assert row.field_key == "renewal_date"
    assert row.field_name == "Renewal Date"


@pytest.mark.asyncio
async def test_refresh_upserts_current_and_prunes_stale():
    """Refresh upserts projected rows and prunes retired field ids."""
    from src.services.expiration_projection import refresh_asset_projection

    keep_id = str(uuid4())
    asset = _asset({keep_id: "2026-10-05"})
    repo = AsyncMock()
    repo.upsert_row = AsyncMock()
    repo.delete_stale_for_asset = AsyncMock(return_value=1)

    count = await refresh_asset_projection(repo, asset, _type(_field(keep_id)))

    assert count == 1
    repo.upsert_row.assert_awaited_once()
    kwargs = repo.upsert_row.await_args.kwargs
    assert kwargs["asset_id"] == ASSET_ID
    assert kwargs["field_id"] == keep_id
    assert kwargs["field_key"] == "expires_on"
    assert kwargs["expires_on"] == date(2026, 10, 5)
    assert kwargs["is_asset_enabled"] is True
    repo.delete_stale_for_asset.assert_awaited_once_with(ASSET_ID, {keep_id})
    # Stale-first: prune runs before any upsert in the same transaction.
    ordered = [call[0] for call in repo.mock_calls]
    assert ordered.index("delete_stale_for_asset") < ordered.index("upsert_row")


@pytest.mark.asyncio
async def test_refresh_rename_converges_on_stable_id():
    """A renamed key with the same field id upserts the new key, prunes nothing."""
    from src.services.expiration_projection import refresh_asset_projection

    field_id = str(uuid4())
    asset = _asset({field_id: "2026-10-05"})
    repo = AsyncMock()
    repo.upsert_row = AsyncMock()
    repo.delete_stale_for_asset = AsyncMock(return_value=0)

    count = await refresh_asset_projection(
        repo, asset, _type(_field(field_id, key="renewal_date", name="Renewal Date"))
    )

    assert count == 1
    kwargs = repo.upsert_row.await_args.kwargs
    assert kwargs["field_id"] == field_id
    assert kwargs["field_key"] == "renewal_date"
    assert kwargs["field_name"] == "Renewal Date"
    repo.delete_stale_for_asset.assert_awaited_once_with(ASSET_ID, {field_id})


@pytest.mark.asyncio
async def test_refresh_reid_reusing_key_prunes_before_upsert():
    """A re-ided field reusing the key prunes the old row before upserting."""
    from src.services.expiration_projection import refresh_asset_projection

    new_id = str(uuid4())
    asset = _asset({new_id: "2026-10-05"})
    repo = AsyncMock()
    repo.upsert_row = AsyncMock()
    repo.delete_stale_for_asset = AsyncMock(return_value=1)

    count = await refresh_asset_projection(repo, asset, _type(_field(new_id)))

    assert count == 1
    # The old row still occupies the 4-tuple key until pruned, so the
    # prune must precede the upsert within the transaction.
    ordered = [call[0] for call in repo.mock_calls]
    assert ordered.index("delete_stale_for_asset") < ordered.index("upsert_row")
    repo.delete_stale_for_asset.assert_awaited_once_with(ASSET_ID, {new_id})
    kwargs = repo.upsert_row.await_args.kwargs
    assert kwargs["field_id"] == new_id
    assert kwargs["field_key"] == "expires_on"


@pytest.mark.asyncio
async def test_refresh_with_no_rows_prunes_everything():
    """A cleared date value removes all rows for the asset."""
    field_id = str(uuid4())
    asset = _asset({field_id: ""})
    repo = AsyncMock()
    repo.delete_stale_for_asset = AsyncMock(return_value=1)

    from src.services.expiration_projection import refresh_asset_projection

    assert await refresh_asset_projection(repo, asset, _type(_field(field_id))) == 0
    repo.upsert_row.assert_not_awaited()
    repo.delete_stale_for_asset.assert_awaited_once_with(ASSET_ID, set())


def test_snapshot_columns_are_unbounded_text():
    """Display/name snapshots must not truncate valid content (no length cap)."""
    from sqlalchemy import String, Text

    from src.models.orm.expiration_projection import ExpirationProjection

    columns = ExpirationProjection.__table__.columns
    for name in ("display_label", "field_name", "asset_type_name"):
        assert isinstance(columns[name].type, Text), name
    # Indexed key columns stay bounded.
    for name in ("field_id", "field_key"):
        assert isinstance(columns[name].type, String), name
        assert columns[name].type.length == 255, name


def test_long_display_value_projects_intact():
    """A display value past 1024 chars projects whole: no new write failure."""
    from src.services.expiration_projection import project_asset

    date_id = str(uuid4())
    name_id = str(uuid4())
    long_name = "n" * 5000
    asset = _asset({date_id: "2026-10-05", name_id: long_name})
    asset_type = _type(
        _field(date_id),
        _field(name_id, key="name", field_type="text", alert=False, name="Name"),
        display_field_key="name",
    )

    (row,) = project_asset(asset, asset_type)

    assert row.display_label == long_name


@pytest.mark.asyncio
async def test_repository_upsert_conflicts_on_stable_id_and_updates_key():
    """Upsert targets (asset_id, field_id) so renames update the key in place."""
    from src.repositories.expiration_projection import ExpirationProjectionRepository

    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock())
    repo = ExpirationProjectionRepository(session)

    await repo.upsert_row(
        organization_id=ORG_ID,
        asset_type_id=TYPE_ID,
        asset_id=ASSET_ID,
        field_id="fid",
        field_key="expires_on",
        field_name="Expires On",
        asset_type_name="SSL Certificate",
        expires_on=date(2026, 10, 5),
        display_label="Wildcard Cert",
        asset_updated_at=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
        is_asset_enabled=True,
    )

    session.execute.assert_awaited_once()
    (stmt,) = session.execute.await_args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "uq_expiration_projection_asset_field" in compiled
    assert "field_key" in compiled


@pytest.mark.asyncio
async def test_repository_deletes_return_row_counts():
    """Delete helpers report removed rows for logging and reconciliation."""
    from src.repositories.expiration_projection import ExpirationProjectionRepository

    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(rowcount=2))
    repo = ExpirationProjectionRepository(session)

    assert await repo.delete_for_asset(ASSET_ID) == 2
    assert await repo.delete_stale_for_asset(ASSET_ID, {"fid"}) == 2
    assert await repo.delete_stale_for_asset(ASSET_ID, set()) == 2
    assert await repo.delete_for_type(TYPE_ID) == 2
    assert session.execute.await_count == 4


@pytest.mark.asyncio
async def test_repository_lists_field_ids_for_pruning():
    """Stale-row pruning reads back the asset's projected field ids."""
    from src.repositories.expiration_projection import ExpirationProjectionRepository

    session = AsyncMock()
    scalars = MagicMock()
    scalars.all.return_value = ["fid-a", "fid-b"]
    session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=scalars)))
    repo = ExpirationProjectionRepository(session)

    assert await repo.list_field_ids_for_asset(ASSET_ID) == ["fid-a", "fid-b"]
