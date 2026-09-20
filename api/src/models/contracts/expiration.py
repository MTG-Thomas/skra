"""Expiration contracts (API request/response schemas, issue #40)."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


class UpcomingExpirationPublic(BaseModel):
    """One flagged date field approaching or past expiration."""

    organization_id: UUID
    asset_id: UUID
    asset_display: str | None = None
    asset_type_id: UUID
    asset_type_name: str
    field_key: str
    field_name: str
    expires_on: date
    days_until: int
    window_days: int = Field(description="Alert window: 0 means expired")


class UpcomingExpirationsResponse(BaseModel):
    """Org-scoped upcoming expirations."""

    items: list[UpcomingExpirationPublic]
    total: int
    within_days: int


class GlobalUpcomingExpirationPublic(UpcomingExpirationPublic):
    """One flagged expiration with its organization context for global view."""

    organization_name: str


class GlobalUpcomingExpirationsPublic(BaseModel):
    """Cross-organization upcoming expirations with pagination."""

    items: list[GlobalUpcomingExpirationPublic]
    total: int
    within_days: int
    limit: int
    offset: int
