"""Tests for the discovery sync entry points.

The rename changed the organization parameter from ``bifrost_org_id`` to
``org_id``; these tests pin that the given organization flows unchanged
into device sync and topology generation for both providers.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from src.services import network_discovery as nd


@pytest.fixture
def org_id() -> UUID:
    return UUID("12345678-1234-5678-1234-567812345678")


def _patch_provider(monkeypatch, name: str, devices: list) -> MagicMock:
    provider = MagicMock()
    provider.discover_devices = AsyncMock(return_value=devices)
    monkeypatch.setattr(nd, name, MagicMock(return_value=provider))
    return provider


def _patch_sync_service(monkeypatch) -> MagicMock:
    sync = MagicMock()
    sync.sync_devices = AsyncMock(return_value={"created": 2})
    sync.generate_topology_diagram = AsyncMock(return_value="doc-1")
    monkeypatch.setattr(nd, "DiscoverySyncService", MagicMock(return_value=sync))
    return sync


async def test_ninjaone_sync_passes_org_id_through(monkeypatch, org_id):
    """NinjaOne devices sync under the requested organization."""
    devices = [MagicMock(), MagicMock()]
    _patch_provider(monkeypatch, "NinjaOneIntegration", devices)
    sync = _patch_sync_service(monkeypatch)

    await nd.run_ninjaone_sync(MagicMock(), org_id, "https://api.ninja", "id", "sec")

    sync.sync_devices.assert_called_once_with(org_id, devices)
    sync.generate_topology_diagram.assert_called_once_with(org_id)


async def test_meraki_sync_passes_org_id_through(monkeypatch, org_id):
    """Meraki devices sync under the requested organization."""
    devices = [MagicMock()]
    provider = _patch_provider(monkeypatch, "MerakiIntegration", devices)
    sync = _patch_sync_service(monkeypatch)

    await nd.run_meraki_sync(MagicMock(), org_id, "meraki-key", "meraki-org-9")

    provider.discover_devices.assert_called_once_with("meraki-org-9")
    sync.sync_devices.assert_called_once_with(org_id, devices)
    sync.generate_topology_diagram.assert_called_once_with(org_id)
