---
name: skra-api-patterns
description: |
  FastAPI + SQLAlchemy patterns for Skra backend (skra repo).
  Use when adding new entities, APIs, repositories, or database operations.
  Triggers: "add entity", "create API", "new repository", "add router", 
  "create migration", "org-scoped query", "new model", "add endpoint".
---

# Skra API Patterns

Reusable patterns for Skra backend (MTG-Thomas/skra repo) using FastAPI, SQLAlchemy, and async PostgreSQL.

## Quick Start: Add New Entity

Example: Adding a "Checklist" entity

```bash
# 1. Create ORM Model
# src/models/orm/checklist.py

# 2. Create Repository  
# src/repositories/checklist.py

# 3. Create Contracts
# src/models/contracts/checklist.py

# 4. Create Router
# src/routers/checklists.py

# 5. Create Migration
# alembic/versions/

# 6. Register in main.py
```

## Architecture Principles

| Principle | Implementation |
|-----------|----------------|
| **Organization-scoped** | Every entity has `organization_id` FK |
| **Soft deletes** | Use `is_enabled` flag, never hard delete |
| **Audit fields** | `created_at`, `updated_at`, `updated_by_user_id` |
| **Type safety** | Pydantic v2 with strict annotations |
| **Async** | `async/await` with SQLAlchemy async session |
| **Repositories** | All DB access through repository layer |

## ORM Model Template

```python
"""Checklist ORM model."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.orm.base import Base

if TYPE_CHECKING:
    from src.models.orm.organization import Organization
    from src.models.orm.user import User


class Checklist(Base):
    """Checklist database table."""

    __tablename__ = "checklists"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    
    # Audit fields
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
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship()
    updated_by: Mapped["User | None"] = relationship()
```

## Repository Template

```python
"""Checklist Repository."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm.checklist import Checklist
from src.repositories.base import BaseRepository


class ChecklistRepository(BaseRepository[Checklist]):
    """Repository for Checklist model operations."""

    model = Checklist

    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def list_by_organization(
        self,
        organization_id: UUID,
        search: str | None = None,
        is_enabled: bool | None = True,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Checklist]:
        """List checklists for an organization."""
        query = select(Checklist).where(
            Checklist.organization_id == organization_id
        )

        if is_enabled is not None:
            query = query.where(Checklist.is_enabled == is_enabled)

        if search:
            query = query.where(Checklist.name.ilike(f"%{search}%"))

        query = query.order_by(Checklist.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_id_and_org(
        self,
        checklist_id: UUID,
        organization_id: UUID,
    ) -> Checklist | None:
        """Get checklist by ID within organization."""
        result = await self.session.execute(
            select(Checklist).where(
                Checklist.id == checklist_id,
                Checklist.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()
```

## Pydantic Contracts Template

```python
"""Checklist Pydantic contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ChecklistBase(BaseModel):
    """Base Checklist fields."""
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)


class ChecklistCreate(ChecklistBase):
    """Fields to create a Checklist."""
    pass


class ChecklistUpdate(BaseModel):
    """Fields to update a Checklist."""
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    is_enabled: bool | None = None


class ChecklistPublic(ChecklistBase):
    """Checklist response model."""
    id: UUID
    organization_id: UUID
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    updated_by_user_id: UUID | None

    class Config:
        from_attributes = True


class ChecklistListResponse(BaseModel):
    """Paginated list of checklists."""
    items: list[ChecklistPublic]
    total: int
    limit: int
    offset: int
```

## Router Template (CRUD)

```python
"""Checklist Router."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from src.core.auth import CurrentActiveUser
from src.core.database import DbSession
from src.models.contracts.checklist import (
    ChecklistCreate,
    ChecklistListResponse,
    ChecklistPublic,
    ChecklistUpdate,
)
from src.models.orm.checklist import Checklist
from src.repositories.checklist import ChecklistRepository
from src.services.audit import log_entity_change

router = APIRouter(
    prefix="/api/organizations/{org_id}/checklists",
    tags=["checklists"],
)


@router.get("", response_model=ChecklistListResponse)
async def list_checklists(
    org_id: UUID,
    current_user: CurrentActiveUser,
    db: DbSession,
    search: str | None = Query(None),
    is_enabled: bool | None = Query(True),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> ChecklistListResponse:
    """List checklists for an organization."""
    repo = ChecklistRepository(db)
    
    items = await repo.list_by_organization(
        organization_id=org_id,
        search=search,
        is_enabled=is_enabled,
        limit=limit,
        offset=offset,
    )
    total = await repo.count_by_organization(org_id, is_enabled=is_enabled)

    return ChecklistListResponse(
        items=[ChecklistPublic.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=ChecklistPublic, status_code=status.HTTP_201_CREATED)
async def create_checklist(
    org_id: UUID,
    data: ChecklistCreate,
    current_user: CurrentActiveUser,
    db: DbSession,
) -> ChecklistPublic:
    """Create a new checklist."""
    repo = ChecklistRepository(db)

    checklist = Checklist(
        organization_id=org_id,
        name=data.name,
        description=data.description,
        updated_by_user_id=current_user.user_id,
    )

    await repo.create(checklist)
    await db.flush()
    
    await log_entity_change(
        db=db,
        action="create",
        entity_type="checklist",
        entity_id=checklist.id,
        user_id=current_user.user_id,
        organization_id=org_id,
        new_values=data.model_dump(),
    )

    return ChecklistPublic.model_validate(checklist)


@router.get("/{checklist_id}", response_model=ChecklistPublic)
async def get_checklist(
    org_id: UUID,
    checklist_id: UUID,
    current_user: CurrentActiveUser,
    db: DbSession,
) -> ChecklistPublic:
    """Get a specific checklist."""
    repo = ChecklistRepository(db)
    checklist = await repo.get_by_id_and_org(checklist_id, org_id)

    if not checklist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Checklist not found",
        )

    return ChecklistPublic.model_validate(checklist)


@router.put("/{checklist_id}", response_model=ChecklistPublic)
async def update_checklist(
    org_id: UUID,
    checklist_id: UUID,
    data: ChecklistUpdate,
    current_user: CurrentActiveUser,
    db: DbSession,
) -> ChecklistPublic:
    """Update a checklist."""
    repo = ChecklistRepository(db)
    checklist = await repo.get_by_id_and_org(checklist_id, org_id)

    if not checklist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Checklist not found",
        )

    # Track changes for audit
    old_values = {}
    new_values = {}

    if data.name is not None and data.name != checklist.name:
        old_values["name"] = checklist.name
        checklist.name = data.name
        new_values["name"] = data.name

    if data.description is not None and data.description != checklist.description:
        old_values["description"] = checklist.description
        checklist.description = data.description
        new_values["description"] = data.description

    if data.is_enabled is not None and data.is_enabled != checklist.is_enabled:
        old_values["is_enabled"] = checklist.is_enabled
        checklist.is_enabled = data.is_enabled
        new_values["is_enabled"] = data.is_enabled

    checklist.updated_by_user_id = current_user.user_id
    await db.flush()

    await log_entity_change(
        db=db,
        action="update",
        entity_type="checklist",
        entity_id=checklist.id,
        user_id=current_user.user_id,
        organization_id=org_id,
        old_values=old_values or None,
        new_values=new_values or None,
    )

    return ChecklistPublic.model_validate(checklist)


@router.delete("/{checklist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_checklist(
    org_id: UUID,
    checklist_id: UUID,
    current_user: CurrentActiveUser,
    db: DbSession,
) -> None:
    """Soft delete a checklist (sets is_enabled=False)."""
    repo = ChecklistRepository(db)
    checklist = await repo.get_by_id_and_org(checklist_id, org_id)

    if not checklist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Checklist not found",
        )

    checklist.is_enabled = False
    checklist.updated_by_user_id = current_user.user_id
    await db.flush()

    await log_entity_change(
        db=db,
        action="delete",
        entity_type="checklist",
        entity_id=checklist.id,
        user_id=current_user.user_id,
        organization_id=org_id,
    )
```

## Alembic Migration Template

```python
"""Add checklists table

Revision ID: XXX
Revises: YYY
Create Date: 2026-04-06 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "XXX"
down_revision: str | None = "YYY"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "checklists",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_by_user_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    
    op.create_index("ix_checklists_org_id", "checklists", ["organization_id"])
    op.create_index("ix_checklists_org_enabled", "checklists", ["organization_id", "is_enabled"])


def downgrade() -> None:
    op.drop_index("ix_checklists_org_enabled", table_name="checklists")
    op.drop_index("ix_checklists_org_id", table_name="checklists")
    op.drop_table("checklists")
```

## Registration in main.py

```python
# Import router
from src.routers.checklists import router as checklists_router

# Add to FastAPI app
app.include_router(checklists_router)
```

## Reference Files

| File | Contents |
|------|----------|
| [references/acceptance-criteria.md](references/acceptance-criteria.md) | Correct/incorrect patterns for review |
| [references/orm-patterns.md](references/orm-patterns.md) | SQLAlchemy ORM patterns |
| [references/repository-patterns.md](references/repository-patterns.md) | Repository layer patterns |
| [references/router-patterns.md](references/router-patterns.md) | FastAPI router patterns |

## Related

- Repo: `MTG-Thomas/skra`
- Stack: FastAPI, SQLAlchemy, PostgreSQL, Pydantic v2
