"""Unit tests for bounded user-favorite repository operations."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.repositories.user_favorites import (
    FavoriteLimitExceededError,
    UserFavoritesRepository,
)


@pytest.mark.unit
@pytest.mark.asyncio
class TestUserFavoritesRepository:
    """Tests for efficient counting and serialized favorite creation."""

    async def test_count_by_user_uses_database_aggregate(self):
        """Counting delegates to COUNT(*) instead of materializing ORM rows."""
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one.return_value = 37
        session.execute.return_value = result

        count = await UserFavoritesRepository(session).count_by_user(uuid4())

        assert count == 37
        statement = session.execute.await_args.args[0]
        assert "count(" in str(statement).lower()

    async def test_create_locks_user_and_rejects_at_limit(self):
        """The cap is checked only after locking the owning user row."""
        session = AsyncMock()
        repo = UserFavoritesRepository(session)
        repo.get_by_user_and_entity = AsyncMock(return_value=None)
        repo.count_by_user = AsyncMock(return_value=100)
        repo.create = AsyncMock()

        with pytest.raises(FavoriteLimitExceededError):
            await repo.get_or_create_with_limit(
                user_id=uuid4(),
                organization_id=uuid4(),
                entity_type="document",
                entity_id=uuid4(),
                max_count=100,
            )

        lock_statement = session.execute.await_args_list[0].args[0]
        assert "FOR UPDATE" in str(lock_statement)
        repo.create.assert_not_awaited()

    async def test_duplicate_is_returned_without_consuming_capacity(self):
        """Idempotent duplicate requests still succeed when the user is full."""
        session = AsyncMock()
        existing = MagicMock()
        repo = UserFavoritesRepository(session)
        repo.get_by_user_and_entity = AsyncMock(return_value=existing)
        repo.count_by_user = AsyncMock()

        result = await repo.get_or_create_with_limit(
            user_id=uuid4(),
            organization_id=uuid4(),
            entity_type="document",
            entity_id=uuid4(),
            max_count=100,
        )

        assert result is existing
        repo.count_by_user.assert_not_awaited()

    async def test_create_uses_current_count_as_display_order(self):
        """A below-cap request creates one favorite at the next order."""
        session = AsyncMock()
        created = MagicMock()
        repo = UserFavoritesRepository(session)
        repo.get_by_user_and_entity = AsyncMock(return_value=None)
        repo.count_by_user = AsyncMock(return_value=12)
        repo.create = AsyncMock(return_value=created)

        result = await repo.get_or_create_with_limit(
            user_id=uuid4(),
            organization_id=uuid4(),
            entity_type="document",
            entity_id=uuid4(),
            max_count=100,
        )

        assert result is created
        assert repo.create.await_args.kwargs["display_order"] == 12

    async def test_delete_is_scoped_to_owner(self):
        """Deletion cannot remove another user's favorite by guessed ID."""
        session = AsyncMock()
        result = MagicMock(rowcount=1)
        session.execute.return_value = result

        deleted = await UserFavoritesRepository(session).delete(uuid4(), uuid4())

        assert deleted is True
        statement = str(session.execute.await_args.args[0])
        assert "user_favorites.id" in statement
        assert "user_favorites.user_id" in statement
