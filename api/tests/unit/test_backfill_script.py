"""Unit tests for scripts/backfill_expiration_projections.py (issue #136).

Exercises the real CLI module with stubbed session factory and backfill
service: default/custom page-size parsing, success path, and failure
propagation. No database, no network.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

import pytest

_REPO = os.environ.get("REPO_ROOT") or str(Path(__file__).resolve().parents[3])
SCRIPT = Path(_REPO) / "api" / "scripts" / "backfill_expiration_projections.py"


def load_module(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Import the real script module with a stubbed database factory."""
    import src.core.database as database

    calls: dict[str, Any] = {}

    class StubSession:
        async def __aenter__(self) -> StubSession:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

    def factory() -> Any:
        calls["factory_used"] = True

        def make() -> StubSession:
            return StubSession()

        return make

    monkeypatch.setattr(database, "get_session_factory", factory)
    spec = importlib.util.spec_from_file_location("backfill_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.__test_calls__ = calls
    return module


def test_main_uses_default_page_size(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module(monkeypatch)
    seen: dict[str, Any] = {}

    async def fake_backfill(session: Any, page_size: int) -> dict[str, int]:
        seen["page_size"] = page_size
        return {"types": 2, "assets": 5}

    monkeypatch.setattr(module, "backfill_all_projections", fake_backfill)
    monkeypatch.setattr("sys.argv", ["backfill_expiration_projections.py"])

    import asyncio

    asyncio.run(module.main())

    assert seen["page_size"] == 500
    assert module.__test_calls__.get("factory_used") is True


def test_main_accepts_custom_page_size(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module(monkeypatch)
    seen: dict[str, Any] = {}

    async def fake_backfill(session: Any, page_size: int) -> dict[str, int]:
        seen["page_size"] = page_size
        return {"types": 1, "assets": 1}

    monkeypatch.setattr(module, "backfill_all_projections", fake_backfill)
    monkeypatch.setattr("sys.argv", ["backfill_expiration_projections.py", "--page-size", "50"])

    import asyncio

    asyncio.run(module.main())

    assert seen["page_size"] == 50


def test_main_reraise_on_backfill_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module(monkeypatch)

    async def fake_backfill(session: Any, page_size: int) -> dict[str, int]:
        raise RuntimeError("boom")

    monkeypatch.setattr(module, "backfill_all_projections", fake_backfill)
    monkeypatch.setattr("sys.argv", ["backfill_expiration_projections.py"])

    import asyncio

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(module.main())


def test_backfill_service_is_coroutine() -> None:
    """Guard: the CLI awaits backfill_all_projections, so it must stay async."""
    import asyncio

    import src.services.expiration_projection as service

    assert asyncio.iscoroutinefunction(service.backfill_all_projections)
