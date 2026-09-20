"""Tests for CLI API prerequisites and client construction.

Pins the rename contract at the CLI boundary: the tool builds a
``SkraClient`` (not the legacy name) from ``SKRA_*`` settings, and the
``run`` error paths name the ``SKRA_*`` variables first with the legacy
``BIFROST_*`` fallbacks second.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from itglue_migrate import cli
from itglue_migrate.api_client import APIError
from itglue_migrate.progress import SimpleProgressReporter
from itglue_migrate.state import MigrationState


def _plan_file(tmp_path: Path, **extra) -> Path:
    plan = {"version": 1, "export_path": str(tmp_path), **extra}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path


def _clean_api_env(monkeypatch) -> None:
    for var in ("SKRA_API_URL", "BIFROST_API_URL", "SKRA_API_TOKEN", "BIFROST_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)


def test_run_requires_api_url_naming_skra_first(tmp_path, monkeypatch):
    """Without any URL source, run exits naming SKRA_API_URL first."""
    _clean_api_env(monkeypatch)
    runner = CliRunner()

    result = runner.invoke(
        cli.app, ["run", "--all", "--plan", str(_plan_file(tmp_path))]
    )

    assert result.exit_code == 1
    assert "SKRA_API_URL" in result.output
    assert result.output.index("SKRA_API_URL") < result.output.index("BIFROST_API_URL")


def test_run_requires_token_naming_skra_first(tmp_path, monkeypatch):
    """Without a token, run exits naming SKRA_API_TOKEN first."""
    _clean_api_env(monkeypatch)
    runner = CliRunner()
    plan = _plan_file(tmp_path, api_url="http://api.example.invalid")

    result = runner.invoke(
        cli.app, ["run", "--all", "--plan", str(plan)]
    )

    assert result.exit_code == 1
    assert "SKRA_API_TOKEN" in result.output
    assert result.output.index("SKRA_API_TOKEN") < result.output.index(
        "BIFROST_API_TOKEN"
    )


def _client_factory(client: MagicMock) -> MagicMock:
    factory = MagicMock()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    factory.return_value = context
    return factory


@pytest.mark.asyncio
async def test_fetch_organizations_constructs_renamed_client():
    """The fetch helper builds SkraClient with base_url and api_key."""
    client = MagicMock()
    client.list_organizations = AsyncMock(return_value=[{"id": "uuid-1"}])
    factory = _client_factory(client)

    with patch.object(cli, "SkraClient", factory):
        orgs = await cli._fetch_existing_organizations("http://api.test", "tok")

    assert orgs == [{"id": "uuid-1"}]
    factory.assert_called_once_with(base_url="http://api.test", api_key="tok")


@pytest.mark.asyncio
async def test_fetch_organizations_api_error_exits():
    """An API failure surfaces as a CLI exit, not a traceback."""
    client = MagicMock()
    client.list_organizations = AsyncMock(side_effect=APIError(500, "down"))

    with patch.object(cli, "SkraClient", _client_factory(client)):
        with pytest.raises(typer.Exit) as exc:
            await cli._fetch_existing_organizations("http://api.test", "tok")

    assert exc.value.exit_code == 1


@pytest.mark.asyncio
async def test_execute_migration_empty_export_is_noop_success(tmp_path):
    """An empty export runs all phases with no writes and exits 0."""
    import io

    from rich.console import Console

    client = MagicMock()
    for name in (
        "list_organizations",
        "list_configuration_types",
        "list_configuration_statuses",
        "list_custom_asset_types",
        "list_locations",
        "list_documents",
        "list_passwords",
    ):
        setattr(client, name, AsyncMock(return_value=[]))
    state = MigrationState(export_path=str(tmp_path))
    reporter = SimpleProgressReporter(console=Console(file=io.StringIO()))

    with patch.object(cli, "SkraClient", _client_factory(client)):
        exit_code = await cli._execute_migration(
            {},
            "http://api.example.invalid",
            "token",
            state,
            reporter,
            True,
            None,
            tmp_path,
            None,
            True,
        )

    assert exit_code == 0


@pytest.mark.asyncio
async def test_verify_connectivity_reports_success_and_failure():
    """Connectivity mirrors the organizations listing outcome."""
    ok_client = MagicMock()
    ok_client.list_organizations = AsyncMock(return_value=[])
    bad_client = MagicMock()
    bad_client.list_organizations = AsyncMock(side_effect=APIError(401, "nope"))

    with patch.object(cli, "SkraClient", _client_factory(ok_client)):
        assert await cli._verify_api_connectivity("http://api.test", "tok") is True
    with patch.object(cli, "SkraClient", _client_factory(bad_client)):
        assert await cli._verify_api_connectivity("http://api.test", "tok") is False
