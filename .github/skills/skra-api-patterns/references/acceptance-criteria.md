# Acceptance Criteria: skra-api-patterns

**Repository:** `MTG-Thomas/skra`  
**Purpose:** Validate backend patterns for FastAPI + SQLAlchemy development

---

## 1. ORM Model Patterns

### ✅ CORRECT: Organization-Scoped Model

```python
class Checklist(Base):
    __tablename__ = "checklists"
    
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,  # Index for performance
    )
```

### ❌ INCORRECT: Missing Organization Scope

```python
class Checklist(Base):
    __tablename__ = "checklists"
    
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # WRONG: Missing organization_id FK
    name: Mapped[str] = mapped_column(String(255))
```

### ✅ CORRECT: Audit Fields

```python
class Checklist(Base):
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
```

### ❌ INCORRECT: Missing Timezone or Server Defaults

```python
class Checklist(Base):
    created_at: Mapped[datetime] = mapped_column(DateTime)  # WRONG: No timezone
    updated_at: Mapped[datetime] = mapped_column(DateTime)  # WRONG: No server_default
```

---

## 2. Repository Patterns

### ✅ CORRECT: Organization-Scoped Query

```python
async def get_by_id_and_org(
    self,
    checklist_id: UUID,
    organization_id: UUID,
) -> Checklist | None:
    """Get by ID within organization."""
    result = await self.session.execute(
        select(Checklist).where(
            Checklist.id == checklist_id,
            Checklist.organization_id == organization_id,  # Scope check
        )
    )
    return result.scalar_one_or_none()
```

### ❌ INCORRECT: No Organization Check

```python
async def get_by_id(self, checklist_id: UUID) -> Checklist | None:
    """WRONG: No org check allows cross-org access!"""
    result = await self.session.execute(
        select(Checklist).where(Checklist.id == checklist_id)
    )
    return result.scalar_one_or_none()
```

### ✅ CORRECT: List with Pagination

```python
async def list_by_organization(
    self,
    organization_id: UUID,
    limit: int = 100,
    offset: int = 0,
) -> list[Checklist]:
    query = select(Checklist).where(
        Checklist.organization_id == organization_id
    )
    query = query.order_by(Checklist.created_at.desc())
    query = query.limit(limit).offset(offset)  # Pagination
    
    result = await self.session.execute(query)
    return list(result.scalars().all())
```

---

## 3. Router Patterns

### ✅ CORRECT: Router Prefix

```python
router = APIRouter(
    prefix="/api/organizations/{org_id}/checklists",
    tags=["checklists"],
)
```

### ❌ INCORRECT: Wrong Prefix

```python
router = APIRouter(
    prefix="/api/checklists",  # WRONG: Missing org scope
    tags=["checklists"],
)
```

### ✅ CORRECT: Soft Delete (Not Hard Delete)

```python
@router.delete("/{checklist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_checklist(...) -> None:
    checklist = await repo.get_by_id_and_org(checklist_id, org_id)
    checklist.is_enabled = False  # Soft delete
    checklist.updated_by_user_id = current_user.user_id
    await db.flush()
```

### ❌ INCORRECT: Hard Delete

```python
@router.delete("/{checklist_id}")
async def delete_checklist(...) -> None:
    checklist = await repo.get_by_id_and_org(checklist_id, org_id)
    await repo.delete(checklist)  # WRONG: Hard delete!
```

### ✅ CORRECT: Audit Logging

```python
@router.post("", response_model=ChecklistPublic, status_code=status.HTTP_201_CREATED)
async def create_checklist(...) -> ChecklistPublic:
    checklist = Checklist(...)
    await repo.create(checklist)
    await db.flush()
    
    await log_entity_change(  # Audit log
        db=db,
        action="create",
        entity_type="checklist",
        entity_id=checklist.id,
        user_id=current_user.user_id,
        organization_id=org_id,
        new_values=data.model_dump(),
    )
```

---

## 4. Pydantic Contract Patterns

### ✅ CORRECT: Separate Create/Update/Public

```python
class ChecklistCreate(ChecklistBase):
    """Fields required to create."""
    pass

class ChecklistUpdate(BaseModel):
    """Fields that can be updated (all optional)."""
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    is_enabled: bool | None = None

class ChecklistPublic(ChecklistBase):
    """Full response model."""
    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime
```

### ❌ INCORRECT: Same Model for All

```python
class ChecklistModel(BaseModel):  # WRONG: Don't reuse same model
    """Used for create, update, AND response"""
    id: UUID  # Required for create?
    name: str  # Required for update?
```

---

## 5. Import Patterns

### ✅ CORRECT: Repository Import

```python
from src.repositories.checklist import ChecklistRepository
from src.repositories.base import BaseRepository
```

### ❌ INCORRECT: Importing from Wrong Module

```python
from src.models.repositories.checklist import ChecklistRepository  # WRONG path
```

### ✅ CORRECT: Async Session Type

```python
from sqlalchemy.ext.asyncio import AsyncSession

async def list_items(self, session: AsyncSession) -> list[Item]:
    ...
```

---

## 6. Common Mistakes Checklist

| Mistake | Why It's Wrong | Correct Approach |
|---------|---------------|------------------|
| No `organization_id` FK | Cross-org data leakage | Always add `organization_id` with FK |
| No `index=True` on FK | Slow queries | Index all FK columns |
| Hard delete | Data loss | Use `is_enabled` soft delete |
| No audit fields | No change tracking | Add `created_at`, `updated_at`, `updated_by` |
| Missing `server_default` | DB-level defaults needed | Use `server_default=text("NOW()")` |
| Wrong router prefix | API inconsistency | Use `/api/organizations/{org_id}/...` |
