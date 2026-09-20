"""State fetcher - retrieves existing state from API.

This module fetches all existing entities from the Skra API
and builds lookup tables by metadata.itglue_id for comparison with
CSV export data.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from itglue_migrate.api_client import SkraClient


@dataclass
class ExistingState:
    """Container for existing entity state fetched from API."""

    # Organization lookups
    org_by_itglue_id: dict[str, str] = field(default_factory=dict)
    org_by_name: dict[str, str] = field(default_factory=dict)

    # Entity lookups by itglue_id -> uuid
    config_by_itglue_id: dict[str, str] = field(default_factory=dict)
    config_type_by_name: dict[str, str] = field(default_factory=dict)
    config_status_by_name: dict[str, str] = field(default_factory=dict)
    location_by_itglue_id: dict[str, str] = field(default_factory=dict)
    document_by_itglue_id: dict[str, str] = field(default_factory=dict)
    password_by_itglue_id: dict[str, str] = field(default_factory=dict)
    custom_asset_type_by_name: dict[str, str] = field(default_factory=dict)
    custom_asset_by_itglue_id: dict[str, str] = field(default_factory=dict)

    # Full entity data for update comparisons
    configs: dict[str, dict[str, Any]] = field(default_factory=dict)
    locations: dict[str, dict[str, Any]] = field(default_factory=dict)
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)
    passwords: dict[str, dict[str, Any]] = field(default_factory=dict)
    custom_assets: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Custom asset type full data (including field definitions)
    custom_asset_types: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Relationships: set of "source_type:source_id:target_type:target_id"
    relationships: set[str] = field(default_factory=set)


class StateFetcher:
    """Fetches existing state from API for comparison."""

    def __init__(self, client: SkraClient) -> None:
        self.client = client

    async def fetch_all_orgs(self) -> ExistingState:
        """Fetch all organizations and build lookup."""
        state = ExistingState()

        orgs = await self.client.list_organizations()
        for org in orgs:
            org_id = org.get("id")
            if not org_id:
                continue

            org_id_str = str(org_id)
            name = org.get("name", "").lower()
            metadata = org.get("metadata") or {}
            itglue_id = metadata.get("itglue_id")

            if itglue_id:
                state.org_by_itglue_id[str(itglue_id)] = org_id_str
            if name:
                state.org_by_name[name] = org_id_str

        return state

    async def list_all_attachments(self, org_id: str) -> list[dict[str, Any]]:
        """List every migrated attachment record for an organization (GET only)."""
        return await self._paginate_all(
            self.client.list_attachments,
            org_id,
        )

    async def fetch_for_org(self, org_id: str) -> ExistingState:
        """Fetch all entities for a specific organization."""
        state = await self.fetch_all_orgs()

        # Fetch configuration types (global)
        await self._fetch_config_types(state)

        # Fetch configuration statuses (global)
        await self._fetch_config_statuses(state)

        # Fetch custom asset types (global)
        await self._fetch_custom_asset_types(state)

        # Fetch org-scoped entities
        await self._fetch_configurations(state, org_id)
        await self._fetch_locations(state, org_id)
        await self._fetch_documents(state, org_id)
        await self._fetch_passwords(state, org_id)
        await self._fetch_custom_assets(state, org_id)
        await self._fetch_relationships(state, org_id)

        return state

    async def _fetch_config_types(self, state: ExistingState) -> None:
        """Fetch all configuration types."""
        types = await self.client.list_configuration_types(include_inactive=True)
        for ct in types:
            name = ct.get("name", "").lower()
            type_id = ct.get("id")
            if name and type_id:
                state.config_type_by_name[name] = str(type_id)

    async def _fetch_config_statuses(self, state: ExistingState) -> None:
        """Fetch all configuration statuses."""
        statuses = await self.client.list_configuration_statuses(include_inactive=True)
        for cs in statuses:
            name = cs.get("name", "").lower()
            status_id = cs.get("id")
            if name and status_id:
                state.config_status_by_name[name] = str(status_id)

    async def _fetch_custom_asset_types(self, state: ExistingState) -> None:
        """Fetch all custom asset types with field definitions."""
        types = await self.client.list_custom_asset_types(include_inactive=True)
        for cat in types:
            name = cat.get("name", "").lower()
            cat_id = cat.get("id")
            if name and cat_id:
                state.custom_asset_type_by_name[name] = str(cat_id)
                # Store full type data including field definitions
                state.custom_asset_types[str(cat_id)] = cat

    async def _paginate_all(
        self,
        fetch_fn: Callable[..., Coroutine[Any, Any, dict[str, Any]]],
        org_id: str,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Paginate through all results from a list endpoint."""
        all_items: list[dict[str, Any]] = []
        offset = 0
        limit = 100

        while True:
            result = await fetch_fn(org_id, limit=limit, offset=offset, **kwargs)
            items = result.get("items", [])
            all_items.extend(items)

            if len(items) < limit:
                break
            offset += limit

        return all_items

    async def _fetch_configurations(self, state: ExistingState, org_id: str) -> None:
        """Fetch all configurations for an org."""
        items = await self._paginate_all(
            self.client.list_configurations,
            org_id,
            show_disabled=True,
        )
        for item in items:
            item_id = item.get("id")
            if not item_id:
                continue

            item_id_str = str(item_id)
            metadata = item.get("metadata") or {}
            itglue_id = metadata.get("itglue_id")

            if itglue_id:
                state.config_by_itglue_id[str(itglue_id)] = item_id_str
            state.configs[item_id_str] = item

    async def _fetch_locations(self, state: ExistingState, org_id: str) -> None:
        """Fetch all locations for an org."""
        items = await self._paginate_all(
            self.client.list_locations,
            org_id,
            show_disabled=True,
        )
        for item in items:
            item_id = item.get("id")
            if not item_id:
                continue

            item_id_str = str(item_id)
            metadata = item.get("metadata") or {}
            itglue_id = metadata.get("itglue_id")

            if itglue_id:
                state.location_by_itglue_id[str(itglue_id)] = item_id_str
            state.locations[item_id_str] = item

    async def _fetch_documents(self, state: ExistingState, org_id: str) -> None:
        """Fetch all documents for an org."""
        items = await self._paginate_all(
            self.client.list_documents,
            org_id,
            show_disabled=True,
        )
        for item in items:
            item_id = item.get("id")
            if not item_id:
                continue

            item_id_str = str(item_id)
            metadata = item.get("metadata") or {}
            itglue_id = metadata.get("itglue_id")

            if itglue_id:
                state.document_by_itglue_id[str(itglue_id)] = item_id_str
            state.documents[item_id_str] = item

    async def _fetch_passwords(self, state: ExistingState, org_id: str) -> None:
        """Fetch all passwords for an org."""
        items = await self._paginate_all(
            self.client.list_passwords,
            org_id,
            show_disabled=True,
        )
        for item in items:
            item_id = item.get("id")
            if not item_id:
                continue

            item_id_str = str(item_id)
            metadata = item.get("metadata") or {}
            itglue_id = metadata.get("itglue_id")

            if itglue_id:
                state.password_by_itglue_id[str(itglue_id)] = item_id_str
            state.passwords[item_id_str] = item

    async def _fetch_custom_assets(self, state: ExistingState, org_id: str) -> None:
        """Fetch all custom assets for an org (across all types)."""
        # Need to fetch for each custom asset type
        for _type_name, type_id in state.custom_asset_type_by_name.items():
            items = await self._paginate_all(
                self.client.list_custom_assets,
                org_id,
                type_id=type_id,
                show_disabled=True,
            )
            for item in items:
                item_id = item.get("id")
                if not item_id:
                    continue

                item_id_str = str(item_id)
                metadata = item.get("metadata") or {}
                itglue_id = metadata.get("itglue_id")

                if itglue_id:
                    state.custom_asset_by_itglue_id[str(itglue_id)] = item_id_str
                state.custom_assets[item_id_str] = item

    async def _fetch_relationships(self, state: ExistingState, org_id: str) -> None:
        """Fetch relationships for all passwords in org."""
        total_fetched = 0
        total_stored = 0
        for password_id in state.passwords:
            try:
                rels = await self.client.list_relationships(
                    org_id,
                    entity_type="password",
                    entity_id=password_id,
                )
                total_fetched += len(rels)
                for rel in rels:
                    # API returns bidirectional results - normalize to password:X:type:Y
                    # regardless of whether password is source or target
                    src_type = rel.get("source_type")
                    src_id = str(rel.get("source_id", ""))
                    tgt_type = rel.get("target_type")
                    tgt_id = str(rel.get("target_id", ""))

                    if src_type == "password" and src_id == str(password_id):
                        # Password is source: password -> other
                        key = f"password:{password_id}:{tgt_type}:{tgt_id}"
                    elif tgt_type == "password" and tgt_id == str(password_id):
                        # Password is target: other -> password, normalize to password -> other
                        key = f"password:{password_id}:{src_type}:{src_id}"
                    else:
                        # Shouldn't happen, but skip if neither matches
                        continue

                    state.relationships.add(key)
                    total_stored += 1
            except Exception:
                # Continue if relationship fetch fails
                pass
        logger.debug(
            f"Relationships: fetched {total_fetched} from API, "
            f"stored {total_stored} (normalized to password:X:type:Y)"
        )
