"""Expiration computation for custom asset date fields (issue #40).

Finds assets whose flagged date fields fall inside the alert windows.
Pure helpers stay free of I/O so alerting, API, and UI share semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

# Alert windows in days, largest first. Day counts at or under a window
# belong to it; 0 marks already-expired items.
ALERT_WINDOWS: tuple[int, ...] = (30, 14, 7, 1)

DEFAULT_WITHIN_DAYS = 30

# Assets scanned per repository call. The repository caps a single call,
# so the scan pages to exhaustion instead of trusting one page.
ASSET_PAGE_SIZE = 500


def parse_expiration_value(value: Any) -> date | None:
    """Parse an ISO date/datetime string into a date, else None."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.date()


def expiration_window(days_until: int) -> int | None:
    """Map days-until-expiration to the smallest containing alert window.

    Returns 0 for expired items and None when beyond every window.
    """
    if days_until < 0:
        return 0
    for window in sorted(ALERT_WINDOWS):
        if days_until <= window:
            return window
    return None


@dataclass(frozen=True)
class UpcomingExpiration:
    """One flagged date field approaching or past expiration."""

    organization_id: UUID
    asset_id: UUID
    asset_display: str | None
    asset_type_id: UUID
    asset_type_name: str
    field_key: str
    field_name: str
    expires_on: date
    days_until: int
    window_days: int


def _field_get(field: Any, attr: str) -> Any:
    if isinstance(field, dict):
        return field.get(attr)
    return getattr(field, attr, None)


async def find_upcoming_expirations(
    db: Any,
    organization_id: UUID,
    *,
    within_days: int = DEFAULT_WITHIN_DAYS,
    today: date | None = None,
) -> list[UpcomingExpiration]:
    """Find flagged expirations for one organization inside the horizon.

    Scans active custom asset types for date fields with expiration_alert,
    then pages through each type's assets in the organization to exhaustion
    (a single repository call is capped and would silently drop assets past
    the first page). Unparseable or blank values are skipped; items beyond
    ``within_days`` are excluded.
    """
    from src.repositories.custom_asset import CustomAssetRepository
    from src.repositories.custom_asset_type import CustomAssetTypeRepository

    current = today or datetime.now(UTC).date()
    type_repo = CustomAssetTypeRepository(db)
    asset_repo = CustomAssetRepository(db)

    items: list[UpcomingExpiration] = []
    for asset_type in await type_repo.get_all_active():
        alert_fields = [
            f
            for f in (asset_type.fields or [])
            if _field_get(f, "type") == "date" and _field_get(f, "expiration_alert")
        ]
        if not alert_fields:
            continue
        key_to_id = {_field_get(f, "key"): _field_get(f, "id") for f in (asset_type.fields or [])}
        display_id = key_to_id.get(getattr(asset_type, "display_field_key", None))
        page_offset = 0
        while True:
            page = await asset_repo.list_by_type_and_organization(
                asset_type.id, organization_id, limit=ASSET_PAGE_SIZE, offset=page_offset
            )
            for asset in page:
                values = asset.values or {}
                for field in alert_fields:
                    expires_on = parse_expiration_value(values.get(_field_get(field, "id")))
                    if expires_on is None:
                        continue
                    days_until = (expires_on - current).days
                    if days_until > within_days:
                        continue
                    window = expiration_window(days_until)
                    if window is None:
                        continue
                    display = None
                    if display_id:
                        raw_display = values.get(display_id)
                        display = str(raw_display) if raw_display is not None else None
                    if display is None:
                        display = str(asset.id)
                    items.append(
                        UpcomingExpiration(
                            organization_id=organization_id,
                            asset_id=asset.id,
                            asset_display=display,
                            asset_type_id=asset_type.id,
                            asset_type_name=asset_type.name,
                            field_key=_field_get(field, "key"),
                            field_name=_field_get(field, "name"),
                            expires_on=expires_on,
                            days_until=days_until,
                            window_days=window,
                        )
                    )
            if len(page) < ASSET_PAGE_SIZE:
                break
            page_offset += ASSET_PAGE_SIZE
    items.sort(key=lambda i: (i.days_until, str(i.asset_id)))
    return items


async def find_global_upcoming_expirations(
    db: Any,
    organization_ids: list[UUID],
    *,
    within_days: int = DEFAULT_WITHIN_DAYS,
    today: date | None = None,
) -> list[UpcomingExpiration]:
    """Find flagged expirations across organizations inside the horizon.

    Legacy full-scan path, kept for rollback and scanner-vs-projection
    comparison (see the integration test): reuses the org-scoped scan
    per organization and merges ordered by urgency (days until
    expiration, then asset id for determinism).

    Cost note: every page of every flagged type in every listed
    organization is scanned, so work scales with total assets, not with
    the caller's limit — limit/offset bound only the response, not the
    scan. Prefer find_global_upcoming_expirations_projected.
    """
    merged: list[UpcomingExpiration] = []
    for organization_id in organization_ids:
        merged.extend(
            await find_upcoming_expirations(
                db, organization_id, within_days=within_days, today=today
            )
        )
    merged.sort(key=lambda i: (i.days_until, str(i.organization_id), str(i.asset_id)))
    return merged


def _row_to_upcoming(row: Any, current: date) -> UpcomingExpiration | None:
    """Map one projection row to the shared upcoming-expiration contract.

    Returns None for out-of-horizon rows (the scanner skips those too);
    unreachable when callers bound expires_on <= today + within_days.
    """
    days_until = (row.expires_on - current).days
    window = expiration_window(days_until)
    if window is None:
        return None
    return UpcomingExpiration(
        organization_id=row.organization_id,
        asset_id=row.asset_id,
        asset_display=row.display_label,
        asset_type_id=row.asset_type_id,
        asset_type_name=row.asset_type_name,
        field_key=row.field_key,
        field_name=row.field_name,
        expires_on=row.expires_on,
        days_until=days_until,
        window_days=window,
    )


async def find_upcoming_expirations_projected(
    db: Any,
    organization_id: UUID,
    *,
    within_days: int = DEFAULT_WITHIN_DAYS,
    today: date | None = None,
) -> list[UpcomingExpiration]:
    """Projection-backed replacement for :func:`find_upcoming_expirations`.

    Same contract and ordering ((days_until, asset_id)); reads the
    normalized rows through the (organization_id, expires_on) index
    instead of paging every asset. Expired rows are included, matching
    the scanner.
    """
    from src.repositories.expiration_projection import ExpirationProjectionRepository

    current = today or datetime.now(UTC).date()
    cutoff = current + timedelta(days=within_days)
    rows = await ExpirationProjectionRepository(db).query_upcoming([organization_id], cutoff)
    items = [item for row in rows if (item := _row_to_upcoming(row, current)) is not None]
    items.sort(key=lambda i: (i.days_until, str(i.asset_id)))
    return items


async def find_global_upcoming_expirations_projected(
    db: Any,
    organization_ids: list[UUID],
    *,
    within_days: int = DEFAULT_WITHIN_DAYS,
    today: date | None = None,
) -> list[UpcomingExpiration]:
    """Projection-backed replacement for :func:`find_global_upcoming_expirations`.

    Single bounded indexed query across the visible organizations, merged
    ordered by urgency ((days_until, organization_id, asset_id)) exactly
    like the scanner merge.
    """
    from src.repositories.expiration_projection import ExpirationProjectionRepository

    current = today or datetime.now(UTC).date()
    cutoff = current + timedelta(days=within_days)
    rows = await ExpirationProjectionRepository(db).query_upcoming(organization_ids, cutoff)
    items = [item for row in rows if (item := _row_to_upcoming(row, current)) is not None]
    items.sort(key=lambda i: (i.days_until, str(i.organization_id), str(i.asset_id)))
    return items
