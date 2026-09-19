"""
DCIM (Data Center Infrastructure Management) models for Skra.

Rack and RackDevice models for physical infrastructure tracking.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.orm.base import Base

if TYPE_CHECKING:
    from src.models.orm.configuration import Configuration
    from src.models.orm.location import Location
    from src.models.orm.organization import Organization
    from src.models.orm.patch_panel import PatchPanel


class Rack(Base):
    """Physical rack for equipment mounting.

    Tracks U-height positions, power circuits, and installed equipment.
    """

    __tablename__ = "racks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
    )
    location_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    # Rack details
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    rack_units: Mapped[int] = mapped_column(Integer, default=42)
    width_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    depth_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Physical location within facility
    row: Mapped[str | None] = mapped_column(String(50), nullable=True)
    position: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Power circuits serving this rack (JSON array)
    power_circuits: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Power capacity tracking
    power_capacity_va: Mapped[int | None] = mapped_column(Integer, nullable=True)
    power_in_use_va: Mapped[int | None] = mapped_column(Integer, default=0)

    # Weight capacity
    weight_capacity_kg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_in_use_kg: Mapped[int | None] = mapped_column(Integer, default=0)

    # Metadata
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(default=True)

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

    # Relationships
    organization: Mapped[Organization] = relationship(back_populates="racks")
    location: Mapped[Location | None] = relationship(back_populates="racks")
    devices: Mapped[list[RackDevice]] = relationship(
        back_populates="rack",
        order_by="RackDevice.u_position",
        cascade="all, delete-orphan",
    )
    patch_panels: Mapped[list[PatchPanel]] = relationship(
        back_populates="rack",
        cascade="all, delete-orphan",
    )


class RackDevice(Base):
    """Device installed in a rack position.

    Links configurations to physical rack positions with U-height tracking.
    """

    __tablename__ = "rack_devices"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    rack_id: Mapped[UUID] = mapped_column(
        ForeignKey("racks.id", ondelete="CASCADE"),
        index=True,
    )
    configuration_id: Mapped[UUID] = mapped_column(
        ForeignKey("configurations.id", ondelete="CASCADE"),
        index=True,
        unique=True,
    )

    # Position within rack
    u_position: Mapped[int] = mapped_column(Integer, nullable=False)
    u_height: Mapped[int] = mapped_column(Integer, default=1)

    # Orientation
    mounted_rear: Mapped[bool] = mapped_column(default=False)

    # Power connections
    power_circuit_a: Mapped[str | None] = mapped_column(String(50), nullable=True)
    power_circuit_b: Mapped[str | None] = mapped_column(String(50), nullable=True)
    power_draw_va: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Cable management
    cable_arm_side: Mapped[str | None] = mapped_column(String(10), nullable=True)

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

    # Relationships
    rack: Mapped[Rack] = relationship(back_populates="devices")
    configuration: Mapped[Configuration] = relationship(back_populates="rack_device")
