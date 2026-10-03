"""
Patch panel models for structured cabling management.

Tracks front (patch) and rear (permanent) port connections.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.orm.base import Base

if TYPE_CHECKING:
    from src.models.orm.cable import Cable
    from src.models.orm.location import Location
    from src.models.orm.organization import Organization

    # rack imports this module, so importing it here would close an import
    # cycle (CodeQL py/unsafe-cyclic-import). Alias as Any instead;
    # SQLAlchemy resolves the string annotations via its class registry.
    Rack = Any


class PatchPanel(Base):
    """Patch panel for structured cabling management.

    Tracks front (patch) and rear (permanent) ports.
    """

    __tablename__ = "patch_panels"

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
    rack_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("racks.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    panel_type: Mapped[str] = mapped_column(String(50), default="cat6")
    port_count: Mapped[int] = mapped_column(Integer, default=24)

    # Physical position
    u_position: Mapped[int | None] = mapped_column(Integer, nullable=True)

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
    organization: Mapped[Organization] = relationship(back_populates="patch_panels")
    location: Mapped[Location | None] = relationship(back_populates="patch_panels")
    rack: Mapped[Rack | None] = relationship(back_populates="patch_panels")
    ports: Mapped[list[PatchPanelPort]] = relationship(
        back_populates="panel",
        cascade="all, delete-orphan",
    )


class PatchPanelPort(Base):
    """Individual port on a patch panel."""

    __tablename__ = "patch_panel_ports"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    panel_id: Mapped[UUID] = mapped_column(
        ForeignKey("patch_panels.id", ondelete="CASCADE"),
        index=True,
    )

    port_number: Mapped[int] = mapped_column(Integer, nullable=False)
    port_type: Mapped[str] = mapped_column(String(50), default="rj45")

    # Front side (patch connection)
    front_cable_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("cables.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Rear side (permanent connection)
    rear_cable_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("cables.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Label/notes
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vlan_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Relationships
    panel: Mapped[PatchPanel] = relationship(back_populates="ports")
    front_cable: Mapped[Cable | None] = relationship(foreign_keys=[front_cable_id])
    rear_cable: Mapped[Cable | None] = relationship(foreign_keys=[rear_cable_id])

    __table_args__ = (UniqueConstraint("panel_id", "port_number", name="uq_panel_port"),)

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
