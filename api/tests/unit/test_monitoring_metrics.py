"""Tests for the Prometheus metrics output contract.

The rename changed every metric name from ``bifrost_docs_*`` to ``skra_*``;
these tests pin the renamed output (and the absence of the old names) with
and without a working database.
"""

from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.exc import SQLAlchemyError

from src.routers import monitoring
from src.routers.monitoring import prometheus_metrics


def _db_failures() -> AsyncMock:
    db = AsyncMock()
    db.execute.side_effect = SQLAlchemyError("connection down")
    return db


def _db_healthy(user_count: int = 3) -> AsyncMock:
    ok = MagicMock()
    count = MagicMock()
    count.scalar.return_value = user_count
    db = AsyncMock()
    db.execute.side_effect = [ok, count]
    return db


async def test_metrics_use_renamed_series():
    """All series carry the skra_ prefix; no legacy names remain."""
    body = await prometheus_metrics(_db_healthy())

    for series in (
        "skra_info",
        "skra_uptime_seconds",
        "skra_database_connected",
        "skra_users_total",
    ):
        assert series in body
    assert "bifrost_docs_" not in body


async def test_metrics_report_healthy_database():
    """A working database reports connected=1 and the real user count."""
    body = await prometheus_metrics(_db_healthy(user_count=7))

    assert "skra_database_connected 1" in body
    assert "skra_users_total 7" in body


async def test_metrics_include_request_count_when_nonzero(monkeypatch):
    """The request counter series appears once traffic has been served."""
    monkeypatch.setattr(monitoring, "_request_count", 42)

    body = await prometheus_metrics(_db_healthy())

    assert "skra_requests_total 42" in body


async def test_metrics_degrade_gracefully_without_database():
    """A down database reports connected=0 and zero users, still 200-shape."""
    body = await prometheus_metrics(_db_failures())

    assert "skra_database_connected 0" in body
    assert "skra_users_total 0" in body
    assert "skra_info" in body
