"""
Expiration Alert repository.

Persists sent-alert sightings for the expiration daily job (issue #40).
Inserts are idempotent: a repeated sighting of the same threshold window
is a no-op that reports False so the caller can suppress duplicates.
"""

from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm.expiration_alert import ExpirationAlertSighting
from src.repositories.base import BaseRepository


class ExpirationAlertRepository(BaseRepository[ExpirationAlertSighting]):
    """Repository for expiration alert sighting operations."""

    model = ExpirationAlertSighting

    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def record_sent(
        self,
        organization_id: UUID,
        asset_id: UUID,
        field_key: str,
        window_days: int,
    ) -> bool:
        """
        Record a sent alert for a threshold window.

        Args:
            organization_id: Organization UUID
            asset_id: Custom asset UUID
            field_key: Date field key within the asset type schema
            window_days: Alert window in days that triggered the notification

        Returns:
            True when this is the first sighting (caller should notify),
            False when the window was already recorded (suppress duplicate).
        """
        stmt = insert(ExpirationAlertSighting).values(
            organization_id=organization_id,
            asset_id=asset_id,
            field_key=field_key,
            window_days=window_days,
        )
        stmt = stmt.on_conflict_do_nothing(constraint="uq_expiration_alert_sighting")

        result = await self.session.execute(stmt)
        return result.rowcount == 1  # type: ignore[attr-defined]
