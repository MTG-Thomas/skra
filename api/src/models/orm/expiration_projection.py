"""
Expiration Projection ORM model (issue #136).

Normalized projection of flagged custom-asset date fields: one row per
(asset, expiration-alert date field) carrying the parsed expiration date,
a safe display label, and the asset enabled flag. Reads (org/global
upcoming-expiration endpoints) become bounded indexed queries instead of
full scans; rows are refreshed transactionally on asset/type writes and
rebuilt idempotently by the backfill job.

Values storage is ID-keyed, so ``field_id`` is the stable storage
identifier while ``field_key`` is the issue-mandated projection key.
Display labels never carry password/totp content (see
``src.services.expiration_projection``); only plain-text display values
or the asset ID fallback are stored here.
"""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.orm.base import Base


class ExpirationProjection(Base):
    """One projected expiration date for a custom asset field."""

    __tablename__ = "expiration_projections"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_type_id: Mapped[UUID] = mapped_column(
        ForeignKey("custom_asset_types.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Custom asset UUID (plain reference like ExpirationAlertSighting.asset_id).
    asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("custom_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Stable storage identifier of the date field within the asset type
    # schema (values JSONB is keyed by field id).
    field_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Human-readable field key: the projection key mandated by issue #136.
    field_key: Mapped[str] = mapped_column(String(255), nullable=False)
    field_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    asset_type_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    expires_on: Mapped[date] = mapped_column(Date, nullable=False)
    # Plain-text display value resolved at write time, or str(asset.id).
    # Never a password/totp value or encrypted blob.
    display_label: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    asset_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Snapshot of the asset enabled flag at projection time. Disabled
    # assets are still projected (current scanner includes them); the
    # product decision on filtering reads this flag.
    is_asset_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true", default=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "asset_type_id",
            "asset_id",
            "field_key",
            name="uq_expiration_projection",
        ),
        UniqueConstraint(
            "asset_id",
            "field_id",
            name="uq_expiration_projection_asset_field",
        ),
        Index(
            "ix_expiration_projection_expires_org",
            "expires_on",
            "organization_id",
        ),
        Index(
            "ix_expiration_projection_org_expires",
            "organization_id",
            "expires_on",
        ),
        Index(
            "ix_expiration_projection_asset_id",
            "asset_id",
        ),
    )
