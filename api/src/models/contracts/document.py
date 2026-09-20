"""Document contracts (API request/response schemas)."""

from pydantic import BaseModel, Field

from src.models.contracts.base import PublicEntityBase
from src.models.contracts.sync import SyncMetadata


class DocumentCreate(BaseModel):
    """Document creation request model."""

    path: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        description="Virtual folder path, e.g., /Infrastructure/Network/Diagrams",
    )
    name: str = Field(..., min_length=1, max_length=255, description="Document title")
    content: str = Field(default="", description="Markdown content")
    metadata: dict | None = Field(default=None, description="External system metadata")
    sync_metadata: SyncMetadata | None = None
    is_enabled: bool | None = None  # Defaults to True if not provided


class DocumentUpdate(BaseModel):
    """Document update request model."""

    path: str | None = Field(
        default=None,
        min_length=1,
        max_length=1024,
        description="Virtual folder path",
    )
    name: str | None = Field(
        default=None, min_length=1, max_length=255, description="Document title"
    )
    content: str | None = Field(default=None, description="Markdown content")
    metadata: dict | None = Field(default=None, description="External system metadata")
    sync_metadata: SyncMetadata | None = None
    is_enabled: bool | None = None  # Don't change if not provided


class DocumentPublic(PublicEntityBase):
    """Document public response model."""

    path: str
    name: str
    content: str
    sync_metadata: SyncMetadata | None = None
    updated_by_user_id: str | None = None
    updated_by_user_name: str | None = None


class FolderCount(BaseModel):
    """Folder with document count."""

    path: str = Field(..., description="Folder path")
    count: int = Field(..., ge=0, description="Number of documents in this folder")


class FolderList(BaseModel):
    """List of distinct folder paths with document counts."""

    folders: list[FolderCount] = Field(
        default_factory=list, description="List of folders with document counts"
    )
