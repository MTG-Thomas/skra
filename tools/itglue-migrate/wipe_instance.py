#!/usr/bin/env python3
"""
DANGEROUS: This script will DELETE ALL DATA from your Skra instance.

This includes:
  - All organizations (and all their data via cascade)
  - All custom asset types
  - All configuration types
  - All configuration statuses

THIS ACTION CANNOT BE UNDONE.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from itglue_migrate.api_client import SkraClient, APIError


RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
BOLD = "\033[1m"
RESET = "\033[0m"

# Track whether deletion has started (for interrupt handling)
_deletion_started = False


def print_banner():
    """Print scary warning banner."""
    print(f"""
{RED}{BOLD}
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║   ██████╗  █████╗ ███╗   ██╗ ██████╗ ███████╗██████╗                        ║
║   ██╔══██╗██╔══██╗████╗  ██║██╔════╝ ██╔════╝██╔══██╗                       ║
║   ██║  ██║███████║██╔██╗ ██║██║  ███╗█████╗  ██████╔╝                       ║
║   ██║  ██║██╔══██║██║╚██╗██║██║   ██║██╔══╝  ██╔══██╗                       ║
║   ██████╔╝██║  ██║██║ ╚████║╚██████╔╝███████╗██║  ██║                       ║
║   ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝                       ║
║                                                                              ║
║                    THIS WILL DELETE ALL YOUR DATA                            ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
{RESET}
""")


async def get_counts(client: SkraClient) -> dict[str, int]:
    """Get counts of all entities."""
    counts = {
        "organizations": 0,
        "custom_asset_types": 0,
        "configuration_types": 0,
        "configuration_statuses": 0,
    }

    try:
        orgs = await client.list_organizations()
        counts["organizations"] = len(orgs)
    except APIError:
        pass

    try:
        types = await client.list_custom_asset_types(include_inactive=True)
        counts["custom_asset_types"] = len(types)
    except APIError:
        pass

    try:
        types = await client.list_configuration_types(include_inactive=True)
        counts["configuration_types"] = len(types)
    except APIError:
        pass

    try:
        statuses = await client.list_configuration_statuses(include_inactive=True)
        counts["configuration_statuses"] = len(statuses)
    except APIError:
        pass

    return counts


async def wipe_instance(api_url: str, token: str) -> None:
    """Wipe the entire instance."""
    global _deletion_started

    async with SkraClient(base_url=api_url, api_key=token) as client:
        # Get initial counts
        print(f"\n{YELLOW}Fetching current data counts...{RESET}\n")
        counts = await get_counts(client)

        print(f"  Organizations:         {counts['organizations']} (+ all child data)")
        print(f"  Custom Asset Types:    {counts['custom_asset_types']}")
        print(f"  Configuration Types:   {counts['configuration_types']}")
        print(f"  Configuration Statuses:{counts['configuration_statuses']}")

        total = sum(counts.values())
        if total == 0:
            print(f"\n{GREEN}Instance is already empty. Nothing to delete.{RESET}")
            return

        # Confirmation
        print(f"\n{RED}{'='*60}{RESET}")
        print(f"{RED}{BOLD}THIS CANNOT BE UNDONE.{RESET}")
        confirm = input(f"{BOLD}Type 'I AM VERY SURE' to proceed: {RESET}")
        if confirm != "I AM VERY SURE":
            print(f"\n{GREEN}Aborted. No changes made.{RESET}")
            return

        print(f"\n{RED}{BOLD}Starting deletion...{RESET}")
        print(f"{YELLOW}(Press Ctrl+C to abort - partial deletion may occur){RESET}\n")

        _deletion_started = True

        deleted = {
            "organizations": 0,
            "custom_asset_types": 0,
            "configuration_types": 0,
            "configuration_statuses": 0,
        }

        # Delete organizations (cascade handles all child data)
        try:
            orgs = await client.list_organizations()
            for org in orgs:
                org_id = org.get("id")
                org_name = org.get("name", "Unknown")
                if org_id:
                    try:
                        await client._request("DELETE", f"/api/organizations/{org_id}")
                        deleted["organizations"] += 1
                        print(f"  {GREEN}Deleted organization: {org_name}{RESET}")
                    except APIError as e:
                        print(f"  {YELLOW}Failed to delete org {org_name}: {e}{RESET}")
        except APIError as e:
            print(f"  {YELLOW}Error listing organizations: {e}{RESET}")

        # Delete custom asset types
        try:
            types = await client.list_custom_asset_types(include_inactive=True)
            for cat in types:
                cat_id = cat.get("id")
                cat_name = cat.get("name", "Unknown")
                if cat_id:
                    try:
                        await client._request("DELETE", f"/api/custom-asset-types/{cat_id}")
                        deleted["custom_asset_types"] += 1
                        print(f"  {GREEN}Deleted custom asset type: {cat_name}{RESET}")
                    except APIError as e:
                        print(f"  {YELLOW}Failed to delete custom asset type {cat_name}: {e}{RESET}")
        except APIError as e:
            print(f"  {YELLOW}Error listing custom asset types: {e}{RESET}")

        # Delete configuration types
        try:
            types = await client.list_configuration_types(include_inactive=True)
            for ct in types:
                ct_id = ct.get("id")
                ct_name = ct.get("name", "Unknown")
                if ct_id:
                    try:
                        await client._request("DELETE", f"/api/configuration-types/{ct_id}")
                        deleted["configuration_types"] += 1
                        print(f"  {GREEN}Deleted configuration type: {ct_name}{RESET}")
                    except APIError as e:
                        print(f"  {YELLOW}Failed to delete config type {ct_name}: {e}{RESET}")
        except APIError as e:
            print(f"  {YELLOW}Error listing configuration types: {e}{RESET}")

        # Delete configuration statuses
        try:
            statuses = await client.list_configuration_statuses(include_inactive=True)
            for cs in statuses:
                cs_id = cs.get("id")
                cs_name = cs.get("name", "Unknown")
                if cs_id:
                    try:
                        await client._request("DELETE", f"/api/configuration-statuses/{cs_id}")
                        deleted["configuration_statuses"] += 1
                        print(f"  {GREEN}Deleted configuration status: {cs_name}{RESET}")
                    except APIError as e:
                        print(f"  {YELLOW}Failed to delete config status {cs_name}: {e}{RESET}")
        except APIError as e:
            print(f"  {YELLOW}Error listing configuration statuses: {e}{RESET}")

        # Summary
        print(f"\n{GREEN}{'='*60}{RESET}")
        print(f"{GREEN}{BOLD}Deletion complete!{RESET}")
        print(f"\n  Organizations deleted:         {deleted['organizations']}")
        print(f"  Custom asset types deleted:    {deleted['custom_asset_types']}")
        print(f"  Configuration types deleted:   {deleted['configuration_types']}")
        print(f"  Configuration statuses deleted:{deleted['configuration_statuses']}")


def main():
    print_banner()

    api_url = os.environ.get("SKRA_API_URL")
    token = os.environ.get("SKRA_API_TOKEN")

    if not api_url:
        print(f"{RED}Error: SKRA_API_URL environment variable not set{RESET}")
        sys.exit(1)

    if not token:
        print(f"{RED}Error: SKRA_API_TOKEN environment variable not set{RESET}")
        sys.exit(1)

    print(f"Target API: {BOLD}{api_url}{RESET}")
    print()

    # Safety check for production (legacy bifrostdocs.com kept: old prod URLs must still trip this)
    if "prod" in api_url.lower() or "bifrostdocs.com" in api_url.lower():
        print(f"{RED}{BOLD}ERROR: This appears to be a production URL!{RESET}")
        print(f"{RED}This script is intended for development/testing only.{RESET}")
        print(f"{RED}If you REALLY want to wipe production, edit this script.{RESET}")
        sys.exit(1)

    asyncio.run(wipe_instance(api_url, token))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        if _deletion_started:
            print(f"\n\n{YELLOW}Interrupted during deletion. Some data may have been deleted.{RESET}")
            sys.exit(1)
        else:
            print(f"\n\n{GREEN}Aborted by user (Ctrl+C). No changes made.{RESET}")
            sys.exit(0)
