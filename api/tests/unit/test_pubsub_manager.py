"""Tests for ConnectionManager channel and lifecycle handling."""

import asyncio
from unittest.mock import MagicMock
from uuid import uuid4

from src.core.pubsub import ConnectionInfo, ConnectionManager


def _manager_with_connection() -> ConnectionManager:
    manager = ConnectionManager()
    manager._connections["c1"] = ConnectionInfo(websocket=MagicMock(), user_id=uuid4())
    return manager


async def test_subscribe_and_unsubscribe_track_channels():
    """Subscribing and unsubscribing update channel membership."""
    manager = _manager_with_connection()

    await manager.subscribe("c1", "jobs:1")
    assert "jobs:1" in manager._connections["c1"].channels

    await manager.unsubscribe("c1", "jobs:1")
    assert "jobs:1" not in manager._connections["c1"].channels


async def test_stop_pubsub_tolerates_cancelled_task():
    """Stopping cancels the task and finishes cleanly."""
    manager = ConnectionManager()

    async def _sleep():
        await asyncio.sleep(60)

    task = asyncio.create_task(_sleep())
    manager._pubsub_task = task

    await manager.stop_pubsub()

    assert task.cancelled()
    assert manager._pubsub_task is None
