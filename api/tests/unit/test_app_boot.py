"""Tests for application boot identity and lifespan wiring.

Pins the renamed application identity (title, root payload, lifespan
messaging runs through startup/shutdown) without opening real database
or pub/sub connections.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.filterwarnings(
    "ignore::DeprecationWarning",
)


async def test_app_carries_renamed_title():
    """The FastAPI application identifies as Skra."""
    from src.main import app

    assert app.title == "Skra API"


async def test_root_endpoint_reports_renamed_name():
    """GET / reports the Skra product name."""
    from src.main import app

    (route,) = [r for r in app.routes if getattr(r, "path", None) == "/"]
    body = await route.endpoint()

    assert body["name"] == "Skra API"


async def test_lifespan_starts_and_stops_dependencies(monkeypatch):
    """Startup initializes DB and pub/sub; shutdown closes them."""
    from src import main

    init_db = AsyncMock()
    close_db = AsyncMock()
    manager = MagicMock()
    manager.start_pubsub = AsyncMock()
    manager.stop_pubsub = AsyncMock()
    monkeypatch.setattr(main, "init_db", init_db)
    monkeypatch.setattr(main, "close_db", close_db)
    monkeypatch.setattr("src.core.pubsub.get_connection_manager", lambda: manager)

    async with main.lifespan(main.app):
        init_db.assert_called_once()
        manager.start_pubsub.assert_called_once()

    manager.stop_pubsub.assert_called_once()
    close_db.assert_called_once()
