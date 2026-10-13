"""
User-specific endpoints.

Provides endpoints for the current user's data such as recently accessed entities,
favorites, and personal preferences.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from src.core.auth import CurrentActiveUser
from src.core.database import DbSession
from src.models.contracts.access_tracking import RecentItem
from src.repositories.access_tracking import AccessTrackingRepository
from src.repositories.user_favorites import (
    FavoriteLimitExceededError,
    UserFavoritesRepository,
)

router = APIRouter(prefix="/api/me", tags=["me"])
MAX_FAVORITES_PER_USER = 100


# ============================================================================
# Recent Activity
# ============================================================================


@router.get("/recent", response_model=list[RecentItem])
async def get_recent(
    current_user: CurrentActiveUser,
    db: DbSession,
    limit: int = Query(10, ge=1, le=50, description="Number of items to return"),
) -> list[RecentItem]:
    """
    Get the current user's recently accessed entities.

    Returns the most recent view per unique entity, ordered by viewed_at descending.
    """
    repo = AccessTrackingRepository(db)
    return await repo.get_recent_for_user(current_user.user_id, limit=limit)


# ============================================================================
# Favorites
# ============================================================================


class FavoriteCreate(BaseModel):
    """Request to add a favorite."""

    organization_id: UUID
    entity_type: str
    entity_id: UUID
    custom_label: str | None = None


class FavoriteResponse(BaseModel):
    """Favorite item response."""

    id: UUID
    organization_id: UUID
    entity_type: str
    entity_id: UUID
    custom_label: str | None = None
    display_order: int

    class Config:
        from_attributes = True


class FavoriteList(BaseModel):
    """List of favorites response."""

    items: list[FavoriteResponse]
    total: int


@router.get("/favorites", response_model=FavoriteList)
async def get_favorites(
    current_user: CurrentActiveUser,
    db: DbSession,
    limit: int = Query(20, ge=1, le=50, description="Maximum favorites to return"),
) -> FavoriteList:
    """
    Get the current user's favorite items.

    Returns favorites ordered by display_order then created_at, most recent first.
    """
    repo = UserFavoritesRepository(db)
    favorites = await repo.list_by_user(current_user.user_id, limit=limit)
    total = await repo.count_by_user(current_user.user_id)

    return FavoriteList(
        items=[FavoriteResponse.model_validate(f) for f in favorites],
        total=total,
    )


@router.post("/favorites", response_model=FavoriteResponse, status_code=status.HTTP_201_CREATED)
async def add_favorite(
    current_user: CurrentActiveUser,
    db: DbSession,
    data: FavoriteCreate,
) -> FavoriteResponse:
    """
    Add an item to favorites.

    Creates a new favorite bookmark for quick access. Duplicate favorites
    (same user, org, type, entity) will return the existing favorite.
    """
    repo = UserFavoritesRepository(db)

    try:
        favorite = await repo.get_or_create_with_limit(
            user_id=current_user.user_id,
            organization_id=data.organization_id,
            entity_type=data.entity_type,
            entity_id=data.entity_id,
            custom_label=data.custom_label,
            max_count=MAX_FAVORITES_PER_USER,
        )
    except FavoriteLimitExceededError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Favorite limit of {MAX_FAVORITES_PER_USER} reached",
        ) from None

    return FavoriteResponse.model_validate(favorite)


@router.delete("/favorites/{favorite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_favorite(
    current_user: CurrentActiveUser,
    db: DbSession,
    favorite_id: UUID,
) -> None:
    """
    Remove an item from favorites by ID.

    Returns 204 on success, 404 if favorite not found.
    """
    repo = UserFavoritesRepository(db)

    deleted = await repo.delete(favorite_id, current_user.user_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Favorite not found",
        )


@router.delete("/favorites", status_code=status.HTTP_204_NO_CONTENT)
async def unfavorite_entity(
    current_user: CurrentActiveUser,
    db: DbSession,
    organization_id: UUID,
    entity_type: str,
    entity_id: UUID,
) -> None:
    """
    Remove an item from favorites by entity reference.

    Alternative to DELETE /favorites/{id} when you know the entity
    but not the favorite ID.
    """
    repo = UserFavoritesRepository(db)

    deleted = await repo.delete_by_user_and_entity(
        user_id=current_user.user_id,
        organization_id=organization_id,
        entity_type=entity_type,
        entity_id=entity_id,
    )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Favorite not found",
        )


@router.get("/favorites/check", response_model=dict)
async def check_favorite(
    current_user: CurrentActiveUser,
    db: DbSession,
    organization_id: UUID,
    entity_type: str,
    entity_id: UUID,
) -> dict:
    """
    Check if an entity is favorited by the current user.

    Returns {is_favorite: true, favorite_id: "..."} or {is_favorite: false}.
    """
    repo = UserFavoritesRepository(db)

    favorite = await repo.get_by_user_and_entity(
        user_id=current_user.user_id,
        organization_id=organization_id,
        entity_type=entity_type,
        entity_id=entity_id,
    )

    if favorite:
        return {"is_favorite": True, "favorite_id": str(favorite.id)}
    return {"is_favorite": False}
