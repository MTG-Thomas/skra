"""
Expiration Alert Sighting ORM model.

Records which expiration threshold windows have already triggered a
notification, so the daily expiration job (issue #40) alerts once per
window and re-alerts only when an asset escalates to a nearer window.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.orm.base import Base


class ExpirationAlertSighting(Base):
    """One sent expiration alert for an asset field threshold window."""

    __tablename__ = "expiration_alert_sightings"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Custom asset UUID (plain reference like UserFavorite.entity_id).
    asset_id: Mapped[UUID] = mapped_column(nullable=False)
    # Date field key within the asset type schema.
    field_key: Mapped[str] = mapped_column(String(255), nullable=False)
    # Alert window in days (7 or 30) that triggered the notification.
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "asset_id",
            "field_key",
            "window_days",
            name="uq_expiration_alert_sighting",
        ),
    )
