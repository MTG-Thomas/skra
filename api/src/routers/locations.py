"""
Locations Router

Provides CRUD endpoints for locations within an organization.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import update

from src.core.auth import CurrentActiveUser, RequireContributor
from src.core.database import DbSession
from src.models.contracts.common import BatchToggleRequest, BatchToggleResponse
from src.models.contracts.location import (
    LocationCreate,
    LocationPublic,
    LocationUpdate,
)
from src.models.contracts.sync import sync_metadata_to_storage
from src.models.enums import AuditAction
from src.models.orm.location import Location
from src.repositories.location import LocationRepository
from src.services.audit_service import get_audit_service
from src.services.search_indexing import index_entity_for_search, remove_entity_from_search


class LocationListResponse(BaseModel):
    """Paginated response for location list."""

    items: list[LocationPublic]
    total: int
    limit: int
    offset: int


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/organizations/{org_id}/locations", tags=["locations"])


def _to_public(location: Location) -> LocationPublic:
    """Convert Location ORM model to public response."""
    # Get base fields from ORM model using getattr for defensive access
    # (handles both real ORM objects and test mocks)
    metadata_value = getattr(location, "metadata_", None)
    metadata = metadata_value if isinstance(metadata_value, dict) else {}
    sync_metadata_value = getattr(location, "sync_metadata", None)
    sync_metadata = (
        sync_metadata_value
        if isinstance(sync_metadata_value, dict) and sync_metadata_value
        else None
    )

    updated_by_user = getattr(location, "updated_by_user", None)
    data = {
        "id": getattr(location, "id", None),
        "organization_id": getattr(location, "organization_id", None),
        "name": getattr(location, "name", ""),
        "notes": getattr(location, "notes", None),
        "metadata": metadata,
        "sync_metadata": sync_metadata,
        "is_enabled": getattr(location, "is_enabled", True),
        "created_at": getattr(location, "created_at", None),
        "updated_at": getattr(location, "updated_at", None),
        "address_1": getattr(location, "address_1", None),
        "address_2": getattr(location, "address_2", None),
        "city": getattr(location, "city", None),
        "region": getattr(location, "region", None),
        "postal_code": getattr(location, "postal_code", None),
        "country": getattr(location, "country", None),
        "phone": getattr(location, "phone", None),
        "updated_by_user_id": str(location.updated_by_user_id)
        if getattr(location, "updated_by_user_id", None)
        else None,
        "updated_by_user_name": updated_by_user.email if updated_by_user else None,
    }

    return LocationPublic.model_validate(data)


@router.get("", response_model=LocationListResponse)
async def list_locations(
    org_id: UUID,
    current_user: CurrentActiveUser,
    db: DbSession,
    search: str | None = Query(None, description="Search by name or notes"),
    region: str | None = Query(None, description="Filter by region (state/province)"),
    sort_by: str | None = Query(None, description="Column to sort by"),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$", description="Sort direction"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results per page"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    show_disabled: bool = Query(False, description="Include disabled locations"),
) -> LocationListResponse:
    """
    List all locations for an organization with pagination and search.

    Args:
        org_id: Organization UUID
        current_user: Current authenticated user
        db: Database session
        search: Optional search term
        region: Optional filter by region (state/province)
        sort_by: Column to sort by
        sort_dir: Sort direction ("asc" or "desc")
        limit: Maximum number of results
        offset: Number of results to skip
        show_disabled: Include disabled locations

    Returns:
        Paginated list of locations
    """
    location_repo = LocationRepository(db)
    # Filter by is_enabled: when show_disabled=False, only show enabled (True)
    # When show_disabled=True, show all (None filter)
    is_enabled_filter = None if show_disabled else True
    locations, total = await location_repo.get_paginated_by_org(
        org_id,
        search=search,
        region=region,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
        is_enabled=is_enabled_filter,
    )

    return LocationListResponse(
        items=[_to_public(loc) for loc in locations],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=LocationPublic, status_code=status.HTTP_201_CREATED)
async def create_location(
    org_id: UUID,
    location_data: LocationCreate,
    current_user: RequireContributor,
    db: DbSession,
) -> LocationPublic:
    """
    Create a new location within an organization.

    Args:
        org_id: Organization UUID
        location_data: Location creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Created location
    """
    location_repo = LocationRepository(db)

    # Create location
    location = Location(
        organization_id=org_id,
        name=location_data.name,
        notes=location_data.notes,
        metadata_=location_data.metadata,
        sync_metadata=sync_metadata_to_storage(location_data.sync_metadata),
        is_enabled=location_data.is_enabled if location_data.is_enabled is not None else True,
        address_1=location_data.address_1,
        address_2=location_data.address_2,
        city=location_data.city,
        region=location_data.region,
        postal_code=location_data.postal_code,
        country=location_data.country,
        phone=location_data.phone,
    )
    location = await location_repo.create(location)

    # Audit log
    audit_service = get_audit_service(db)
    await audit_service.log(
        AuditAction.CREATE,
        "location",
        location.id,
        actor=current_user,
        organization_id=org_id,
    )

    logger.info(
        f"Location created: {location.name}",
        extra={
            "location_id": str(location.id),
            "org_id": str(org_id),
            "user_id": str(current_user.user_id),
        },
    )

    # Index for search (async, non-blocking on failure)
    await index_entity_for_search(db, "location", location.id, org_id)

    return _to_public(location)


@router.get("/{location_id}", response_model=LocationPublic)
async def get_location(
    org_id: UUID,
    location_id: UUID,
    current_user: CurrentActiveUser,
    db: DbSession,
) -> LocationPublic:
    """
    Get a location by ID.

    Args:
        org_id: Organization UUID
        location_id: Location UUID
        current_user: Current authenticated user
        db: Database session

    Returns:
        Location details

    Raises:
        HTTPException: If location not found
    """
    location_repo = LocationRepository(db)
    location = await location_repo.get_by_id_and_organization(location_id, org_id)

    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location not found",
        )

    # Log view (with 60-second dedupe)
    audit_service = get_audit_service(db)
    await audit_service.log(
        AuditAction.VIEW,
        "location",
        location.id,
        actor=current_user,
        organization_id=org_id,
        dedupe_seconds=60,
    )

    return _to_public(location)


@router.get("/{location_id}/preview")
async def get_location_preview(
    org_id: UUID,
    location_id: UUID,
    current_user: CurrentActiveUser,
    db: DbSession,
) -> dict:
    """
    Get location preview for search.

    Returns formatted markdown content suitable for rendering in a preview panel.

    Args:
        org_id: Organization UUID
        location_id: Location UUID
        current_user: Current authenticated user
        db: Database session

    Returns:
        Preview data with formatted content

    Raises:
        HTTPException: If location not found
    """
    location_repo = LocationRepository(db)
    location = await location_repo.get_by_id_and_organization(location_id, org_id)

    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location not found",
        )

    # Build preview content
    content_parts = [f"# {location.name}"]

    # Build address from actual fields
    if location.address_1:
        content_parts.append(f"\n**Address:** {location.address_1}")
        if location.address_2:
            content_parts.append(f"  {location.address_2}")
    if location.city or location.region or location.postal_code:
        city_region_postal = ""
        if location.city:
            city_region_postal = location.city
        if location.region:
            if city_region_postal:
                city_region_postal += f", {location.region}"
            else:
                city_region_postal = location.region
        if location.postal_code:
            if city_region_postal:
                city_region_postal += f" {location.postal_code}"
            else:
                city_region_postal = location.postal_code
        content_parts.append(f"\n**City:** {city_region_postal}")
    if location.country:
        content_parts.append(f"\n**Country:** {location.country}")
    if location.phone:
        content_parts.append(f"\n**Phone:** {location.phone}")

    # Fall back to metadata for email (if still stored there)
    metadata = location.metadata_ if isinstance(location.metadata_, dict) else {}
    if metadata.get("email"):
        content_parts.append(f"\n**Email:** {metadata['email']}")
    if location.notes:
        content_parts.append(f"\n## Notes\n{location.notes}")

    return {
        "id": str(location.id),
        "name": location.name,
        "content": "\n".join(content_parts),
        "entity_type": "location",
        "organization_id": str(org_id),
    }


@router.put("/{location_id}", response_model=LocationPublic)
async def update_location(
    org_id: UUID,
    location_id: UUID,
    location_data: LocationUpdate,
    current_user: RequireContributor,
    db: DbSession,
) -> LocationPublic:
    """
    Update a location.

    Args:
        org_id: Organization UUID
        location_id: Location UUID
        location_data: Location update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Updated location

    Raises:
        HTTPException: If location not found
    """
    location_repo = LocationRepository(db)
    location = await location_repo.get_by_id_and_organization(location_id, org_id)

    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location not found",
        )

    # Update fields
    if location_data.name is not None:
        location.name = location_data.name
    if location_data.notes is not None:
        location.notes = location_data.notes
    if location_data.metadata is not None:
        location.metadata_ = location_data.metadata
    if location_data.sync_metadata is not None:
        location.sync_metadata = sync_metadata_to_storage(location_data.sync_metadata)
    if location_data.is_enabled is not None:
        location.is_enabled = location_data.is_enabled
    if location_data.address_1 is not None:
        location.address_1 = location_data.address_1
    if location_data.address_2 is not None:
        location.address_2 = location_data.address_2
    if location_data.city is not None:
        location.city = location_data.city
    if location_data.region is not None:
        location.region = location_data.region
    if location_data.postal_code is not None:
        location.postal_code = location_data.postal_code
    if location_data.country is not None:
        location.country = location_data.country
    if location_data.phone is not None:
        location.phone = location_data.phone

    # Track who updated
    location.updated_by_user_id = current_user.user_id

    location = await location_repo.update(location)

    # Audit log
    audit_service = get_audit_service(db)
    await audit_service.log(
        AuditAction.UPDATE,
        "location",
        location.id,
        actor=current_user,
        organization_id=org_id,
    )

    logger.info(
        f"Location updated: {location.name}",
        extra={
            "location_id": str(location.id),
            "org_id": str(org_id),
            "user_id": str(current_user.user_id),
        },
    )

    # Update search index (async, non-blocking on failure)
    await index_entity_for_search(db, "location", location.id, org_id)

    return _to_public(location)


@router.delete("/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_location(
    org_id: UUID,
    location_id: UUID,
    current_user: RequireContributor,
    db: DbSession,
) -> None:
    """
    Delete a location.

    Args:
        org_id: Organization UUID
        location_id: Location UUID
        current_user: Current authenticated user
        db: Database session

    Raises:
        HTTPException: If location not found
    """
    location_repo = LocationRepository(db)
    location = await location_repo.get_by_id_and_organization(location_id, org_id)

    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location not found",
        )

    # Audit log (before delete)
    audit_service = get_audit_service(db)
    await audit_service.log(
        AuditAction.DELETE,
        "location",
        location_id,
        actor=current_user,
        organization_id=org_id,
    )

    await location_repo.delete(location)

    # Remove from search index (async, non-blocking on failure)
    await remove_entity_from_search(db, "location", location_id)

    logger.info(
        f"Location deleted: {location.name}",
        extra={
            "location_id": str(location.id),
            "org_id": str(org_id),
            "user_id": str(current_user.user_id),
        },
    )


@router.patch("/batch/toggle", response_model=BatchToggleResponse)
async def batch_toggle_locations(
    org_id: UUID,
    request: BatchToggleRequest,
    current_user: RequireContributor,
    db: DbSession,
) -> BatchToggleResponse:
    """
    Batch activate/deactivate locations.

    Args:
        org_id: Organization UUID
        request: Batch toggle request with IDs and new is_enabled value
        current_user: Current authenticated user
        db: Database session

    Returns:
        Number of locations updated
    """
    # Convert string IDs to UUIDs
    location_ids = [UUID(id_str) for id_str in request.ids]

    # Batch update
    result = await db.execute(
        update(Location)
        .where(Location.id.in_(location_ids))
        .where(Location.organization_id == org_id)
        .values(is_enabled=request.is_enabled)
    )
    await db.commit()

    logger.info(
        f"Batch toggle locations: {result.rowcount} locations set to is_enabled={request.is_enabled}",  # type: ignore[attr-defined]
        extra={
            "org_id": str(org_id),
            "user_id": str(current_user.user_id),
            "updated_count": result.rowcount,  # type: ignore[attr-defined]
        },
    )

    # Update search index for each affected location
    # The worker will index if enabled, remove from index if disabled
    for location_id in location_ids:
        await index_entity_for_search(db, "location", location_id, org_id)

    return BatchToggleResponse(updated_count=result.rowcount)  # type: ignore[attr-defined]
