"""Success-path tests for the remaining EntityImporter methods.

Each test drives one import method through its create branch, pinning the
renamed ``skra_id`` bookkeeping: the API-returned UUID must land in the ID
map under the right entity type.
"""

import io
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from rich.console import Console

from itglue_migrate.importers import EntityImporter
from itglue_migrate.progress import Phase, SimpleProgressReporter
from itglue_migrate.state import MigrationState


@pytest.fixture
def importer():
    """Importer with organization "1" already mapped to a Skra UUID."""
    client = AsyncMock()
    state = MigrationState(export_path="/tmp/exports")
    state.id_mapper.add("organization", "1", "org-uuid")
    reporter = SimpleProgressReporter(console=Console(file=io.StringIO()))
    return EntityImporter(client, state, reporter), client, state


@pytest.mark.asyncio
async def test_get_org_uuid_resolves_mapped_org(importer):
    """The org lookup returns the mapped UUID and None when unknown."""
    imp, _client, _state = importer

    assert imp._get_org_uuid("1") == "org-uuid"
    assert imp._get_org_uuid("999") is None


@pytest.mark.asyncio
async def test_import_locations_registers_created_id(importer):
    """A created location is recorded in the ID map and counted."""
    imp, client, state = importer
    client.create_location = AsyncMock(return_value={"id": "loc-uuid"})

    created = await imp.import_locations(
        [{"id": "10", "name": "HQ", "organization_id": "1", "city": "Austin"}]
    )

    assert created == 1
    assert state.id_mapper.get("location", "10") == "loc-uuid"
    assert state.is_completed(Phase.LOCATIONS, "10")


@pytest.mark.asyncio
async def test_import_configuration_types_registers_created_id(importer):
    """A new configuration type populates the cache and the ID map."""
    imp, client, state = importer
    client.list_configuration_types = AsyncMock(return_value=[])
    client.create_configuration_type = AsyncMock(return_value={"id": "ct-uuid"})

    created = await imp.import_configuration_types(
        [{"configuration_type": "Server"}, {"configuration_type": "Server"}]
    )

    assert created == 1
    assert imp._config_type_cache["server"] == "ct-uuid"
    assert state.id_mapper.get("configuration_type", "type:Server") == "ct-uuid"


@pytest.mark.asyncio
async def test_import_configurations_registers_created_id(importer):
    """A created configuration resolves org/type/status and is counted."""
    imp, client, state = importer
    imp._config_type_cache = {"server": "ct-uuid"}
    imp._config_status_cache = {"active": "st-uuid"}
    client.create_configuration = AsyncMock(return_value={"id": "cfg-uuid"})

    created = await imp.import_configurations(
        [
            {
                "id": "20",
                "name": "web-01",
                "organization_id": "1",
                "configuration_type": "Server",
                "configuration_status": "Active",
                "archived": "No",
            }
        ]
    )

    assert created == 1
    _, kwargs = client.create_configuration.call_args
    assert kwargs["org_id"] == "org-uuid"
    assert kwargs["configuration_type_id"] == "ct-uuid"
    assert kwargs["is_enabled"] is True
    assert state.id_mapper.get("configuration", "20") == "cfg-uuid"


@pytest.mark.asyncio
async def test_import_custom_asset_types_registers_created_id(importer):
    """A created custom asset type caches by slug and records the ID."""
    imp, client, state = importer
    client.list_custom_asset_types = AsyncMock(return_value=[])
    client.create_custom_asset_type = AsyncMock(return_value={"id": "cat-uuid"})

    created = await imp.import_custom_asset_types(
        {
            "ssl-certificates": {
                "display_name": "SSL Certificates",
                "fields": [
                    {"name": "Domain", "field_type": "text", "required": True},
                ],
            }
        }
    )

    assert created == 1
    assert imp._custom_asset_type_cache["ssl-certificates"] == "cat-uuid"
    assert (
        state.id_mapper.get("custom_asset_type", "type:ssl-certificates")
        == "cat-uuid"
    )


@pytest.mark.asyncio
async def test_import_custom_assets_registers_created_id(importer):
    """A created custom asset converts fields to keys and is counted."""
    imp, client, state = importer
    imp._custom_asset_type_cache = {"ssl-certificates": "cat-uuid"}
    client.create_custom_asset = AsyncMock(return_value={"id": "ca-uuid"})

    created = await imp.import_custom_assets(
        {
            "ssl-certificates": [
                {
                    "id": "30",
                    "organization_id": "1",
                    "fields": {"Domain": "example.com"},
                }
            ]
        }
    )

    assert created == 1
    _, kwargs = client.create_custom_asset.call_args
    assert kwargs["values"] == {"domain": "example.com"}
    assert state.id_mapper.get("custom_asset", "30") == "ca-uuid"


@pytest.mark.asyncio
async def test_import_documents_converts_html_and_registers_id(importer, tmp_path):
    """A document with export HTML imports with converted content."""
    imp, client, state = importer
    doc_dir = tmp_path / "documents" / "DOC-1-42 Network Plan"
    doc_dir.mkdir(parents=True)
    (doc_dir / "Network Plan.html").write_text(
        "<html><body><p>Hello world</p></body></html>", encoding="utf-8"
    )
    client.create_document = AsyncMock(return_value={"id": "doc-uuid"})

    created = await imp.import_documents(
        [{"id": "42", "name": "Network Plan", "organization_id": "1"}],
        Path(tmp_path),
    )

    assert created == 1
    _, kwargs = client.create_document.call_args
    assert "Hello world" in kwargs["content"]
    assert state.id_mapper.get("document", "42") == "doc-uuid"


@pytest.mark.asyncio
async def test_import_passwords_registers_created_id(importer):
    """A created password maps the OTP secret and records the ID."""
    imp, client, state = importer
    client.create_password = AsyncMock(return_value={"id": "pw-uuid"})

    created = await imp.import_passwords(
        [
            {
                "id": "50",
                "name": "Admin",
                "organization_id": "1",
                "password": "s3cret",
                "username": "root",
                "otp_secret": "JBSW Y3DP",
            }
        ]
    )

    assert created == 1
    _, kwargs = client.create_password.call_args
    assert kwargs["totp_secret"] == "JBSW Y3DP"
    assert state.id_mapper.get("password", "50") == "pw-uuid"
