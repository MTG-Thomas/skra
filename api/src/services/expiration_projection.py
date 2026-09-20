"""Expiration projection computation (issue #136, stage 1A).

Projects flagged custom-asset date fields into normalized rows without
I/O: :func:`project_asset` is pure so routers, backfill, and tests share
semantics, while :func:`refresh_asset_projection` applies the rows
transactionally in the caller's session (no commit here; ``get_db``
commits at request end).

Safety rules: values storage is ID-keyed, so date lookups use the stable
field ``id``. Display labels resolve like the asset router but never
from password/totp fields and never from encrypted raw values — only
plain-text display values, else the asset ID fallback. Disabled assets
are still projected (current scanner includes them); the enabled flag is
stored for the later product decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from src.services.expiration import parse_expiration_value

# Field types that must never render as a display label:
# password/totp values are encrypted blobs.
_SECRET_DISPLAY_TYPES = frozenset({"password", "totp"})


@dataclass(frozen=True)
class ProjectedExpiration:
    """One normalized expiration row for an asset date field."""

    organization_id: UUID
    asset_type_id: UUID
    asset_id: UUID
    field_id: str
    field_key: str
    field_name: str
    asset_type_name: str
    expires_on: date
    display_label: str | None
    asset_updated_at: datetime | None
    is_asset_enabled: bool


def _field_get(field: Any, attr: str) -> Any:
    if isinstance(field, dict):
        return field.get(attr)
    return getattr(field, attr, None)


def _resolve_display_label(
    type_fields: list[Any],
    values: dict[str, Any],
    display_field_key: str | None,
) -> str | None:
    """
    Resolve a safe display label from ID-keyed storage values.

    Preserves the old expiration scanner: only the configured display
    field qualifies, otherwise the caller falls back to the asset ID —
    other fields are never searched. Like the scanner, any non-None
    value stringifies (numbers, booleans, even empty strings). One
    hardening over the scanner: password/totp display fields are
    rejected, so encrypted blobs can never land in the projection.
    """
    if not display_field_key:
        return None
    by_key = {_field_get(f, "key"): f for f in type_fields}
    field = by_key.get(display_field_key)
    if field is None:
        return None
    if _field_get(field, "type") in _SECRET_DISPLAY_TYPES:
        return None
    raw = values.get(_field_get(field, "id"))
    if raw is None:
        return None
    return str(raw)


def project_asset(asset: Any, asset_type: Any) -> list[ProjectedExpiration]:
    """
    Project an asset's flagged date fields into normalized rows.

    Pure: no I/O, no filtering on enabled state (disabled assets are
    projected with ``is_asset_enabled=False``). Unparseable or blank
    date values are skipped; non-date or unflagged fields never project.
    """
    values: dict[str, Any] = asset.values if isinstance(asset.values, dict) else {}
    type_fields: list[Any] = list(asset_type.fields or [])
    display_field_key = getattr(asset_type, "display_field_key", None)

    rows: list[ProjectedExpiration] = []
    for field in type_fields:
        if _field_get(field, "type") != "date":
            continue
        if not _field_get(field, "expiration_alert"):
            continue
        field_id = _field_get(field, "id")
        if not field_id:
            continue
        expires_on = parse_expiration_value(values.get(field_id))
        if expires_on is None:
            continue
        label = _resolve_display_label(type_fields, values, display_field_key)
        rows.append(
            ProjectedExpiration(
                organization_id=asset.organization_id,
                asset_type_id=asset.custom_asset_type_id,
                asset_id=asset.id,
                field_id=str(field_id),
                field_key=str(_field_get(field, "key")),
                field_name=str(_field_get(field, "name") or ""),
                asset_type_name=str(getattr(asset_type, "name", "") or ""),
                expires_on=expires_on,
                display_label=label if label is not None else str(asset.id),
                asset_updated_at=getattr(asset, "updated_at", None),
                is_asset_enabled=bool(getattr(asset, "is_enabled", True)),
            )
        )
    return rows


async def refresh_asset_projection(repository: Any, asset: Any, asset_type: Any) -> int:
    """
    Refresh one asset's projection rows in the current transaction.

    Prunes stale rows first, then upserts current ones, and returns the
    upserted count. Stale-first ordering matters: when a type edit
    re-ids a field but reuses the same field key, the old row still
    holds the 4-tuple (organization, type, asset, field key) the new
    row needs, so upsert-first would collide. Commits nothing; the
    caller (request transaction or backfill job) owns the commit.
    """
    rows = project_asset(asset, asset_type)
    # Prune before upsert: cleared dates, unflagged or removed fields,
    # and re-ided fields whose old row still occupies the 4-tuple key.
    await repository.delete_stale_for_asset(asset.id, {row.field_id for row in rows})
    for row in rows:
        await repository.upsert_row(
            organization_id=row.organization_id,
            asset_type_id=row.asset_type_id,
            asset_id=row.asset_id,
            field_id=row.field_id,
            field_key=row.field_key,
            field_name=row.field_name,
            asset_type_name=row.asset_type_name,
            expires_on=row.expires_on,
            display_label=row.display_label,
            asset_updated_at=row.asset_updated_at,
            is_asset_enabled=row.is_asset_enabled,
        )
    return len(rows)
