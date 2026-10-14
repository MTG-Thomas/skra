"""
User Favorites Repository

Provides database operations for UserFavorite model.
Supports CRUD operations for user bookmarks with organization scoping.
"""

from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm.user import User
from src.models.orm.user_favorite import UserFavorite


class FavoriteLimitExceededError(ValueError):
    """Raised when a user has reached the allowed number of favorites."""


class UserFavoritesRepository:
    """Repository for UserFavorite model operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_user(
        self,
        user_id: UUID,
        limit: int = 20,
    ) -> list[UserFavorite]:
        """
        Get all favorites for a user, ordered by display_order then created_at.

        Args:
            user_id: User UUID
            limit: Maximum number to return (default 20)

        Returns:
            List of UserFavorite ordered by display_order, created_at
        """
        result = await self.session.execute(
            select(UserFavorite)
            .where(UserFavorite.user_id == user_id)
            .order_by(UserFavorite.display_order.asc(), UserFavorite.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_by_user_and_org(
        self,
        user_id: UUID,
        organization_id: UUID,
    ) -> list[UserFavorite]:
        """
        Get favorites for a user within a specific organization.

        Args:
            user_id: User UUID
            organization_id: Organization UUID

        Returns:
            List of UserFavorite for that org
        """
        result = await self.session.execute(
            select(UserFavorite)
            .where(
                UserFavorite.user_id == user_id,
                UserFavorite.organization_id == organization_id,
            )
            .order_by(UserFavorite.display_order.asc(), UserFavorite.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_user_and_entity(
        self,
        user_id: UUID,
        organization_id: UUID,
        entity_type: str,
        entity_id: UUID,
    ) -> UserFavorite | None:
        """
        Check if a specific entity is favorited by user.

        Args:
            user_id: User UUID
            organization_id: Organization UUID
            entity_type: Entity type (e.g., "password", "configuration")
            entity_id: Entity UUID

        Returns:
            UserFavorite if found, None otherwise
        """
        result = await self.session.execute(
            select(UserFavorite).where(
                UserFavorite.user_id == user_id,
                UserFavorite.organization_id == organization_id,
                UserFavorite.entity_type == entity_type,
                UserFavorite.entity_id == entity_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        user_id: UUID,
        organization_id: UUID,
        entity_type: str,
        entity_id: UUID,
        custom_label: str | None = None,
        display_order: int = 0,
    ) -> UserFavorite:
        """
        Add a new favorite.

        Args:
            user_id: User UUID
            organization_id: Organization UUID
            entity_type: Entity type identifier
            entity_id: Entity UUID
            custom_label: Optional custom display label
            display_order: Sort order position

        Returns:
            Created UserFavorite
        """
        favorite = UserFavorite(
            user_id=user_id,
            organization_id=organization_id,
            entity_type=entity_type,
            entity_id=entity_id,
            custom_label=custom_label,
            display_order=display_order,
        )
        self.session.add(favorite)
        await self.session.flush()
        await self.session.refresh(favorite)
        return favorite

    async def get_or_create_with_limit(
        self,
        user_id: UUID,
        organization_id: UUID,
        entity_type: str,
        entity_id: UUID,
        max_count: int,
        custom_label: str | None = None,
    ) -> UserFavorite:
        """Return an existing favorite or create one below a serialized cap.

        Locking the owning user row makes concurrent additions for one user
        observe each other's counts before inserting. This prevents a burst of
        requests from racing past the per-user limit.
        """
        await self.session.execute(select(User.id).where(User.id == user_id).with_for_update())

        existing = await self.get_by_user_and_entity(
            user_id=user_id,
            organization_id=organization_id,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        if existing is not None:
            return existing

        count = await self.count_by_user(user_id)
        if count >= max_count:
            raise FavoriteLimitExceededError(f"favorite limit of {max_count} reached")

        return await self.create(
            user_id=user_id,
            organization_id=organization_id,
            entity_type=entity_type,
            entity_id=entity_id,
            custom_label=custom_label,
            display_order=count,
        )

    async def delete(self, favorite_id: UUID, user_id: UUID) -> bool:
        """
        Delete a favorite by ID when it belongs to the user.

        Args:
            favorite_id: Favorite UUID
            user_id: Owning user UUID

        Returns:
            True if deleted, False if not found
        """
        result = await self.session.execute(
            delete(UserFavorite).where(
                UserFavorite.id == favorite_id,
                UserFavorite.user_id == user_id,
            )
        )
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def delete_by_user_and_entity(
        self,
        user_id: UUID,
        organization_id: UUID,
        entity_type: str,
        entity_id: UUID,
    ) -> bool:
        """
        Delete a favorite by user and entity (unfavorite).

        Args:
            user_id: User UUID
            organization_id: Organization UUID
            entity_type: Entity type
            entity_id: Entity UUID

        Returns:
            True if deleted, False if not found
        """
        result = await self.session.execute(
            delete(UserFavorite).where(
                UserFavorite.user_id == user_id,
                UserFavorite.organization_id == organization_id,
                UserFavorite.entity_type == entity_type,
                UserFavorite.entity_id == entity_id,
            )
        )
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def update_order(
        self,
        favorite_id: UUID,
        display_order: int,
    ) -> bool:
        """
        Update the display order of a favorite.

        Args:
            favorite_id: Favorite UUID
            display_order: New sort order

        Returns:
            True if updated, False if not found
        """
        result = await self.session.execute(
            update(UserFavorite)
            .where(UserFavorite.id == favorite_id)
            .values(display_order=display_order)
        )
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def count_by_user(self, user_id: UUID) -> int:
        """
        Count total favorites for a user.

        Args:
            user_id: User UUID

        Returns:
            Number of favorites
        """
        result = await self.session.execute(
            select(func.count()).select_from(UserFavorite).where(UserFavorite.user_id == user_id)
        )
        return int(result.scalar_one())
