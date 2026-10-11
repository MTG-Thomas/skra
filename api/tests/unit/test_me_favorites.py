"""Unit tests for bounded current-user favorite routes."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, status

from src.repositories.user_favorites import FavoriteLimitExceededError
from src.routers.me import MAX_FAVORITES_PER_USER, FavoriteCreate, add_favorite


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_favorite_returns_conflict_at_cap():
    """The route exposes a bounded response instead of creating past the cap."""
    repo = MagicMock()
    repo.get_or_create_with_limit = AsyncMock(side_effect=FavoriteLimitExceededError)
    current_user = MagicMock(user_id=uuid4())
    request = FavoriteCreate(
        organization_id=uuid4(),
        entity_type="document",
        entity_id=uuid4(),
    )

    with (
        patch("src.routers.me.UserFavoritesRepository", return_value=repo),
        pytest.raises(HTTPException) as exc_info,
    ):
        await add_favorite(current_user, AsyncMock(), request)

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert str(MAX_FAVORITES_PER_USER) in exc_info.value.detail
    assert repo.get_or_create_with_limit.await_args.kwargs["max_count"] == 100
