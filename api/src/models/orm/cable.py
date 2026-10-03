"""
Cable tracking models for DCIM.

Tracks physical cable connections between devices with port mapping.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.orm.base import Base

if TYPE_CHECKING:
    from src.models.orm.organization import Organization

    # configuration imports this module, so importing it here would close an
    # import cycle (CodeQL py/unsafe-cyclic-import). Alias as Any instead;
    # SQLAlchemy resolves the string annotations via its class registry.
    Configuration = Any


class Cable(Base):
    """Physical cable tracking between devices.

    Supports fiber, copper, DAC, power cables with port mapping.
    """

    __tablename__ = "cables"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
    )

    # Cable identification
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cable_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Cable specs
    length_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    color: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # End A (source)
    end_a_config_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("configurations.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    end_a_port: Mapped[str | None] = mapped_column(String(100), nullable=True)
    end_a_location: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # End B (destination)
    end_b_config_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("configurations.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    end_b_port: Mapped[str | None] = mapped_column(String(100), nullable=True)
    end_b_location: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # For fiber: which strand in a bundle
    strand_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Status
    is_connected: Mapped[bool] = mapped_column(default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    organization: Mapped[Organization] = relationship(back_populates="cables")
    end_a_config: Mapped[Configuration | None] = relationship(
        foreign_keys=[end_a_config_id],
        back_populates="cables_as_source",
    )
    end_b_config: Mapped[Configuration | None] = relationship(
        foreign_keys=[end_b_config_id],
        back_populates="cables_as_destination",
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )
