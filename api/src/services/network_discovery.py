"""
External platform integration for network discovery.

Syncs device data from NinjaOne and Meraki into Skra configurations,
enabling auto-generated topology diagrams from live data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm.configuration import Configuration
from src.repositories.configuration import ConfigurationRepository
from src.services.mermaid_diagrams import MermaidDiagramService

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredDevice:
    """Device discovered from external platform."""

    external_id: str
    name: str
    device_type: str  # switch, router, firewall, server, workstation, ap
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    ip_address: str | None = None
    mac_address: str | None = None
    os_name: str | None = None
    os_version: str | None = None
    site_name: str | None = None  # For matching to our locations
    status: str = "up"  # up, down, offline

    # Network topology data
    parent_device_id: str | None = None  # Connected to what (e.g., uplink switch)
    connected_ports: list[dict] | None = (
        None  # [{"local_port": "eth0", "remote_device": "id", "remote_port": "eth1"}]
    )


class NinjaOneIntegration:
    """Integration with NinjaOne RMM for device discovery."""

    def __init__(self, api_url: str, client_id: str, client_secret: str) -> None:
        self.api_url = api_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self._access_token: str | None = None

    async def _get_access_token(self) -> str:
        """Get OAuth access token."""
        if self._access_token:
            return self._access_token

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.api_url}/auth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": "monitoring",
                },
            )
            response.raise_for_status()
            data = response.json()
            self._access_token = data["access_token"]
            return str(self._access_token)

    async def discover_devices(self, organization_id: str | None = None) -> list[DiscoveredDevice]:
        """Discover all devices from NinjaOne.

        Args:
            organization_id: Optional NinjaOne org ID to filter

        Returns:
            List of discovered devices
        """
        token = await self._get_access_token()

        devices: list[DiscoveredDevice] = []

        async with httpx.AsyncClient() as client:
            # Get all devices
            response = await client.get(
                f"{self.api_url}/devices",
                headers={"Authorization": f"Bearer {token}"},
                params={"pageSize": 1000} if organization_id else None,
            )
            response.raise_for_status()
            data = response.json()

            for device_data in data.get("results", []):
                device = self._parse_device(device_data)
                if device:
                    devices.append(device)

        # Fetch network interfaces for topology data
        await self._enrich_with_interfaces(devices, token)

        logger.info(f"Discovered {len(devices)} devices from NinjaOne")
        return devices

    def _parse_device(self, data: dict[str, Any]) -> DiscoveredDevice | None:
        """Parse NinjaOne device data."""
        # Map NinjaOne device classes to our types
        device_class = data.get("deviceClass", "").lower()
        device_type = "default"

        if device_class in ["workstation", "laptop", "desktop"]:
            device_type = "workstation"
        elif device_class in ["server"]:
            device_type = "server"
        elif "switch" in device_class:
            device_type = "switch"
        elif "router" in device_class or "firewall" in device_class:
            device_type = "firewall" if "firewall" in device_class else "router"
        elif "access point" in device_class or "ap" in device_class:
            device_type = "ap"

        # Get IP from network interfaces
        ip_address = None
        interfaces = data.get("networkInterfaces", [])
        for iface in interfaces:
            if iface.get("ipAddress") and not iface.get("ipAddress").startswith("127."):
                ip_address = iface["ipAddress"]
                break

        return DiscoveredDevice(
            external_id=str(data.get("id", "")),
            name=data.get("systemName", data.get("displayName", "Unknown")),
            device_type=device_type,
            manufacturer=data.get("manufacturer", ""),
            model=data.get("model", ""),
            serial_number=data.get("serialNumber"),
            ip_address=ip_address,
            mac_address=interfaces[0].get("macAddress") if interfaces else None,
            os_name=data.get("os", {}).get("name"),
            os_version=data.get("os", {}).get("version"),
            site_name=data.get("siteName"),
            status="up" if data.get("online", False) else "offline",
        )

    async def _enrich_with_interfaces(
        self,
        devices: list[DiscoveredDevice],
        token: str,
    ) -> None:
        """Fetch detailed interface data for topology."""
        # This would fetch switch port mappings, etc.
        # Simplified for now - real implementation would parse SNMP data
        pass


class MerakiIntegration:
    """Integration with Cisco Meraki Dashboard API."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.base_url = "https://api.meraki.com/api/v1"

    async def discover_devices(self, organization_id: str) -> list[DiscoveredDevice]:
        """Discover all devices from Meraki organization.

        Args:
            organization_id: Meraki organization ID

        Returns:
            List of discovered devices with topology data
        """
        devices: list[DiscoveredDevice] = []

        async with httpx.AsyncClient() as client:
            headers = {
                "X-Cisco-Meraki-API-Key": self.api_key,
                "Content-Type": "application/json",
            }

            # Get all networks in org
            networks_response = await client.get(
                f"{self.base_url}/organizations/{organization_id}/networks",
                headers=headers,
            )
            networks_response.raise_for_status()
            networks = networks_response.json()

            # Get devices from each network
            for network in networks:
                network_id = network["id"]
                network_name = network["name"]

                # Get devices in network
                devices_response = await client.get(
                    f"{self.base_url}/networks/{network_id}/devices",
                    headers=headers,
                )
                if devices_response.status_code == 200:
                    network_devices = devices_response.json()

                    for device_data in network_devices:
                        device = self._parse_meraki_device(device_data, network_name)
                        if device:
                            devices.append(device)

                # Get topology data
                await self._enrich_topology(client, headers, network_id, devices)

        logger.info(f"Discovered {len(devices)} devices from Meraki")
        return devices

    def _parse_meraki_device(
        self,
        data: dict[str, Any],
        network_name: str,
    ) -> DiscoveredDevice | None:
        """Parse Meraki device data."""
        device_model = data.get("model", "").lower()

        # Map Meraki model prefixes to types
        device_type = "ap"  # Default
        if device_model.startswith("ms"):
            device_type = "switch"
        elif device_model.startswith("mx"):
            device_type = "firewall"
        elif device_model.startswith("mr"):
            device_type = "ap"
        elif device_model.startswith("mv"):
            device_type = "camera"  # We may not track these
            return None  # Skip cameras for now

        # Determine status
        status = data.get("status", "offline")
        status_map = {
            "online": "up",
            "alerting": "warning",
            "offline": "down",
            "dormant": "offline",
        }

        return DiscoveredDevice(
            external_id=data.get("serial", ""),  # Meraki uses serial as ID
            name=data.get("name", data.get("serial", "Unknown")),
            device_type=device_type,
            manufacturer="Cisco Meraki",
            model=data.get("model", "").upper(),
            serial_number=data.get("serial"),
            ip_address=data.get("lanIp") or data.get("wan1Ip"),
            mac_address=data.get("mac"),
            site_name=network_name,
            status=status_map.get(status, "down"),
        )

    async def _enrich_topology(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        network_id: str,
        devices: list[DiscoveredDevice],
    ) -> None:
        """Fetch topology data for switches."""
        # Get switch ports for topology
        topology_response = await client.get(
            f"{self.base_url}/networks/{network_id}/topology/linkLayer",
            headers=headers,
        )

        if topology_response.status_code == 200:
            topology = topology_response.json()

            # Parse topology links
            for link in topology.get("links", []):
                source_mac = link.get("source", {}).get("mac")
                target_mac = link.get("target", {}).get("mac")

                # Find devices by MAC
                source_device = None
                target_device = None

                for device in devices:
                    if device.mac_address and device.mac_address.lower() == source_mac.lower():
                        source_device = device
                    if device.mac_address and device.mac_address.lower() == target_mac.lower():
                        target_device = device

                if source_device and target_device:
                    # Record connection
                    if not source_device.connected_ports:
                        source_device.connected_ports = []

                    source_device.connected_ports.append(
                        {
                            "local_port": link.get("source", {}).get("portId", "unknown"),
                            "remote_device": target_device.external_id,
                            "remote_port": link.get("target", {}).get("portId", "unknown"),
                        }
                    )


class DiscoverySyncService:
    """Sync discovered devices to Skra configurations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.config_repo = ConfigurationRepository(db)

    async def sync_devices(
        self,
        org_id: UUID,
        devices: list[DiscoveredDevice],
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Sync discovered devices to configurations.

        Args:
            org_id: Skra organization ID
            devices: Discovered devices to sync
            dry_run: If True, don't actually create/update

        Returns:
            Stats: {created: int, updated: int, unchanged: int, errors: list}
        """
        stats = {
            "created": 0,
            "updated": 0,
            "unchanged": 0,
            "errors": [],
        }

        # Build external_id -> UUID mapping for existing configs
        existing_query = select(Configuration).where(
            Configuration.organization_id == org_id,
            Configuration.metadata_["external_id"].astext.isnot(None),
        )
        result = await self.db.execute(existing_query)
        existing = result.scalars().all()

        existing_map = {
            cfg.metadata_.get("external_id"): cfg
            for cfg in existing
            if cfg.metadata_ and cfg.metadata_.get("external_id")
        }

        for device in devices:
            try:
                if device.external_id in existing_map:
                    # Update existing
                    existing_cfg = existing_map[device.external_id]
                    updated = await self._update_config(existing_cfg, device)

                    if updated:
                        stats["updated"] += 1
                    else:
                        stats["unchanged"] += 1
                else:
                    # Create new
                    if not dry_run:
                        await self._create_config(org_id, device)
                    stats["created"] += 1

            except Exception as e:
                logger.error(f"Failed to sync device {device.name}: {e}")
                stats["errors"].append(f"{device.name}: {str(e)}")

        return stats

    async def _create_config(
        self,
        org_id: UUID,
        device: DiscoveredDevice,
    ) -> Configuration:
        """Create new configuration from discovered device."""
        config = Configuration(
            id=uuid4(),
            organization_id=org_id,
            name=device.name,
            configuration_type=device.device_type,
            manufacturer=device.manufacturer,
            model=device.model,
            serial_number=device.serial_number,
            ip_address=device.ip_address,
            mac_address=device.mac_address,
            operating_system=device.os_name,
            os_version=device.os_version,
            status=device.status,
            metadata_={
                "external_id": device.external_id,
                "source": "auto-discovery",
                "discovery_time": datetime.now().isoformat(),
                "site_name": device.site_name,
            },
            is_enabled=True,
        )

        return await self.config_repo.create(config)

    async def _update_config(
        self,
        config: Configuration,
        device: DiscoveredDevice,
    ) -> bool:
        """Update existing configuration. Returns True if changed."""
        changed = False

        # Update fields that may have changed
        if config.ip_address != device.ip_address:
            config.ip_address = device.ip_address
            changed = True

        config_status = config.metadata_.get("status")
        if config_status != device.status:
            config.metadata_["status"] = device.status
            changed = True

        os_version = config.metadata_.get("os_version")
        if os_version != device.os_version:
            config.metadata_["os_version"] = device.os_version
            changed = True

        if changed:
            await self.config_repo.update(config)

        return changed

    async def generate_topology_diagram(
        self,
        org_id: UUID,
        refresh: bool = False,
    ) -> str:
        """Generate or refresh network topology diagram.

        Args:
            org_id: Organization to diagram
            refresh: If True, regenerate even if exists

        Returns:
            Document ID of topology diagram
        """
        diagram_service = MermaidDiagramService(self.db)

        # Generate new diagram
        doc_id = await diagram_service.auto_generate_and_save(
            org_id,
            document_name="Network Topology (Auto)",
            auto_update=True,
        )

        return str(doc_id)


# Example usage in CLI/scheduler:
async def run_ninjaone_sync(
    db: AsyncSession,
    org_id: UUID,
    ninja_api_url: str,
    ninja_client_id: str,
    ninja_client_secret: str,
) -> None:
    """Run full NinjaOne discovery and sync."""
    ninja = NinjaOneIntegration(ninja_api_url, ninja_client_id, ninja_client_secret)

    # Discover devices
    devices = await ninja.discover_devices()

    # Sync to configurations
    sync_service = DiscoverySyncService(db)
    stats = await sync_service.sync_devices(org_id, devices)

    logger.info(f"NinjaOne sync complete: {stats}")

    # Generate topology diagram
    doc_id = await sync_service.generate_topology_diagram(org_id)
    logger.info(f"Topology diagram: {doc_id}")


async def run_meraki_sync(
    db: AsyncSession,
    org_id: UUID,
    meraki_api_key: str,
    meraki_org_id: str,
) -> None:
    """Run full Meraki discovery and sync."""
    meraki = MerakiIntegration(meraki_api_key)

    # Discover devices
    devices = await meraki.discover_devices(meraki_org_id)

    # Sync to configurations
    sync_service = DiscoverySyncService(db)
    stats = await sync_service.sync_devices(org_id, devices)

    logger.info(f"Meraki sync complete: {stats}")

    # Generate topology diagram
    doc_id = await sync_service.generate_topology_diagram(org_id)
    logger.info(f"Topology diagram: {doc_id}")
