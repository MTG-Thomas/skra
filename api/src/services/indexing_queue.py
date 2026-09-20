"""
Indexing Queue Service.

Provides async functions to enqueue indexing jobs for background processing.
Jobs are processed by the arq worker (src/worker.py).

This allows indexing to happen asynchronously without blocking API responses.
"""

import logging

from arq import create_pool
from arq.connections import RedisSettings

from src.config import get_settings

logger = logging.getLogger(__name__)


async def enqueue_index_entity(
    entity_type: str,
    entity_id: str,
    org_id: str,
) -> None:
    """
    Enqueue an entity for indexing.

    Called from routers after create/update operations.
    The job will be processed asynchronously by the worker.

    Args:
        entity_type: Type of entity (password, document, configuration, etc.)
        entity_id: UUID of the entity as string
        org_id: UUID of the organization as string
    """
    settings = get_settings()
    try:
        redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await redis.enqueue_job(
            "index_entity_task",
            entity_type,
            entity_id,
            org_id,
        )
        # Log a static event only: entity IDs trace to sensitive records and
        # exception text can carry credentials, so neither is logged here.
        logger.debug(
            "Enqueued index job",
            extra={
                "entity_type": entity_type,
            },
        )
    except Exception:
        # Log but don't fail the request - indexing is best-effort.
        # No exception text or traceback: either can leak secrets.
        logger.warning(
            "Failed to enqueue index job",
            extra={
                "entity_type": entity_type,
            },
        )


async def enqueue_remove_entity(
    entity_type: str,
    entity_id: str,
) -> None:
    """
    Enqueue entity removal from index.

    Called from routers after delete operations.
    The job will be processed asynchronously by the worker.

    Args:
        entity_type: Type of entity (password, document, configuration, etc.)
        entity_id: UUID of the entity as string
    """
    settings = get_settings()
    try:
        redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await redis.enqueue_job(
            "remove_entity_task",
            entity_type,
            entity_id,
        )
        # Static event only (see note above).
        logger.debug(
            "Enqueued remove job",
            extra={
                "entity_type": entity_type,
            },
        )
    except Exception:
        # Log but don't fail the request - index removal is best-effort.
        # No exception text or traceback: either can leak secrets.
        logger.warning(
            "Failed to enqueue remove job",
            extra={
                "entity_type": entity_type,
            },
        )
