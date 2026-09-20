"""Expiration computation for custom asset date fields (issue #40).

Finds assets whose flagged date fields fall inside the alert windows.
Pure helpers stay free of I/O so alerting, API, and UI share semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

# Alert windows in days, largest first. Day counts at or under a window
# belong to it; 0 marks already-expired items.
ALERT_WINDOWS: tuple[int, ...] = (30, 14, 7, 1)

DEFAULT_WITHIN_DAYS = 30


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
    then each type's assets in the organization. Unparseable or blank
    values are skipped; items beyond ``within_days`` are excluded.
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
        key_to_id = {
            _field_get(f, "key"): _field_get(f, "id")
            for f in (asset_type.fields or [])
        }
        display_id = key_to_id.get(getattr(asset_type, "display_field_key", None))
        assets = await asset_repo.list_by_type_and_organization(
            asset_type.id, organization_id
        )
        for asset in assets:
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
    items.sort(key=lambda i: (i.days_until, str(i.asset_id)))
    return items
