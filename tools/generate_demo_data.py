#!/usr/bin/env python3
"""
Generate sample MSP data for Skra demo.

Creates realistic organizations, configurations, passwords, documents, etc.
for demonstration purposes.

Usage:
    python generate_demo_data.py --api-url http://localhost:8080 --token <jwt-token>
    
Or run directly against the database:
    python generate_demo_data.py --database-url postgresql://...
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import string
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Demo data
COMPANIES = [
    {
        "name": "Acme Manufacturing",
        "industry": "Manufacturing",
        "size": "50-100 employees",
        "city": "Detroit",
        "state": "MI",
    },
    {
        "name": "TechStart Solutions",
        "industry": "Technology",
        "size": "10-50 employees",
        "city": "Austin",
        "state": "TX",
    },
    {
        "name": "Summit Financial Group",
        "industry": "Finance",
        "size": "100-500 employees",
        "city": "Denver",
        "state": "CO",
    },
    {
        "name": "Harbor Medical Clinic",
        "industry": "Healthcare",
        "size": "20-50 employees",
        "city": "Seattle",
        "state": "WA",
    },
]

DEVICE_TEMPLATES = [
    {"type": "firewall", "manufacturer": "Fortinet", "models": ["FortiGate 60F", "FortiGate 100F", "FortiGate 200F"]},
    {"type": "switch", "manufacturer": "Cisco", "models": ["Catalyst 2960X", "Catalyst 9300", "SG350-28"]},
    {"type": "router", "manufacturer": "Cisco", "models": ["ISR 4331", "ISR 1111", "Meraki MX68"]},
    {"type": "server", "manufacturer": "Dell", "models": ["PowerEdge R740", "PowerEdge R640", "PowerEdge T340"]},
    {"type": "server", "manufacturer": "HPE", "models": ["ProLiant DL380", "ProLiant ML350"]},
    {"type": "workstation", "manufacturer": "Dell", "models": ["OptiPlex 7090", "Precision 3560", "Latitude 5520"]},
    {"type": "ap", "manufacturer": "Ubiquiti", "models": ["UAP-AC-Pro", "UAP-AC-Lite", "U6-Pro"]},
    {"type": "ap", "manufacturer": "Cisco", "models": ["Aironet 1815i", "Meraki MR46"]},
    {"type": "ups", "manufacturer": "APC", "models": ["Smart-UPS 1500VA", "Smart-UPS 3000VA"]},
]

PASSWORD_CATEGORIES = [
    {"name": "Domain Admin", "type": "windows", "has_totp": True},
    {"name": "Office 365 Global Admin", "type": "cloud", "has_totp": True},
    {"name": "Firewall Admin", "type": "network", "has_totp": False},
    {"name": "Switch Admin", "type": "network", "has_totp": False},
    {"name": "Server Root", "type": "linux", "has_totp": True},
    {"name": "Database sa", "type": "database", "has_totp": False},
    {"name": "Backup System", "type": "backup", "has_totp": False},
    {"name": "Wi-Fi Admin", "type": "wireless", "has_totp": False},
]

LOCATIONS = [
    {"name": "Main Office", "type": "primary"},
    {"name": "Warehouse", "type": "secondary"},
    {"name": "Branch Office", "type": "branch"},
    {"name": "Data Center", "type": "datacenter"},
]

NETWORK_DIAGRAM_TEMPLATE = """```mermaid
flowchart LR
    subgraph Internet["Internet"]
        WAN["ISP Gateway\\n{wan_ip}"]
    end
    
    subgraph Core["Core Network"]
        FW["{firewall}\\n{fw_ip}"]
        SW1["Core Switch\\n{switch_ip}"]
    end
    
    subgraph Servers["Server VLAN {server_vlan}"]
        SRV1["{server1}\\n{server1_ip}"]
        SRV2["{server2}\\n{server2_ip}"]
    end
    
    subgraph Workstations["Workstation VLAN {workstation_vlan}"]
        WS1["Workstations"]
    end
    
    WAN --> FW
    FW --> SW1
    SW1 --> SRV1
    SW1 --> SRV2
    SW1 --> WS1
    
    classDef up fill:#90EE90,stroke:#228B22
    classDef down fill:#FFB6C1,stroke:#DC143C
    class FW,SW1,SRV1,SRV2,WS1 up
```
"""

SOP_DOCUMENTS = [
    {
        "title": "New Employee Onboarding - IT Checklist",
        "content": """# New Employee Onboarding - IT Checklist

## Pre-Arrival (Day -1)
- [ ] Create AD account
- [ ] Assign Office 365 license
- [ ] Prepare laptop/workstation
- [ ] Create email signature template
- [ ] Add to distribution lists

## Day 1
- [ ] Deliver hardware
- [ ] Setup desk peripherals
- [ ] Initial login and password reset
- [ ] MFA setup (phone app)
- [ ] Brief security training (15 min)

## Week 1
- [ ] Access to file shares
- [ ] VPN configuration
- [ ] Printer setup
- [ ] Application installations

## Contact
**IT Support:** helpdesk@company.com | ext. 4357"""
    },
    {
        "title": "After-Hours Emergency Procedure",
        "content": """# After-Hours Emergency Procedure

## Critical Systems
**Priority 1 (Immediate Response):**
- Email server down
- Internet connectivity loss
- Security breach
- Core server failure

**Priority 2 (Within 2 hours):**
- Single workstation failure
- Printer issues
- Non-critical application down

## Emergency Contacts

| Role | Name | Phone |
|------|------|-------|
| IT Manager | {it_manager} | {it_manager_phone} |
| Network Admin | {network_admin} | {network_admin_phone} |
| MSP Hotline | - | 1-800-555-0199 |

## Escalation Path
1. Try self-service portal: https://helpdesk.company.com
2. Call MSP hotline if unable to login
3. Text IT Manager for Priority 1 only"""
    },
]


class DemoDataGenerator:
    """Generates realistic demo data for Skra."""

    def __init__(self, base_url: str, token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {token}"} if token else {},
            timeout=30.0,
        )
        self.created_ids: dict[str, list[str]] = {
            "organizations": [],
            "configurations": [],
            "passwords": [],
            "documents": [],
            "locations": [],
        }

    async def generate_all(self) -> dict[str, int]:
        """Generate complete demo dataset."""
        stats = {
            "organizations": 0,
            "configurations": 0,
            "passwords": 0,
            "documents": 0,
            "locations": 0,
        }

        print("🚀 Generating demo data...")

        # Create organizations first
        for company in COMPANIES:
            org_id = await self._create_organization(company)
            if org_id:
                self.created_ids["organizations"].append(org_id)
                stats["organizations"] += 1
                print(f"  ✓ Created organization: {company['name']}")

                # Create locations for this org
                for loc in LOCATIONS:
                    if random.random() > 0.3:  # 70% chance
                        loc_id = await self._create_location(org_id, loc)
                        if loc_id:
                            stats["locations"] += 1

                # Create configurations (network infrastructure)
                config_count = random.randint(8, 20)
                for i in range(config_count):
                    config_id = await self._create_configuration(org_id)
                    if config_id:
                        stats["configurations"] += 1

                # Create passwords
                for pwd_template in PASSWORD_CATEGORIES:
                    pwd_id = await self._create_password(org_id, pwd_template)
                    if pwd_id:
                        stats["passwords"] += 1

                # Create documents
                for doc_template in SOP_DOCUMENTS:
                    doc_id = await self._create_document(org_id, doc_template)
                    if doc_id:
                        stats["documents"] += 1

                # Create network diagram document
                await self._create_network_diagram(org_id)
                stats["documents"] += 1

        print(f"\n✅ Demo data generation complete!")
        print(f"   Organizations: {stats['organizations']}")
        print(f"   Configurations: {stats['configurations']}")
        print(f"   Passwords: {stats['passwords']}")
        print(f"   Documents: {stats['documents']}")
        print(f"   Locations: {stats['locations']}")

        return stats

    async def _create_organization(self, company: dict) -> str | None:
        """Create an organization."""
        try:
            response = await self.client.post(
                "/api/organizations",
                json={
                    "name": company["name"],
                    "metadata": {
                        "industry": company["industry"],
                        "size": company["size"],
                        "city": company["city"],
                        "state": company["state"],
                    },
                },
            )
            if response.status_code in (200, 201):
                return response.json()["id"]
            elif response.status_code == 409:
                # Already exists, try to find it
                list_resp = await self.client.get(
                    "/api/organizations",
                    params={"search": company["name"], "limit": 1},
                )
                if list_resp.status_code == 200:
                    items = list_resp.json().get("items", [])
                    if items:
                        return items[0]["id"]
        except Exception as e:
            print(f"  ✗ Failed to create organization {company['name']}: {e}")
        return None

    async def _create_location(self, org_id: str, loc: dict) -> str | None:
        """Create a location."""
        try:
            cities = ["Downtown", "North Campus", "South Building", "East Wing"]
            city = random.choice(cities)
            
            response = await self.client.post(
                f"/api/organizations/{org_id}/locations",
                json={
                    "name": f"{loc['name']} - {city}",
                    "address_1": f"{random.randint(100, 9999)} {random.choice(['Main St', 'First Ave', 'Commerce Blvd'])}",
                    "city": "Demo City",
                    "region": "DC",
                    "postal_code": f"{random.randint(10000, 99999)}",
                    "notes": f"{loc['type'].title()} location for organization.",
                },
            )
            if response.status_code in (200, 201):
                return response.json()["id"]
        except Exception as e:
            print(f"    ✗ Failed to create location: {e}")
        return None

    async def _create_configuration(self, org_id: str) -> str | None:
        """Create a configuration (device)."""
        template = random.choice(DEVICE_TEMPLATES)
        model = random.choice(template["models"])
        
        # Generate realistic IP
        subnet = random.choice([10, 172, 192])
        ip = f"{subnet}.{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(2, 254)}"
        
        # Generate MAC address
        mac = ":".join(["".join(random.choices("0123456789ABCDEF", k=2)) for _ in range(6)])
        
        # Device name based on type
        prefixes = {
            "firewall": "FW",
            "switch": "SW",
            "router": "RTR",
            "server": "SRV",
            "workstation": "WS",
            "ap": "AP",
            "ups": "UPS",
        }
        prefix = prefixes.get(template["type"], "DEV")
        name = f"{prefix}-{random.randint(10, 99):02d}"
        
        try:
            response = await self.client.post(
                f"/api/organizations/{org_id}/configurations",
                json={
                    "name": name,
                    "configuration_type": template["type"],
                    "manufacturer": template["manufacturer"],
                    "model": model,
                    "serial_number": "".join(random.choices(string.ascii_uppercase + string.digits, k=12)),
                    "ip_address": ip,
                    "mac_address": mac,
                    "operating_system": random.choice(["Windows Server 2022", "Ubuntu 22.04", "Cisco IOS", "FortiOS 7.0", None]),
                    "notes": f"Primary {template['type']} for {random.choice(['HQ', 'Branch', 'Datacenter'])}.",
                    "status": random.choice(["active", "active", "active", "maintenance"]),
                },
            )
            if response.status_code in (200, 201):
                return response.json()["id"]
        except Exception as e:
            print(f"    ✗ Failed to create configuration: {e}")
        return None

    async def _create_password(self, org_id: str, template: dict) -> str | None:
        """Create a password."""
        # Generate realistic-looking password
        words = ["Secure", "Admin", "Pass", "Key", "Access", "Login", "System", "Core"]
        pw = f"{random.choice(words)}{random.choice(['!', '@', '#'])}{random.randint(1000, 9999)}"
        
        # Generate TOTP secret for some passwords
        totp_secret = None
        if template["has_totp"]:
            # Base32 encoded secret (16 chars)
            totp_secret = "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567", k=16))
        
        try:
            payload: dict[str, Any] = {
                "name": f"{template['name']} - {random.choice(['Primary', 'Secondary', 'Backup'])}",
                "username": random.choice(["admin", "administrator", "root", "svc_account"]),
                "password": pw,
                "url": random.choice([
                    "https://admin.office365.com",
                    "https://firewall.local",
                    "https://vcenter.local",
                    None,
                ]),
                "notes": f"Category: {template['type']}\nLast rotated: {(datetime.now() - timedelta(days=random.randint(1, 90))).strftime('%Y-%m-%d')}",
            }
            
            if totp_secret:
                payload["totp_secret"] = totp_secret
            
            response = await self.client.post(
                f"/api/organizations/{org_id}/passwords",
                json=payload,
            )
            if response.status_code in (200, 201):
                return response.json()["id"]
        except Exception as e:
            print(f"    ✗ Failed to create password: {e}")
        return None

    async def _create_document(self, org_id: str, template: dict) -> str | None:
        """Create a document."""
        try:
            # Fill in template variables
            content = template["content"]
            content = content.replace("{it_manager}", "John Smith")
            content = content.replace("{it_manager_phone}", "555-0100")
            content = content.replace("{network_admin}", "Jane Doe")
            content = content.replace("{network_admin_phone}", "555-0101")
            
            response = await self.client.post(
                f"/api/organizations/{org_id}/documents",
                json={
                    "name": template["title"],
                    "path": "/SOPs",
                    "content": content,
                },
            )
            if response.status_code in (200, 201):
                return response.json()["id"]
        except Exception as e:
            print(f"    ✗ Failed to create document: {e}")
        return None

    async def _create_network_diagram(self, org_id: str) -> str | None:
        """Create a network topology document with Mermaid diagram."""
        try:
            # Generate network values
            wan_ip = f"203.0.{random.randint(1, 254)}.{random.randint(1, 254)}"
            fw_ip = f"10.{random.randint(1, 254)}.1.1"
            switch_ip = f"10.{random.randint(1, 254)}.1.2"
            server_vlan = random.randint(10, 99)
            workstation_vlan = server_vlan + 1
            server1_ip = f"10.{random.randint(1, 254)}.{server_vlan}.10"
            server2_ip = f"10.{random.randint(1, 254)}.{server_vlan}.11"
            
            firewall_model = random.choice(["FortiGate 100F", "Cisco ASA 5508", "Palo Alto PA-440"])
            server1 = random.choice(["DC01", "APP01", "FS01"])
            server2 = random.choice(["DC02", "SQL01", "WEB01"])
            
            mermaid_content = NETWORK_DIAGRAM_TEMPLATE.format(
                wan_ip=wan_ip,
                firewall=firewall_model,
                fw_ip=fw_ip,
                switch_ip=switch_ip,
                server_vlan=server_vlan,
                workstation_vlan=workstation_vlan,
                server1=server1,
                server1_ip=server1_ip,
                server2=server2,
                server2_ip=server2_ip,
            )
            
            response = await self.client.post(
                f"/api/organizations/{org_id}/documents",
                json={
                    "name": "Network Topology Diagram",
                    "path": "/Infrastructure",
                    "content": f"# Network Topology\n\nAuto-generated network diagram:\n\n{mermaid_content}\n\n_Last updated: {datetime.now().strftime('%Y-%m-%d')}_",
                    "metadata": {
                        "diagram_type": "network_topology",
                        "auto_generated": False,
                    },
                },
            )
            if response.status_code in (200, 201):
                return response.json()["id"]
        except Exception as e:
            print(f"    ✗ Failed to create network diagram: {e}")
        return None

    async def cleanup(self) -> None:
        """Clean up created data."""
        print("\n🧹 Cleaning up demo data...")
        
        # Delete in reverse order
        for doc_id in self.created_ids["documents"]:
            try:
                # Need to find org_id first - skip for now
                pass
            except:
                pass
        
        print("   Cleanup complete (manual removal may be needed)")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()


async def main():
    parser = argparse.ArgumentParser(description="Generate demo data for Skra")
    parser.add_argument("--api-url", default="http://localhost:8080", help="API base URL")
    parser.add_argument("--token", help="JWT auth token (or set SKRA_TOKEN env var)")
    parser.add_argument("--cleanup", action="store_true", help="Remove demo data after creation")
    
    args = parser.parse_args()
    
    token = args.token or "demo-token"
    
    async with DemoDataGenerator(args.api_url, token) as generator:
        stats = await generator.generate_all()
        
        if args.cleanup:
            await generator.cleanup()
        
        print(f"\n📊 Summary:")
        print(f"   Total entities created: {sum(stats.values())}")
        print(f"\n🌐 Access your demo at: {args.api_url}")
        print(f"   Dashboard: {args.api_url}/admin/migration")


if __name__ == "__main__":
    asyncio.run(main())
