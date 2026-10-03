"""Tests for embeddings service with new config loading."""

from unittest.mock import AsyncMock, patch
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
            await service._get_entity_and_org(AsyncMock(), "bogus", uuid4())

    async def test_get_entity_name_unknown_type_returns_none(self):
        """Naming an unknown entity type returns None."""
        service = EmbeddingsService(AsyncMock())

        assert await service._get_entity_name(AsyncMock(), "bogus", uuid4()) is None
