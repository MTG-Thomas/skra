"""Custom Asset contracts (API request/response schemas).

Defines field definitions for custom asset types and the contracts
for both custom asset types and custom asset instances.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from src.models.contracts.base import PublicEntityBase
from src.models.contracts.sync import SyncMetadata

# =============================================================================
# Field Definition Schema
# =============================================================================


class ChecklistItemDefinition(BaseModel):
    """
    Definition of a single step in a checklist field.

    The `id` is stable across definition edits so completion history survives
    renames and reorders. The `required` flag marks mandatory steps for
    display; completion enforcement is left to close-out flows.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    label: str
    required: bool = False


class FieldDefinition(BaseModel):
    """
    Definition of a single field in a custom asset type.

    This defines the schema for fields that can be added to custom asset types.
    The `id` is a stable identifier used for value storage, while `key` is
    the human-readable identifier used in API requests/responses.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))  # stable storage identifier
    key: str  # human-readable identifier for API
    name: str  # display name
    type: Literal[
        "text",
        "textbox",
        "number",
        "date",
        "checkbox",
        "select",
        "header",
        "password",
        "totp",
        "checklist",
    ]
    required: bool = False
    show_in_list: bool = False
    hint: str | None = None
    default_value: str | None = None
    options: list[str] | None = None  # required for select type
    checklist_items: list[ChecklistItemDefinition] | None = None  # required for checklist type
    expiration_alert: bool = False  # only meaningful on date fields (issue #40)

    @field_validator("options")
    @classmethod
    def validate_options(cls, v: list[str] | None, info) -> list[str] | None:
        """Validate that select type has options."""
        field_type = info.data.get("type")
        if field_type == "select" and (not v or len(v) == 0):
            raise ValueError("Select field type requires options")
        return v

    @field_validator("checklist_items")
    @classmethod
    def validate_checklist_items(
        cls, v: list[ChecklistItemDefinition] | None, info
    ) -> list[ChecklistItemDefinition] | None:
        """Validate checklist items: required, non-empty labels, unique ids."""
        field_type = info.data.get("type")
        if field_type == "checklist":
            if not v or len(v) == 0:
                raise ValueError("Checklist field type requires at least one item")
            labels = [item.label.strip() for item in v]
            if any(not label for label in labels):
                raise ValueError("Checklist items must have non-empty labels")
            ids = [item.id for item in v]
            if len(ids) != len(set(ids)):
                raise ValueError("Checklist item ids must be unique within a field")
        return v

    @field_validator("expiration_alert")
    @classmethod
    def validate_expiration_alert(cls, v: bool, info) -> bool:
        """Validate that expiration alerts are only set on date fields."""
        if v and info.data.get("type") != "date":
            raise ValueError("expiration_alert is only supported on date fields")
        return v


# =============================================================================
# Custom Asset Type Contracts
# =============================================================================


class CustomAssetTypeCreate(BaseModel):
    """Custom asset type creation request model."""

    model_config = ConfigDict(extra="forbid")

    name: str
    fields: list[FieldDefinition]
    display_field_key: str | None = None

    @field_validator("fields")
    @classmethod
    def validate_unique_keys(cls, v: list[FieldDefinition]) -> list[FieldDefinition]:
        """Validate that all field keys are unique."""
        keys = [f.key for f in v]
        if len(keys) != len(set(keys)):
            raise ValueError("Field keys must be unique within a custom asset type")
        return v


class CustomAssetTypeUpdate(BaseModel):
    """Custom asset type update request model."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    fields: list[FieldDefinition] | None = None
    display_field_key: str | None = None

    @field_validator("fields")
    @classmethod
    def validate_unique_keys(cls, v: list[FieldDefinition] | None) -> list[FieldDefinition] | None:
        """Validate that all field keys are unique."""
        if v is None:
            return v
        keys = [f.key for f in v]
        if len(keys) != len(set(keys)):
            raise ValueError("Field keys must be unique within a custom asset type")
        return v


class CustomAssetTypeReorder(BaseModel):
    """Custom asset type reorder request model."""

    model_config = ConfigDict(extra="forbid")

    ids: list[str]  # Ordered list of custom asset type IDs


class CustomAssetTypePublic(BaseModel):
    """Custom asset type public response model (global, not org-scoped)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    fields: list[FieldDefinition]
    sort_order: int = 0
    display_field_key: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    asset_count: int = 0

    @field_serializer("id")
    def serialize_uuid(self, v: UUID) -> str:
        return str(v)


# =============================================================================
# Custom Asset Instance Contracts
# =============================================================================


class CustomAssetCreate(BaseModel):
    """Custom asset creation request model."""

    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any]  # validated against type's fields in service layer
    metadata: dict | None = None
    sync_metadata: SyncMetadata | None = None
    is_enabled: bool | None = None  # Defaults to True if not provided


class CustomAssetUpdate(BaseModel):
    """Custom asset update request model."""

    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any] | None = None  # validated against type's fields in service layer
    metadata: dict | None = None
    sync_metadata: SyncMetadata | None = None
    is_enabled: bool | None = None  # Don't change if not provided


class CustomAssetPublic(PublicEntityBase):
    """
    Custom asset public response model.

    Password fields are excluded from values.
    """

    custom_asset_type_id: UUID
    values: dict[str, Any]  # password fields excluded
    sync_metadata: SyncMetadata | None = None
    updated_by_user_id: str | None = None
    updated_by_user_name: str | None = None

    @field_serializer("custom_asset_type_id")
    def serialize_fk_uuid(self, v: UUID) -> str:
        """Serialize foreign key UUID to string."""
        return str(v)


class CustomAssetReveal(PublicEntityBase):
    """
    Custom asset reveal response model.

    Includes decrypted password field values.
    """

    custom_asset_type_id: UUID
    values: dict[str, Any]  # includes decrypted password fields
    sync_metadata: SyncMetadata | None = None
    updated_by_user_id: str | None = None
    updated_by_user_name: str | None = None

    @field_serializer("custom_asset_type_id")
    def serialize_fk_uuid(self, v: UUID) -> str:
        """Serialize foreign key UUID to string."""
        return str(v)
