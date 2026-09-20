#!/usr/bin/env python3
"""Debug script to test API endpoints directly."""

import asyncio
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, "src")

from itglue_migrate.api_client import SkraClient
from itglue_migrate.state_fetcher import StateFetcher
from itglue_migrate.csv_parser import CSVParser


async def main():
    api_url = os.environ.get("SKRA_API_URL")
    token = os.environ.get("SKRA_API_TOKEN")
    org_id = os.environ.get("SKRA_ORG_ID")  # UUID of the org to test
    export_path = os.environ.get("SKRA_EXPORT_PATH")  # Path to CSV export
    org_name = os.environ.get("SKRA_ORG_NAME", "Covi, Inc.")  # Org name to filter

    if not all([api_url, token]):
        print("Set SKRA_API_URL and SKRA_API_TOKEN environment variables")
        return

    async with SkraClient(base_url=api_url, api_key=token) as client:
        print("=" * 60)
        print("Testing API endpoints...")
        print("=" * 60)

        # Test configuration types
        print("\n1. Configuration Types (include_inactive=True):")
        try:
            types = await client.list_configuration_types(include_inactive=True)
            print(f"   Returned: {len(types)} types")
            for t in types[:3]:
                print(f"   - {t.get('name')} (id={t.get('id')})")
            if len(types) > 3:
                print(f"   ... and {len(types) - 3} more")
        except Exception as e:
            print(f"   ERROR: {e}")

        # Test configuration statuses
        print("\n2. Configuration Statuses (include_inactive=True):")
        try:
            statuses = await client.list_configuration_statuses(include_inactive=True)
            print(f"   Returned: {len(statuses)} statuses")
            for s in statuses[:3]:
                print(f"   - {s.get('name')} (id={s.get('id')})")
        except Exception as e:
            print(f"   ERROR: {e}")

        # Test custom asset types
        print("\n3. Custom Asset Types (include_inactive=True):")
        try:
            cat_types = await client.list_custom_asset_types(include_inactive=True)
            print(f"   Returned: {len(cat_types)} types")
            for t in cat_types[:3]:
                print(f"   - {t.get('name')} (id={t.get('id')})")
            if len(cat_types) > 3:
                print(f"   ... and {len(cat_types) - 3} more")
        except Exception as e:
            print(f"   ERROR: {e}")

        if not org_id:
            print("\n\nSet SKRA_ORG_ID to test org-scoped endpoints")
            return

        # Test locations
        print(f"\n4. Locations for org {org_id} (show_disabled=True):")
        try:
            result = await client.list_locations(org_id, limit=100, show_disabled=True)
            items = result.get("items", [])
            total = result.get("total", len(items))
            print(f"   Returned: {len(items)} items, total={total}")
            for loc in items[:3]:
                meta = loc.get("metadata", {})
                print(f"   - {loc.get('name')} (itglue_id={meta.get('itglue_id')}, enabled={loc.get('is_enabled')})")
            if len(items) > 3:
                print(f"   ... and {len(items) - 3} more")
        except Exception as e:
            print(f"   ERROR: {e}")

        # Test documents
        print(f"\n5. Documents for org {org_id} (show_disabled=True):")
        try:
            result = await client.list_documents(org_id, limit=100, show_disabled=True)
            items = result.get("items", [])
            total = result.get("total", len(items))
            print(f"   Returned: {len(items)} items, total={total}")
            for doc in items[:3]:
                meta = doc.get("metadata", {})
                print(f"   - {doc.get('name')} (itglue_id={meta.get('itglue_id')}, enabled={doc.get('is_enabled')})")
            if len(items) > 3:
                print(f"   ... and {len(items) - 3} more")
        except Exception as e:
            print(f"   ERROR: {e}")

        # Test configurations
        print(f"\n6. Configurations for org {org_id} (show_disabled=True):")
        try:
            result = await client.list_configurations(org_id, limit=100, show_disabled=True)
            items = result.get("items", [])
            total = result.get("total", len(items))
            print(f"   Returned: {len(items)} items, total={total}")
            for cfg in items[:3]:
                meta = cfg.get("metadata", {})
                print(f"   - {cfg.get('name')} (itglue_id={meta.get('itglue_id')}, enabled={cfg.get('is_enabled')})")
        except Exception as e:
            print(f"   ERROR: {e}")

        # Test passwords
        print(f"\n7. Passwords for org {org_id} (show_disabled=True):")
        try:
            result = await client.list_passwords(org_id, limit=100, show_disabled=True)
            items = result.get("items", [])
            total = result.get("total", len(items))
            print(f"   Returned: {len(items)} items, total={total}")
        except Exception as e:
            print(f"   ERROR: {e}")

        print("\n" + "=" * 60)

        # Now test StateFetcher if we have org_id
        if org_id:
            print("\n\nTesting StateFetcher...")
            print("=" * 60)

            fetcher = StateFetcher(client)
            state = await fetcher.fetch_for_org(org_id)

            print(f"\nState fetched:")
            print(f"  - config_type_by_name: {len(state.config_type_by_name)} types")
            print(f"  - config_status_by_name: {len(state.config_status_by_name)} statuses")
            print(f"  - custom_asset_type_by_name: {len(state.custom_asset_type_by_name)} types")
            print(f"  - location_by_itglue_id: {len(state.location_by_itglue_id)} locations")
            print(f"  - document_by_itglue_id: {len(state.document_by_itglue_id)} documents")
            print(f"  - config_by_itglue_id: {len(state.config_by_itglue_id)} configurations")
            print(f"  - password_by_itglue_id: {len(state.password_by_itglue_id)} passwords")
            print(f"  - custom_asset_by_itglue_id: {len(state.custom_asset_by_itglue_id)} custom assets")

            # Show sample itglue_ids from state
            print(f"\nSample location itglue_ids from API state:")
            for itglue_id in list(state.location_by_itglue_id.keys())[:5]:
                print(f"    '{itglue_id}'")

            print(f"\nSample document itglue_ids from API state:")
            for itglue_id in list(state.document_by_itglue_id.keys())[:5]:
                print(f"    '{itglue_id}'")

        # Compare with CSV if export path provided
        if export_path and org_id:
            print("\n\nComparing with CSV export...")
            print("=" * 60)

            export_path = Path(export_path)
            parser = CSVParser()

            # Parse locations
            if (export_path / "locations.csv").exists():
                locations = parser.parse_locations(export_path / "locations.csv")
                # Get org's ITGlue ID from organizations.csv
                orgs = parser.parse_organizations(export_path / "organizations.csv")
                target_org = next((o for o in orgs if o.get("name") == org_name), None)
                org_itglue_id = str(target_org.get("id", "")) if target_org else ""

                org_locations = [
                    loc for loc in locations
                    if str(loc.get("organization_id", "")) == org_itglue_id
                    or str(loc.get("organization_id", "")) == org_name
                ]

                print(f"\nCSV locations for '{org_name}':")
                print(f"  Total in CSV: {len(locations)}")
                print(f"  Filtered for org (id={org_itglue_id}): {len(org_locations)}")
                print(f"  Sample CSV itglue_ids:")
                for loc in org_locations[:5]:
                    print(f"    '{loc.get('id')}' - {loc.get('name')}")

                # Check matching
                matches = 0
                for loc in org_locations:
                    csv_id = str(loc.get("id", ""))
                    if csv_id in state.location_by_itglue_id:
                        matches += 1
                print(f"  Matches with API state: {matches}")

            # Parse documents
            if (export_path / "documents.csv").exists():
                documents = parser.parse_documents(export_path / "documents.csv")
                org_documents = [
                    doc for doc in documents
                    if str(doc.get("organization_id", "")) == org_itglue_id
                    or str(doc.get("organization_id", "")) == org_name
                ]

                print(f"\nCSV documents for '{org_name}':")
                print(f"  Total in CSV: {len(documents)}")
                print(f"  Filtered for org: {len(org_documents)}")
                print(f"  Sample CSV itglue_ids:")
                for doc in org_documents[:5]:
                    print(f"    '{doc.get('id')}' - {doc.get('name')}")

                # Check matching
                matches = 0
                for doc in org_documents:
                    csv_id = str(doc.get("id", ""))
                    if csv_id in state.document_by_itglue_id:
                        matches += 1
                print(f"  Matches with API state: {matches}")

        print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
