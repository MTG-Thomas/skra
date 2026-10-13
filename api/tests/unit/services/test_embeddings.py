"""Tests for embeddings service with new config loading."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.services.embeddings import EmbeddingsService
from src.services.llm.factory import EmbeddingsConfig


@pytest.mark.unit
@pytest.mark.asyncio
class TestEmbeddingsService:
    """Tests for EmbeddingsService."""

    async def test_check_openai_available_false_when_not_configured(self):
        """Test returns False when not configured."""
        mock_session = AsyncMock()

        with patch("src.services.embeddings.get_embeddings_config") as mock_config:
            mock_config.return_value = None

            service = EmbeddingsService(mock_session)
            result = await service.check_openai_available()

            assert result is False

    async def test_check_openai_available_true_when_configured(self):
        """Test returns True when configured."""
        mock_session = AsyncMock()

        with patch("src.services.embeddings.get_embeddings_config") as mock_config:
            mock_config.return_value = EmbeddingsConfig(
                api_key="test-key",
                model="text-embedding-3-small",
            )

            service = EmbeddingsService(mock_session)
            result = await service.check_openai_available()

            assert result is True


@pytest.mark.unit
@pytest.mark.asyncio
class TestUnknownEntityType:
    """Unknown entity types fail closed without touching the database."""

    async def test_get_entity_and_org_unknown_type_raises(self):
        """Fetching an unknown entity type raises ValueError."""
        service = EmbeddingsService(AsyncMock())

        with pytest.raises(ValueError, match="Unknown entity type"):
            await service._get_entity_and_org(
                AsyncMock(),
                "bogus",  # pyright: ignore[reportArgumentType]
                uuid4(),
            )

    async def test_get_entity_search_metadata_unknown_type_returns_empty(self):
        """Metadata lookup ignores unknown entity types without querying."""
        db = AsyncMock()
        service = EmbeddingsService(db)
        index = MagicMock(entity_type="bogus", entity_id=uuid4())

        assert await service._get_entity_search_metadata(db, [index]) == {}
        db.execute.assert_not_awaited()
