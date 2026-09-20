"""Tests for EntityImporter.import_organizations.

Covers the matched/create dispatch added by the Skra rename, including the
``skra_id`` plan key and the legacy ``bifrost_id`` fallback for pre-rename
plan files.
"""

import io
from unittest.mock import AsyncMock

import pytest
from rich.console import Console

from itglue_migrate.api_client import APIError
from itglue_migrate.importers import EntityImporter
from itglue_migrate.progress import Phase, SimpleProgressReporter
from itglue_migrate.state import MigrationState


@pytest.fixture
def importer():
    """Importer wired to a mock client, real state, and a quiet reporter."""
    client = AsyncMock()
    state = MigrationState(export_path="/tmp/exports")
    reporter = SimpleProgressReporter(console=Console(file=io.StringIO()))
    return EntityImporter(client, state, reporter), client, state


def _mapping(itglue_id, status, **extra):
    return {
        "itglue_id": itglue_id,
        "itglue_name": "Acme",
        "status": status,
        **extra,
    }


@pytest.mark.asyncio
async def test_matched_org_registers_skra_id_without_api_call(importer):
    """A matched org is recorded by IT Glue ID and by name; returns 0."""
    imp, client, state = importer
    orgs = [{"id": "123", "name": "Acme"}]
    plan = {"mappings": [_mapping("123", "matched", skra_id="uuid-abc")]}

    created = await imp.import_organizations(orgs, plan)

    assert created == 0
    client.create_organization.assert_not_called()
    assert state.id_mapper.get("organization", "123") == "uuid-abc"
    assert state.id_mapper.get("organization", "Acme") == "uuid-abc"
    assert state.is_completed(Phase.ORGANIZATIONS, "123")


@pytest.mark.asyncio
async def test_matched_org_accepts_legacy_bifrost_id(importer):
    """Pre-rename plan files carrying bifrost_id still resolve."""
    imp, client, state = importer
    orgs = [{"id": "123", "name": "Acme"}]
    plan = {"mappings": [_mapping("123", "matched", bifrost_id="uuid-old")]}

    created = await imp.import_organizations(orgs, plan)

    assert created == 0
    assert state.id_mapper.get("organization", "123") == "uuid-old"
    assert state.is_completed(Phase.ORGANIZATIONS, "123")


@pytest.mark.asyncio
async def test_matched_org_without_id_is_recorded_failed(importer):
    """A matched org with neither key fails instead of mapping None."""
    imp, client, state = importer
    orgs = [{"id": "123", "name": "Acme"}]
    plan = {"mappings": [_mapping("123", "matched")]}

    created = await imp.import_organizations(orgs, plan)

    assert created == 0
    assert state.id_mapper.get("organization", "123") is None
    assert state.is_failed(Phase.ORGANIZATIONS, "123")
    assert "skra_id" in (state.get_failure_error(Phase.ORGANIZATIONS, "123") or "")


@pytest.mark.asyncio
async def test_create_org_calls_api_and_counts(importer):
    """A create-mapping org is created with status-derived flags."""
    imp, client, state = importer
    client.create_organization = AsyncMock(return_value={"id": "uuid-new"})
    orgs = [
        {
            "id": "123",
            "name": "Acme",
            "organization_status": "Active",
            "description": "Main client",
        }
    ]
    plan = {"mappings": [_mapping("123", "create")]}

    created = await imp.import_organizations(orgs, plan)

    assert created == 1
    _, kwargs = client.create_organization.call_args
    assert kwargs["name"] == "Acme"
    assert kwargs["is_enabled"] is True
    assert kwargs["metadata"]["itglue_id"] == "123"
    assert state.id_mapper.get("organization", "Acme") == "uuid-new"


@pytest.mark.asyncio
async def test_create_archived_org_is_disabled(importer):
    """Archived IT Glue orgs import as disabled organizations."""
    imp, client, state = importer
    client.create_organization = AsyncMock(return_value={"id": "uuid-new"})
    orgs = [{"id": "9", "name": "Old Co", "organization_status": "Archived"}]
    plan = {"mappings": [_mapping("9", "create")]}

    await imp.import_organizations(orgs, plan)

    _, kwargs = client.create_organization.call_args
    assert kwargs["is_enabled"] is False


@pytest.mark.asyncio
async def test_org_missing_id_is_skipped(importer):
    """Rows without an IT Glue ID never reach the API."""
    imp, client, _state = importer

    created = await imp.import_organizations([{"name": "No Id"}], {"mappings": []})

    assert created == 0
    client.create_organization.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_names_create_once(importer):
    """The second org with a repeated name is skipped with a warning."""
    imp, client, state = importer
    client.create_organization = AsyncMock(
        side_effect=[{"id": "uuid-1"}, {"id": "uuid-2"}]
    )
    orgs = [
        {"id": "1", "name": "Acme"},
        {"id": "2", "name": "ACME"},
    ]
    plan = {"mappings": [_mapping("1", "create"), _mapping("2", "create")]}

    created = await imp.import_organizations(orgs, plan)

    assert created == 1
    assert client.create_organization.call_count == 1
    assert any("duplicate" in w.lower() for w in state.warnings)


@pytest.mark.asyncio
async def test_already_completed_org_is_skipped_on_resume(importer):
    """Resume skips previously completed orgs without calling the API."""
    imp, client, state = importer
    state.mark_completed(Phase.ORGANIZATIONS, "123")
    orgs = [{"id": "123", "name": "Acme"}]
    plan = {"mappings": [_mapping("123", "create")]}

    created = await imp.import_organizations(orgs, plan)

    assert created == 0
    client.create_organization.assert_not_called()


@pytest.mark.asyncio
async def test_create_org_forwards_quick_notes_metadata(importer):
    """Optional CSV fields land in the organization metadata payload."""
    imp, client, _state = importer
    client.create_organization = AsyncMock(return_value={"id": "uuid-new"})
    orgs = [{"id": "123", "name": "Acme", "quick_notes": "VIP"}]
    plan = {"mappings": [_mapping("123", "create")]}

    await imp.import_organizations(orgs, plan)

    _, kwargs = client.create_organization.call_args
    assert kwargs["metadata"]["quick_notes"] == "VIP"


@pytest.mark.asyncio
async def test_create_org_missing_response_id_is_recorded_failed(importer):
    """An API response without an id fails the org instead of mapping None."""
    imp, client, state = importer
    client.create_organization = AsyncMock(return_value={})
    orgs = [{"id": "123", "name": "Acme"}]
    plan = {"mappings": [_mapping("123", "create")]}

    created = await imp.import_organizations(orgs, plan)

    assert created == 0
    assert state.is_failed(Phase.ORGANIZATIONS, "123")


@pytest.mark.asyncio
async def test_api_error_marks_org_failed(importer):
    """An API failure records the org as failed and creates nothing."""
    imp, client, state = importer
    client.create_organization = AsyncMock(side_effect=APIError(500, "boom"))
    orgs = [{"id": "123", "name": "Acme"}]
    plan = {"mappings": [_mapping("123", "create")]}

    created = await imp.import_organizations(orgs, plan)

    assert created == 0
    assert state.is_failed(Phase.ORGANIZATIONS, "123")
