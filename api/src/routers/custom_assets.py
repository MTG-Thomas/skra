"""
Custom Assets Router.

Provides CRUD endpoints for custom asset instances within organizations.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import update

from src.core.auth import CurrentActiveUser, RequireContributor
from src.core.database import DbSession
from src.models.contracts.common import BatchToggleRequest, BatchToggleResponse
from src.models.contracts.custom_asset import (
    CustomAssetCreate,
    CustomAssetPublic,
    CustomAssetReveal,
    CustomAssetUpdate,
    FieldDefinition,
)
from src.models.contracts.sync import sync_metadata_to_storage
from src.models.enums import AuditAction
from src.models.orm.custom_asset import CustomAsset
from src.models.orm.custom_asset_type import CustomAssetType
from src.repositories.custom_asset import CustomAssetRepository
from src.repositories.custom_asset_type import CustomAssetTypeRepository
from src.repositories.expiration_projection import ExpirationProjectionRepository
from src.services.audit_service import get_audit_service
from src.services.custom_asset_validation import (
    CustomAssetValidationError,
    apply_default_values,
    initialize_checklist_values,
    merge_checklist_value,
    validate_values,
    values_id_to_key,
    values_key_to_id,
)
from src.services.expiration_projection import refresh_asset_projection
from src.services.search_indexing import index_entity_for_search, remove_entity_from_search


class CustomAssetListResponse(BaseModel):
    """Paginated response for custom asset list."""

    items: list[CustomAssetPublic]
    total: int
    limit: int
    offset: int


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/organizations/{org_id}/custom-asset-types/{type_id}/assets",
    tags=["custom-assets"],
)


async def _verify_org_access(
    org_id: UUID,
    current_user: CurrentActiveUser,
    db: DbSession,
) -> None:
    """Verify user has access to the organization."""
    # Organization access is now handled by RLS policies
    pass


async def _get_asset_type(
    type_id: UUID,
    db: DbSession,
) -> CustomAssetType:
    """Get and verify custom asset type exists (types are global)."""
    type_repo = CustomAssetTypeRepository(db)
    asset_type = await type_repo.get_by_id(type_id)
    if not asset_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Custom asset type not found",
        )
    return asset_type


def _get_field_definitions(asset_type: CustomAssetType) -> list[FieldDefinition]:
    """Convert asset type fields to FieldDefinition objects."""
    return [FieldDefinition(**f) for f in asset_type.fields]


def _get_display_field_key(asset_type: CustomAssetType) -> str | None:
    """
    Get the display field key for an asset type.

    Priority:
    1. Use explicit display_field_key if set
    2. Fall back to first text/textbox field
    3. Fall back to first non-header, non-checklist field (checklist and
       other structured values don't render as names)
    4. Return None if no suitable field

    Args:
        asset_type: CustomAssetType entity

    Returns:
        Field key to use for display, or None if no suitable field
    """
    if asset_type.display_field_key:
        return asset_type.display_field_key

    fields = _get_field_definitions(asset_type)
    non_header_fields = [f for f in fields if f.type != "header"]

    # Try to find first text/textbox field
    for field in non_header_fields:
        if field.type in ("text", "textbox"):
            return field.key

    # Fall back to first scalar field (skip structured values)
    for field in non_header_fields:
        if field.type != "checklist":
            return field.key

    return None


def _get_display_name(
    asset: CustomAsset,
    asset_type: CustomAssetType,
    type_fields: list[FieldDefinition],
) -> str:
    """
    Get the display name for a custom asset.

    Uses the display field value if available, otherwise falls back to asset ID.

    Args:
        asset: CustomAsset entity
        asset_type: CustomAssetType entity
        type_fields: List of field definitions

    Returns:
        Display name string
    """
    display_field_key = _get_display_field_key(asset_type)
    if not display_field_key:
        return str(asset.id)

    # Transform values to key-based to get the display field. Only plain
    # strings render as names; anything else falls back to the asset ID.
    key_values = values_id_to_key(type_fields, asset.values, filter_secrets=True)
    display_value = key_values.get(display_field_key)
    if isinstance(display_value, str) and display_value:
        return display_value
    return str(asset.id)


def _to_public(
    asset: CustomAsset,
    type_fields: list[FieldDefinition],
) -> CustomAssetPublic:
    """Convert ORM model to public response (password fields filtered)."""
    # Transform from ID-based storage to key-based API format, filtering secrets
    key_values = values_id_to_key(type_fields, asset.values, filter_secrets=True)
    data = {
        "id": asset.id,
        "organization_id": asset.organization_id,
        "custom_asset_type_id": asset.custom_asset_type_id,
        "values": key_values,
        "metadata": asset.metadata_ if isinstance(asset.metadata_, dict) else {},
        "sync_metadata": asset.sync_metadata
        if isinstance(asset.sync_metadata, dict) and asset.sync_metadata
        else None,
        "is_enabled": asset.is_enabled,
        "created_at": asset.created_at,
        "updated_at": asset.updated_at,
        "updated_by_user_id": str(asset.updated_by_user_id) if asset.updated_by_user_id else None,
        "updated_by_user_name": asset.updated_by_user.email if asset.updated_by_user else None,
    }
    return CustomAssetPublic.model_validate(data)


def _to_reveal(
    asset: CustomAsset,
    type_fields: list[FieldDefinition],
) -> CustomAssetReveal:
    """Convert ORM model to reveal response (password fields decrypted)."""
    # Transform from ID-based storage to key-based API format, decrypting secrets
    key_values = values_id_to_key(type_fields, asset.values, decrypt_secrets=True)
    data = {
        "id": asset.id,
        "organization_id": asset.organization_id,
        "custom_asset_type_id": asset.custom_asset_type_id,
        "values": key_values,
        "metadata": asset.metadata_ if isinstance(asset.metadata_, dict) else {},
        "sync_metadata": asset.sync_metadata
        if isinstance(asset.sync_metadata, dict) and asset.sync_metadata
        else None,
        "is_enabled": asset.is_enabled,
        "created_at": asset.created_at,
        "updated_at": asset.updated_at,
        "updated_by_user_id": str(asset.updated_by_user_id) if asset.updated_by_user_id else None,
        "updated_by_user_name": asset.updated_by_user.email if asset.updated_by_user else None,
    }
    return CustomAssetReveal.model_validate(data)


@router.get("", response_model=CustomAssetListResponse)
async def list_custom_assets(
    org_id: UUID,
    type_id: UUID,
    current_user: CurrentActiveUser,
    db: DbSession,
    search: str | None = Query(None, description="Search by display field"),
    sort_by: str | None = Query(None, description="Column to sort by"),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$", description="Sort direction"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results per page"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    show_disabled: bool = Query(False, description="Include disabled custom assets"),
) -> CustomAssetListResponse:
    """
    List all custom assets for a type within an organization with pagination and search.

    Search is performed on the display_field_key field (or first text field if not set).

    Args:
        org_id: Organization UUID
        type_id: Custom asset type UUID
        current_user: Current authenticated user
        db: Database session
        search: Optional search term for display field
        sort_by: Column to sort by (use "values.fieldkey" for JSONB fields)
        sort_dir: Sort direction ("asc" or "desc")
        limit: Maximum number of results
        offset: Number of results to skip
        show_disabled: Include disabled custom assets

    Returns:
        Paginated list of custom assets (password fields filtered)
    """
    await _verify_org_access(org_id, current_user, db)
    asset_type = await _get_asset_type(type_id, db)
    type_fields = _get_field_definitions(asset_type)

    # Get the display field key for searching
    display_field_key = _get_display_field_key(asset_type)

    repo = CustomAssetRepository(db)
    # Filter by is_enabled: when show_disabled=False, only show enabled (True)
    # When show_disabled=True, show all (None filter)
    is_enabled_filter = None if show_disabled else True
    assets, total = await repo.get_paginated_by_type_and_org(
        type_id,
        org_id,
        search=search,
        search_field_key=display_field_key,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
        is_enabled=is_enabled_filter,
    )

    return CustomAssetListResponse(
        items=[_to_public(a, type_fields) for a in assets],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=CustomAssetPublic, status_code=status.HTTP_201_CREATED)
async def create_custom_asset(
    org_id: UUID,
    type_id: UUID,
    data: CustomAssetCreate,
    current_user: RequireContributor,
    db: DbSession,
) -> CustomAssetPublic:
    """
    Create a new custom asset.

    Args:
        org_id: Organization UUID
        type_id: Custom asset type UUID
        data: Custom asset creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Created custom asset (password fields filtered)
    """
    await _verify_org_access(org_id, current_user, db)
    asset_type = await _get_asset_type(type_id, db)
    type_fields = _get_field_definitions(asset_type)

    # Apply defaults and validate values
    values = apply_default_values(type_fields, data.values)
    values = initialize_checklist_values(type_fields, values)

    try:
        validate_values(type_fields, values, partial=False)
    except CustomAssetValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    # Server-side checklist merge: stamps newly completed items with the
    # acting user and time (no prior state on create).
    for field in type_fields:
        if field.type == "checklist" and field.key in values:
            values[field.key] = merge_checklist_value(
                field, None, values[field.key], current_user.user_id
            )

    # Transform to ID-based storage format (also encrypts password fields)
    storage_values = values_key_to_id(type_fields, values)

    # Create the custom asset
    repo = CustomAssetRepository(db)
    asset = CustomAsset(
        organization_id=org_id,
        custom_asset_type_id=type_id,
        values=storage_values,
        metadata_=data.metadata,
        sync_metadata=sync_metadata_to_storage(data.sync_metadata),
        is_enabled=data.is_enabled if data.is_enabled is not None else True,
    )
    asset = await repo.create(asset)

    # Refresh the expiration projection in the same session/transaction
    # (issue #136): get_db commits at request end, so reads never observe
    # the asset without its expiration rows.
    await refresh_asset_projection(ExpirationProjectionRepository(db), asset, asset_type)

    # Audit log
    audit_service = get_audit_service(db)
    await audit_service.log(
        AuditAction.CREATE,
        "custom_asset",
        asset.id,
        actor=current_user,
        organization_id=org_id,
    )

    # Get display name for logging
    display_field_key = _get_display_field_key(asset_type)
    display_name = (
        values.get(display_field_key, str(asset.id)) if display_field_key else str(asset.id)
    )

    logger.info(
        f"Custom asset created: {display_name}",
        extra={
            "org_id": str(org_id),
            "asset_type_id": str(type_id),
            "asset_id": str(asset.id),
            "user_id": str(current_user.user_id),
        },
    )

    # Index for search (async, non-blocking on failure)
    await index_entity_for_search(db, "custom_asset", asset.id, org_id)

    return _to_public(asset, type_fields)


@router.get("/{asset_id}", response_model=CustomAssetPublic)
async def get_custom_asset(
    org_id: UUID,
    type_id: UUID,
    asset_id: UUID,
    current_user: CurrentActiveUser,
    db: DbSession,
) -> CustomAssetPublic:
    """
    Get a custom asset by ID.

    Password field values are excluded from the response.

    Args:
        org_id: Organization UUID
        type_id: Custom asset type UUID
        asset_id: Custom asset UUID
        current_user: Current authenticated user
        db: Database session

    Returns:
        Custom asset details (password fields filtered)
    """
    await _verify_org_access(org_id, current_user, db)
    asset_type = await _get_asset_type(type_id, db)
    type_fields = _get_field_definitions(asset_type)

    repo = CustomAssetRepository(db)
    asset = await repo.get_by_id_type_and_org(asset_id, type_id, org_id)

    if not asset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Custom asset not found",
        )

    # Log view (with 60-second dedupe)
    audit_service = get_audit_service(db)
    await audit_service.log(
        AuditAction.VIEW,
        "custom_asset",
        asset.id,
        actor=current_user,
        organization_id=org_id,
        dedupe_seconds=60,
    )

    return _to_public(asset, type_fields)


@router.get("/{asset_id}/preview")
async def get_custom_asset_preview(
    org_id: UUID,
    type_id: UUID,
    asset_id: UUID,
    current_user: CurrentActiveUser,
    db: DbSession,
) -> dict:
    """
    Get custom asset preview for search (password fields filtered).

    Returns formatted markdown content suitable for rendering in a preview panel.

    Args:
        org_id: Organization UUID
        type_id: Custom asset type UUID
        asset_id: Custom asset UUID
        current_user: Current authenticated user
        db: Database session

    Returns:
        Preview data with formatted content (password fields excluded)

    Raises:
        HTTPException: If custom asset not found
    """
    await _verify_org_access(org_id, current_user, db)
    asset_type = await _get_asset_type(type_id, db)
    type_fields = _get_field_definitions(asset_type)

    repo = CustomAssetRepository(db)
    asset = await repo.get_by_id_type_and_org(asset_id, type_id, org_id)

    if not asset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Custom asset not found",
        )

    # Transform to key-based values (filtering secrets)
    key_values = values_id_to_key(type_fields, asset.values, filter_secrets=True)

    # Get display name
    display_field_key = _get_display_field_key(asset_type)
    display_name = (
        key_values.get(display_field_key, asset_type.name) if display_field_key else asset_type.name
    )

    # Build preview content
    content_parts = [f"# {display_name}"]
    content_parts.append(f"\n**Type:** {asset_type.name}")

    # Add visible field values
    for field in type_fields:
        if field.type == "header":
            continue
        if field.type in ("password", "totp"):
            continue
        value = key_values.get(field.key)
        if value is not None and str(value).strip():
            content_parts.append(f"\n**{field.name}:** {value}")

    return {
        "id": str(asset.id),
        "name": display_name,
        "content": "\n".join(content_parts),
        "entity_type": "custom_asset",
        "organization_id": str(org_id),
        "custom_asset_type_id": str(type_id),
    }


@router.get("/{asset_id}/reveal", response_model=CustomAssetReveal)
async def reveal_custom_asset(
    org_id: UUID,
    type_id: UUID,
    asset_id: UUID,
    current_user: CurrentActiveUser,
    db: DbSession,
) -> CustomAssetReveal:
    """
    Get a custom asset with decrypted password fields.

    This endpoint reveals sensitive password field values.

    Args:
        org_id: Organization UUID
        type_id: Custom asset type UUID
        asset_id: Custom asset UUID
        current_user: Current authenticated user
        db: Database session

    Returns:
        Custom asset details with decrypted password fields
    """
    await _verify_org_access(org_id, current_user, db)
    asset_type = await _get_asset_type(type_id, db)
    type_fields = _get_field_definitions(asset_type)

    repo = CustomAssetRepository(db)
    asset = await repo.get_by_id_type_and_org(asset_id, type_id, org_id)

    if not asset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Custom asset not found",
        )

    # Get display name for logging
    display_name = _get_display_name(asset, asset_type, type_fields)

    logger.info(
        f"Custom asset revealed: {display_name}",
        extra={
            "org_id": str(org_id),
            "asset_type_id": str(type_id),
            "asset_id": str(asset_id),
            "user_id": str(current_user.user_id),
        },
    )

    return _to_reveal(asset, type_fields)


@router.put("/{asset_id}", response_model=CustomAssetPublic)
async def update_custom_asset(
    org_id: UUID,
    type_id: UUID,
    asset_id: UUID,
    data: CustomAssetUpdate,
    current_user: RequireContributor,
    db: DbSession,
) -> CustomAssetPublic:
    """
    Update a custom asset.

    Args:
        org_id: Organization UUID
        type_id: Custom asset type UUID
        asset_id: Custom asset UUID
        data: Custom asset update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Updated custom asset (password fields filtered)
    """
    await _verify_org_access(org_id, current_user, db)
    asset_type = await _get_asset_type(type_id, db)
    type_fields = _get_field_definitions(asset_type)

    repo = CustomAssetRepository(db)
    # Lock the row when checklist fields are updated so concurrent item
    # toggles serialize and the item-level merge below loses nothing.
    lock_for_checklist = any(
        f.type == "checklist" and f.key in (data.values or {}) for f in type_fields
    )
    asset = await repo.get_by_id_type_and_org(
        asset_id, type_id, org_id, for_update=lock_for_checklist
    )

    if not asset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Custom asset not found",
        )

    # Update metadata if provided
    if data.metadata is not None:
        asset.metadata_ = data.metadata
    if data.sync_metadata is not None:
        asset.sync_metadata = sync_metadata_to_storage(data.sync_metadata)

    # Update is_enabled if provided
    if data.is_enabled is not None:
        asset.is_enabled = data.is_enabled

    # Update values if provided
    if data.values is not None:
        try:
            validate_values(type_fields, data.values, partial=True)
        except CustomAssetValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            ) from e

        # Convert existing ID-based values to key-based (decrypting secrets)
        current_key_values = values_id_to_key(type_fields, asset.values, decrypt_secrets=True)

        # Snapshot stored checklist states before overlay for item-level merge
        checklist_priors = {
            f.key: current_key_values.get(f.key)
            for f in type_fields
            if f.type == "checklist" and f.key in data.values
        }

        # Merge with incoming key-based values
        current_key_values.update(data.values)

        # Server-side checklist merge: per-item completion with acting-user
        # stamps; untouched items keep stored state (concurrency-safe with
        # the row lock above).
        for field in type_fields:
            if field.type == "checklist" and field.key in data.values:
                current_key_values[field.key] = merge_checklist_value(
                    field,
                    checklist_priors.get(field.key),
                    current_key_values[field.key],
                    current_user.user_id,
                )

        # Convert back to ID-based storage format (encrypting secrets)
        asset.values = values_key_to_id(type_fields, current_key_values)

    # Track who updated
    asset.updated_by_user_id = current_user.user_id

    asset = await repo.update(asset)

    # Same-transaction projection refresh (issue #136): updated dates,
    # cleared values, and enable toggles converge before request commit.
    await refresh_asset_projection(ExpirationProjectionRepository(db), asset, asset_type)

    # Audit log
    audit_service = get_audit_service(db)
    await audit_service.log(
        AuditAction.UPDATE,
        "custom_asset",
        asset.id,
        actor=current_user,
        organization_id=org_id,
    )

    # Get display name for logging
    display_name = _get_display_name(asset, asset_type, type_fields)

    logger.info(
        f"Custom asset updated: {display_name}",
        extra={
            "org_id": str(org_id),
            "asset_type_id": str(type_id),
            "asset_id": str(asset_id),
            "user_id": str(current_user.user_id),
        },
    )

    # Update search index (async, non-blocking on failure)
    await index_entity_for_search(db, "custom_asset", asset_id, org_id)

    return _to_public(asset, type_fields)


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_asset(
    org_id: UUID,
    type_id: UUID,
    asset_id: UUID,
    current_user: RequireContributor,
    db: DbSession,
) -> None:
    """
    Delete a custom asset.

    Args:
        org_id: Organization UUID
        type_id: Custom asset type UUID
        asset_id: Custom asset UUID
        current_user: Current authenticated user
        db: Database session
    """
    await _verify_org_access(org_id, current_user, db)
    await _get_asset_type(type_id, db)

    repo = CustomAssetRepository(db)
    asset = await repo.get_by_id_type_and_org(asset_id, type_id, org_id)

    if not asset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Custom asset not found",
        )

    # Audit log (before delete)
    audit_service = get_audit_service(db)
    await audit_service.log(
        AuditAction.DELETE,
        "custom_asset",
        asset_id,
        actor=current_user,
        organization_id=org_id,
    )

    # Get display name for logging before deletion
    asset_type = await _get_asset_type(type_id, db)
    type_fields = _get_field_definitions(asset_type)
    display_name = _get_display_name(asset, asset_type, type_fields)

    await repo.delete(asset)

    # Same-transaction projection cleanup (issue #136); the asset_id FK
    # cascade is a backstop, the explicit delete is the contract.
    await ExpirationProjectionRepository(db).delete_for_asset(asset_id)

    # Remove from search index (async, non-blocking on failure)
    await remove_entity_from_search(db, "custom_asset", asset_id)

    logger.info(
        f"Custom asset deleted: {display_name}",
        extra={
            "org_id": str(org_id),
            "asset_type_id": str(type_id),
            "asset_id": str(asset_id),
            "user_id": str(current_user.user_id),
        },
    )


@router.patch("/batch/toggle", response_model=BatchToggleResponse)
async def batch_toggle_custom_assets(
    org_id: UUID,
    type_id: UUID,
    request: BatchToggleRequest,
    current_user: RequireContributor,
    db: DbSession,
) -> BatchToggleResponse:
    """
    Batch activate/deactivate custom assets.

    Args:
        org_id: Organization UUID
        type_id: Custom asset type UUID
        request: Batch toggle request with IDs and new is_enabled value
        current_user: Current authenticated user
        db: Database session

    Returns:
        Number of custom assets updated
    """
    await _verify_org_access(org_id, current_user, db)
    await _get_asset_type(type_id, db)

    # Convert string IDs to UUIDs
    asset_ids = [UUID(id_str) for id_str in request.ids]

    # Batch update
    result = await db.execute(
        update(CustomAsset)
        .where(CustomAsset.id.in_(asset_ids))
        .where(CustomAsset.custom_asset_type_id == type_id)
        .where(CustomAsset.organization_id == org_id)
        .values(is_enabled=request.is_enabled)
    )
    await db.commit()

    logger.info(
        f"Batch toggle custom assets: {result.rowcount} assets set to is_enabled={request.is_enabled}",  # type: ignore[attr-defined]
        extra={
            "org_id": str(org_id),
            "asset_type_id": str(type_id),
            "user_id": str(current_user.user_id),
            "updated_count": result.rowcount,  # type: ignore[attr-defined]
        },
    )

    # Update search index for each affected custom asset
    # The worker will index if enabled, remove from index if disabled
    for asset_id in asset_ids:
        await index_entity_for_search(db, "custom_asset", asset_id, org_id)

    # Projection refresh (issue #136): is_enabled flips are stored on the
    # rows, so re-project each toggled asset in the request transaction.
    projection_repo = ExpirationProjectionRepository(db)
    asset_repo = CustomAssetRepository(db)
    type_repo = CustomAssetTypeRepository(db)
    for asset_id in asset_ids:
        asset = await asset_repo.get_by_id_type_and_org(asset_id, type_id, org_id)
        if asset is None:
            continue
        asset_type = await type_repo.get_by_id(type_id)
        if asset_type is None:
            continue
        await refresh_asset_projection(projection_repo, asset, asset_type)

    return BatchToggleResponse(updated_count=result.rowcount)  # type: ignore[attr-defined]
