"""
Power circuit tracking models for DCIM.

Tracks power distribution circuits and device power connections.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.orm.base import Base

if TYPE_CHECKING:
    from src.models.orm.configuration import Configuration
    from src.models.orm.organization import Organization

    # location imports this module, so importing it here would close an
    # import cycle (CodeQL py/unsafe-cyclic-import). Alias as Any instead;
    # SQLAlchemy resolves the string annotations via its class registry.
    Location = Any


class Circuit(Base):
    """Power circuit/panel tracking.

    Tracks power distribution for capacity planning.
    """

    __tablename__ = "circuits"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
    )
    location_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    # Circuit details
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    circuit_type: Mapped[str] = mapped_column(String(50), default="power")
    phase: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Capacity
    voltage_v: Mapped[int] = mapped_column(Integer, default=120)
    amperage_a: Mapped[int] = mapped_column(Integer, default=20)
    power_in_use_va: Mapped[int] = mapped_column(Integer, default=0)

    # Status
    is_active: Mapped[bool] = mapped_column(default=True)
    is_redundant: Mapped[bool] = mapped_column(default=False)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    organization: Mapped[Organization] = relationship(back_populates="circuits")
    location: Mapped[Location | None] = relationship(back_populates="circuits")
    powered_devices: Mapped[list[PoweredDevice]] = relationship(
        back_populates="circuit",
        cascade="all, delete-orphan",
    )


class PoweredDevice(Base):
    """Link between circuits and devices (for power tracking).

    A device can have multiple power supplies on different circuits.
    """

    __tablename__ = "powered_devices"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    circuit_id: Mapped[UUID] = mapped_column(
        ForeignKey("circuits.id", ondelete="CASCADE"),
        index=True,
    )
    configuration_id: Mapped[UUID] = mapped_column(
        ForeignKey("configurations.id", ondelete="CASCADE"),
        index=True,
    )

    # Power supply identifier
    psu_number: Mapped[int] = mapped_column(Integer, default=1)
    power_draw_va: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    circuit: Mapped[Circuit] = relationship(back_populates="powered_devices")
    configuration: Mapped[Configuration] = relationship(back_populates="power_connections")

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
