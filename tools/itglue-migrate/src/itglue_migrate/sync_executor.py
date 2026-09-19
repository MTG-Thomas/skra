"""Sync executor module for applying sync plans to the API.

This module provides the SyncExecutor class that takes a SyncPlan and
executes it against the Skra API, creating missing entities and
relationships. Supports dry-run mode for previewing changes.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from itglue_migrate.api_client import APIError
from itglue_migrate.document_processor import DocumentProcessor
from itglue_migrate.progress import Phase, ProgressReporter, SimpleProgressReporter
from itglue_migrate.relationship_audit import (
    RelationshipAuditResult,
    classify_relationship,
    summarize_relationship_audit,
)

if TYPE_CHECKING:
    from itglue_migrate.state_fetcher import ExistingState
    from itglue_migrate.sync_differ import SyncPlan

logger = logging.getLogger(__name__)


def _is_content_empty(html_content: str) -> bool:
    """Check if HTML content is empty after stripping tags.

    Args:
        html_content: HTML string to check.

    Returns:
        True if content is empty or whitespace-only after stripping HTML.
    """
    if not html_content:
        return True
    text = re.sub(r"<[^>]+>", "", html_content)
    return not text.strip()


def _map_org_status_to_is_enabled(status: str | None) -> bool:
    """Convert IT Glue organization_status to is_enabled boolean.

    Args:
        status: "Active" or other status from IT Glue export

    Returns:
        True if Active, False otherwise
    """
    if not status:
        return True
    return str(status).lower() == "active"


class APIClientProtocol(Protocol):
    """Protocol defining the API client interface used by SyncExecutor."""

    async def create_organization(
        self,
        name: str,
        is_enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    async def create_configuration(
        self,
        org_id: str,
        name: str,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def update_configuration(
        self,
        org_id: str,
        config_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def create_location(
        self,
        org_id: str,
        name: str,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def update_location(
        self,
        org_id: str,
        location_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def create_configuration_type(self, name: str) -> dict[str, Any]: ...

    async def create_configuration_status(self, name: str) -> dict[str, Any]: ...

    async def create_custom_asset_type(
        self,
        name: str,
        fields: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def create_custom_asset(
        self,
        org_id: str,
        type_id: str,
        values: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def update_custom_asset(
        self,
        org_id: str,
        type_id: str,
        asset_id: str,
        values: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def create_document(
        self,
        org_id: str,
        path: str,
        name: str,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def update_document(
        self,
        org_id: str,
        doc_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def create_password(
        self,
        org_id: str,
        name: str,
        password: str,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def update_password(
        self,
        org_id: str,
        password_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def create_relationship(
        self,
        org_id: str,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
    ) -> dict[str, Any]: ...


@dataclass
class SyncResult:
    """Result of executing a sync plan.

    Attributes:
        created: Count of entities created per type.
        updated: Count of entities updated per type.
        skipped: Count of entities skipped per type.
        failed: Count of entities that failed per type.
        errors: List of error messages encountered.
        id_map: Mapping of ITGlue IDs to newly created UUIDs.
    """

    created: dict[str, int] = field(default_factory=dict)
    updated: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    failed: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    id_map: dict[str, str] = field(default_factory=dict)
    # Track type_id for newly created custom assets (ITGlue ID -> type_id)
    asset_type_map: dict[str, str] = field(default_factory=dict)
    relationship_audit: list[dict[str, Any]] = field(default_factory=list)
    relationship_summary: dict[str, int] = field(default_factory=dict)


class SyncExecutor:
    """Executes a sync plan against the Skra API.

    The executor processes a SyncPlan and creates/updates entities in the
    target system. Supports dry-run mode to preview changes without making
    actual API calls.

    Example:
        >>> executor = SyncExecutor(client, org_id="org-uuid", dry_run=False)
        >>> result = await executor.execute(plan)
        >>> print(f"Created {result.created.get('configurations', 0)} configurations")
    """

    def __init__(
        self,
        client: APIClientProtocol,
        org_id: str,
        dry_run: bool = False,
        state: ExistingState | None = None,
        update_existing: bool = False,
        reporter: ProgressReporter | SimpleProgressReporter | None = None,
        doc_processor: DocumentProcessor | None = None,
        export_path: Path | None = None,
        skip_attachments: bool = False,
    ) -> None:
        """Initialize the sync executor.

        Args:
            client: Skra API client instance.
            org_id: Target organization UUID.
            dry_run: If True, count changes but don't make API calls.
            state: Existing state for lookups (required for cell_writes).
            update_existing: If True, update entities that already exist but have changed.
            reporter: Optional progress reporter for live progress display.
            doc_processor: Optional document processor for HTML cleaning and image uploads.
            export_path: Optional path to IT Glue export directory (for document processing).
            skip_attachments: If True, skip attachment uploads for faster testing.
        """
        self.client = client
        self.org_id = org_id
        self.dry_run = dry_run
        self.state = state
        self.update_existing = update_existing
        self.reporter = reporter
        self.doc_processor = doc_processor
        self.export_path = export_path
        self.skip_attachments = skip_attachments

    async def _upload_entity_attachments(
        self,
        entity_type: str,
        itglue_id: str,
        our_entity_id: str,
    ) -> int:
        """Upload attachments for an entity if doc_processor is available.

        Args:
            entity_type: IT Glue entity type (e.g., "configurations", "locations").
            itglue_id: IT Glue entity ID.
            our_entity_id: Our Skra entity UUID.

        Returns:
            Count of successfully uploaded attachments.
        """
        if self.skip_attachments:
            return 0

        if not self.doc_processor or not self.export_path:
            return 0

        try:
            count = await self.doc_processor.upload_entity_attachments(
                entity_type=entity_type,
                entity_id=itglue_id,
                org_uuid=self.org_id,
                our_entity_id=our_entity_id,
            )
            return count
        except Exception as e:
            logger.warning(f"Failed to upload attachments for {entity_type}/{itglue_id}: {e}")
            return 0

    async def execute(self, plan: SyncPlan) -> SyncResult:
        """Execute a sync plan.

        Processes all entity types in the plan, creating and updated
        entities as needed. In dry-run mode, counts are tracked but
        no API calls are made.

        Args:
            plan: The sync plan to execute.

        Returns:
            SyncResult with counts of created/failed entities and any errors.
        """
        result = SyncResult()

        # Execute in dependency order:
        # 0. Organizations first (need org UUIDs for all other entities)
        # 1. Global types (config types, statuses, custom asset types)
        # 2. Then org-scoped entities (locations, configurations, etc.)
        # 3. Finally relationships (need entity IDs to exist)

        await self._execute_organizations(plan, result)

        # Config types phase
        await self._execute_phase(
            Phase.CONFIGURATION_TYPES,
            plan.config_types.to_create,
            self._execute_config_types,
            plan, result
        )

        # Config statuses - no phase in enum, combine with config types
        await self._execute_config_statuses(plan, result)

        # Custom asset types phase
        await self._execute_phase(
            Phase.CUSTOM_ASSET_TYPES,
            plan.custom_asset_types.to_create,
            self._execute_custom_asset_types,
            plan, result
        )

        # Locations phase
        await self._execute_phase(
            Phase.LOCATIONS,
            plan.locations.to_create,
            self._execute_locations,
            plan, result
        )

        # Configurations phase
        await self._execute_phase(
            Phase.CONFIGURATIONS,
            plan.configurations.to_create,
            self._execute_configurations,
            plan, result
        )

        # Custom assets phase
        await self._execute_phase(
            Phase.CUSTOM_ASSETS,
            plan.custom_assets.to_create,
            self._execute_custom_assets,
            plan, result
        )

        # Documents phase
        await self._execute_phase(
            Phase.DOCUMENTS,
            plan.documents.to_create,
            self._execute_documents,
            plan, result
        )

        # Passwords phase
        await self._execute_phase(
            Phase.PASSWORDS,
            plan.passwords.to_create + plan.passwords.row_creates,
            self._execute_passwords,
            plan, result
        )

        # Cell writes - no separate phase, part of custom assets
        await self._execute_cell_writes(plan, result)

        # Relationships phase
        await self._execute_phase(
            Phase.RELATIONSHIPS,
            plan.relationships.to_create,
            self._execute_relationships,
            plan, result
        )

        # Execute updates if update_existing is enabled
        if self.update_existing:
            await self._execute_configuration_updates(plan, result)
            await self._execute_location_updates(plan, result)
            await self._execute_document_updates(plan, result)
            await self._execute_password_updates(plan, result)

        if result.relationship_audit:
            result.relationship_summary = summarize_relationship_audit(
                result.relationship_audit
            )

        return result

    async def _execute_phase(
        self,
        phase: Phase,
        entities: list[dict[str, Any]],
        execute_fn: Any,  # The execute function to call
        plan: SyncPlan,
        result: SyncResult,
    ) -> None:
        """Execute a phase with progress reporting.

        Args:
            phase: The phase to execute.
            entities: List of entities to process in this phase.
            execute_fn: The actual execution function to call.
            plan: The sync plan.
            result: The result accumulator.
        """
        if not entities:
            return

        if self.reporter:
            self.reporter.start_phase(phase, len(entities))

        await execute_fn(plan, result)

        if self.reporter:
            self.reporter.complete_phase()

    async def _execute_organizations(
        self, plan: SyncPlan, result: SyncResult
    ) -> None:
        """Execute organization creation."""
        for entity in plan.organizations.to_create:
            try:
                if self.dry_run:
                    result.created["organizations"] = (
                        result.created.get("organizations", 0) + 1
                    )
                    continue

                name = entity.get("name", "Unnamed")
                metadata = entity.get("metadata")

                # Get organization_status and map to is_enabled
                org_status = entity.get("organization_status")
                is_enabled = _map_org_status_to_is_enabled(org_status)

                response = await self.client.create_organization(
                    name=name,
                    is_enabled=is_enabled,
                    metadata=metadata,
                )

                # Track ID mapping using itglue_id from metadata
                itglue_id = (metadata or {}).get("itglue_id", "")
                if itglue_id and response.get("id"):
                    result.id_map[str(itglue_id)] = response["id"]

                result.created["organizations"] = (
                    result.created.get("organizations", 0) + 1
                )

            except APIError as e:
                if e.status_code == 409:
                    # Organization already exists - expected during re-sync
                    logger.info(f"Organization '{entity.get('name')}' already exists")
                    result.skipped["organizations"] = (
                        result.skipped.get("organizations", 0) + 1
                    )
                else:
                    result.failed["organizations"] = (
                        result.failed.get("organizations", 0) + 1
                    )
                    result.errors.append(f"Organization '{entity.get('name')}': {e}")
                    logger.warning(f"Failed to create organization: {e}")
            except Exception as e:
                result.failed["organizations"] = (
                    result.failed.get("organizations", 0) + 1
                )
                result.errors.append(f"Organization '{entity.get('name')}': {e}")
                logger.warning(f"Failed to create organization: {e}")

    async def _execute_configurations(
        self, plan: SyncPlan, result: SyncResult
    ) -> None:
        """Execute configuration creation.

        Handles CSV format: {id, name, configuration_type, configuration_status, serial, ip, mac, ...}
        Transforms to API format by resolving type/status IDs and mapping field names.
        """
        for entity in plan.configurations.to_create:
            name = entity.get("name", "Unnamed")

            if self.reporter:
                self.reporter.set_current_item(f"Configuration: {name}")

            try:
                itglue_id = str(entity.get("id", ""))

                if self.dry_run:
                    result.created["configurations"] = (
                        result.created.get("configurations", 0) + 1
                    )
                    if self.reporter:
                        self.reporter.update_progress(succeeded=1)
                    continue

                # Resolve configuration_type_id from name
                config_type_id = entity.get("configuration_type_id")
                if not config_type_id and self.state:
                    type_name = entity.get("configuration_type", "")
                    if type_name:
                        config_type_id = self.state.config_type_by_name.get(type_name.lower())

                # Resolve configuration_status_id from name
                config_status_id = entity.get("configuration_status_id")
                if not config_status_id and self.state:
                    status_name = entity.get("configuration_status", "")
                    if status_name:
                        config_status_id = self.state.config_status_by_name.get(status_name.lower())

                # Build metadata with itglue_id
                metadata = entity.get("metadata") or {}
                if itglue_id and "itglue_id" not in metadata:
                    metadata["itglue_id"] = itglue_id

                # Handle archived -> is_enabled
                is_enabled = entity.get("is_enabled", True)
                archived = entity.get("archived")
                if archived is not None:
                    archived_str = str(archived).lower()
                    is_enabled = archived_str not in ("true", "1", "yes")

                # Parse configuration_interfaces from JSON string if present
                interfaces = entity.get("configuration_interfaces")
                if isinstance(interfaces, str):
                    try:
                        interfaces = json.loads(interfaces)
                    except json.JSONDecodeError:
                        interfaces = None

                # Extract fields - handle both CSV names (serial, ip, mac) and API names
                response = await self.client.create_configuration(
                    org_id=self.org_id,
                    name=name,
                    configuration_type_id=config_type_id,
                    configuration_status_id=config_status_id,
                    serial_number=entity.get("serial_number") or entity.get("serial"),
                    asset_tag=entity.get("asset_tag"),
                    manufacturer=entity.get("manufacturer"),
                    model=entity.get("model"),
                    ip_address=entity.get("ip_address") or entity.get("ip"),
                    mac_address=entity.get("mac_address") or entity.get("mac"),
                    notes=entity.get("notes"),
                    metadata=metadata,
                    is_enabled=is_enabled,
                    interfaces=interfaces,
                )

                if skra_id := response.get("id"):
                    result.id_map[itglue_id] = skra_id

                    # Upload attachments
                    if self.doc_processor and self.export_path:
                        attachment_count = await self._upload_entity_attachments(
                            "configurations", itglue_id, skra_id
                        )
                        if attachment_count > 0 and self.reporter:
                            self.reporter.info(f"Uploaded {attachment_count} attachments")

                result.created["configurations"] = (
                    result.created.get("configurations", 0) + 1
                )
                if self.reporter:
                    disabled = 1 if not is_enabled else 0
                    self.reporter.update_progress(succeeded=1, disabled=disabled)

            except Exception as e:
                result.failed["configurations"] = (
                    result.failed.get("configurations", 0) + 1
                )
                result.errors.append(f"Configuration '{name}': {e}")
                logger.warning(f"Failed to create configuration: {e}")
                if self.reporter:
                    self.reporter.update_progress(failed=1)
                    self.reporter.error(f"Configuration '{name}': {e}")

    async def _execute_locations(self, plan: SyncPlan, result: SyncResult) -> None:
        """Execute location creation.

        Handles CSV format and adds itglue_id to metadata.
        Note: locations don't support is_enabled in the API.
        """
        for entity in plan.locations.to_create:
            name = entity.get("name", "Unnamed")

            if self.reporter:
                self.reporter.set_current_item(f"Location: {name}")

            try:
                itglue_id = str(entity.get("id", ""))

                if self.dry_run:
                    result.created["locations"] = (
                        result.created.get("locations", 0) + 1
                    )
                    if self.reporter:
                        self.reporter.update_progress(succeeded=1)
                    continue

                # Build metadata with itglue_id
                metadata = entity.get("metadata") or {}
                if itglue_id and "itglue_id" not in metadata:
                    metadata["itglue_id"] = itglue_id

                response = await self.client.create_location(
                    org_id=self.org_id,
                    name=name,
                    notes=entity.get("notes"),
                    metadata=metadata,
                    address_1=entity.get("address_1"),
                    address_2=entity.get("address_2"),
                    city=entity.get("city"),
                    region=entity.get("region"),
                    postal_code=entity.get("postal_code"),
                    country=entity.get("country"),
                    phone=entity.get("phone"),
                )

                if skra_id := response.get("id"):
                    result.id_map[itglue_id] = skra_id

                    # Upload attachments
                    if self.doc_processor and self.export_path:
                        attachment_count = await self._upload_entity_attachments(
                            "locations", itglue_id, skra_id
                        )
                        if attachment_count > 0 and self.reporter:
                            self.reporter.info(f"Uploaded {attachment_count} attachments")

                result.created["locations"] = result.created.get("locations", 0) + 1
                if self.reporter:
                    self.reporter.update_progress(succeeded=1)

            except Exception as e:
                result.failed["locations"] = result.failed.get("locations", 0) + 1
                result.errors.append(f"Location '{name}': {e}")
                logger.warning(f"Failed to create location: {e}")
                if self.reporter:
                    self.reporter.update_progress(failed=1)
                    self.reporter.error(f"Location '{name}': {e}")

    async def _execute_documents(self, plan: SyncPlan, result: SyncResult) -> None:
        """Execute document creation with HTML processing.

        Handles CSV format: {id, name, locator, content, organization_id}
        Transforms to API format with defaults for missing content.
        If DocumentProcessor is available, processes HTML content to clean it,
        extract images, and convert to markdown.
        """
        for entity in plan.documents.to_create:
            itglue_id = str(entity.get("id", ""))
            doc_name = entity.get("name", "Untitled")

            if self.reporter:
                self.reporter.set_current_item(f"Document: {doc_name}")

            # FIRST: Get content - try CSV, then load from filesystem
            raw_content = entity.get("content", "")

            # If CSV content is empty and we have a doc_processor, try loading from file
            if not raw_content and self.doc_processor:
                loaded_content = self.doc_processor.load_document_content(itglue_id)
                if loaded_content:
                    raw_content = loaded_content

            # SECOND: Check for empty content (after attempting to load from file)
            if _is_content_empty(raw_content):
                attachment_files = []
                if self.doc_processor and self.export_path:
                    try:
                        attachment_files = self.doc_processor.scanner.get_entity_attachments(
                            self.export_path,
                            "documents",
                            itglue_id,
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to inspect attachments for document %s in %s: %s",
                            itglue_id,
                            self.export_path,
                            e,
                        )
                if attachment_files:
                    raw_content = (
                        "_Attachment-only document imported from IT Glue. "
                        "The export did not include an HTML body; see attachments._"
                    )
                else:
                    result.skipped["documents"] = result.skipped.get("documents", 0) + 1
                    logger.debug(f"Skipping document '{doc_name}': empty content")
                    if self.reporter:
                        self.reporter.update_progress(skipped=1)
                        self.reporter.warning(f"Document '{doc_name}' has empty content")
                    continue

            if _is_content_empty(raw_content):
                result.skipped["documents"] = result.skipped.get("documents", 0) + 1
                logger.debug(f"Skipping document '{doc_name}': empty content")
                if self.reporter:
                    self.reporter.update_progress(skipped=1)
                    self.reporter.warning(f"Document '{doc_name}' has empty content")
                continue

            try:
                if self.dry_run:
                    result.created["documents"] = (
                        result.created.get("documents", 0) + 1
                    )
                    if self.reporter:
                        self.reporter.update_progress(succeeded=1)
                    continue

                # Get folder path from document_folder_map, fallback to CSV path/locator
                path = entity.get("path") or entity.get("locator") or "/"
                if self.doc_processor:
                    folder_info = self.doc_processor.document_folder_map.get(itglue_id)
                    if folder_info:
                        folder_path, _ = folder_info
                        path = folder_path

                # Process content through DocumentProcessor if available
                content = raw_content
                if self.doc_processor and content:
                    # Process HTML: clean, extract images, convert to markdown
                    processed_content, warnings = await self.doc_processor.process_document(
                        {"id": itglue_id, "name": doc_name},
                        org_uuid=self.org_id,
                    )
                    if processed_content:
                        content = processed_content
                    for warning in warnings:
                        logger.debug(f"Document {doc_name}: {warning}")
                elif content:
                    # Fallback: just ensure content is string
                    content = str(content) if content else ""

                # Build metadata
                metadata = entity.get("metadata") or {}
                if itglue_id and "itglue_id" not in metadata:
                    metadata["itglue_id"] = itglue_id

                # Handle archived -> is_enabled
                is_enabled = entity.get("is_enabled", True)
                archived = entity.get("archived")
                if archived is not None:
                    archived_str = str(archived).lower()
                    is_enabled = archived_str not in ("true", "1", "yes")

                response = await self.client.create_document(
                    org_id=self.org_id,
                    path=path,
                    name=doc_name,
                    content=content,
                    metadata=metadata,
                    is_enabled=is_enabled,
                )

                if skra_id := response.get("id"):
                    result.id_map[itglue_id] = skra_id

                    # Upload attachments
                    if self.doc_processor and self.export_path:
                        attachment_count = await self._upload_entity_attachments(
                            "documents", itglue_id, skra_id
                        )
                        if attachment_count > 0 and self.reporter:
                            self.reporter.info(f"Uploaded {attachment_count} attachments")

                result.created["documents"] = result.created.get("documents", 0) + 1
                if self.reporter:
                    disabled = 1 if not is_enabled else 0
                    self.reporter.update_progress(succeeded=1, disabled=disabled)

            except Exception as e:
                result.failed["documents"] = result.failed.get("documents", 0) + 1
                result.errors.append(f"Document '{doc_name}': {e}")
                logger.warning(f"Failed to create document: {e}")
                if self.reporter:
                    self.reporter.update_progress(failed=1)
                    self.reporter.error(f"Document '{doc_name}': {e}")

    async def _execute_passwords(self, plan: SyncPlan, result: SyncResult) -> None:
        """Execute password creation for regular passwords and row_creates.

        Handles CSV format and adds itglue_id to metadata.
        """
        # Regular passwords
        for entity in plan.passwords.to_create:
            name = entity.get("name", "Unnamed")

            if self.reporter:
                self.reporter.set_current_item(f"Password: {name}")

            # Check for empty password value
            password_value = entity.get("password", "")
            if not password_value:
                result.skipped["passwords"] = result.skipped.get("passwords", 0) + 1
                logger.warning(f"Skipping password '{name}': empty password value")
                if self.reporter:
                    self.reporter.update_progress(skipped=1)
                    self.reporter.warning(f"Password '{name}' has empty password value")
                continue

            try:
                itglue_id = str(entity.get("id", ""))

                if self.dry_run:
                    result.created["passwords"] = (
                        result.created.get("passwords", 0) + 1
                    )
                    if self.reporter:
                        self.reporter.update_progress(succeeded=1)
                    continue

                password = entity.get("password", "")

                # Build metadata with itglue_id
                metadata = entity.get("metadata") or {}
                if itglue_id and "itglue_id" not in metadata:
                    metadata["itglue_id"] = itglue_id

                # Handle archived -> is_enabled
                is_enabled = entity.get("is_enabled", True)
                archived = entity.get("archived")
                if archived is not None:
                    archived_str = str(archived).lower()
                    is_enabled = archived_str not in ("true", "1", "yes")

                response = await self.client.create_password(
                    org_id=self.org_id,
                    name=name,
                    password=password,
                    username=entity.get("username"),
                    totp_secret=entity.get("totp_secret") or entity.get("otp_secret"),
                    url=entity.get("url"),
                    notes=entity.get("notes"),
                    metadata=metadata,
                    is_enabled=is_enabled,
                )

                if skra_id := response.get("id"):
                    result.id_map[itglue_id] = skra_id

                    # Upload attachments
                    if self.doc_processor and self.export_path:
                        attachment_count = await self._upload_entity_attachments(
                            "passwords", itglue_id, skra_id
                        )
                        if attachment_count > 0 and self.reporter:
                            self.reporter.info(f"Uploaded {attachment_count} attachments")

                result.created["passwords"] = result.created.get("passwords", 0) + 1
                if self.reporter:
                    disabled = 1 if not is_enabled else 0
                    self.reporter.update_progress(succeeded=1, disabled=disabled)

            except Exception as e:
                result.failed["passwords"] = result.failed.get("passwords", 0) + 1
                result.errors.append(f"Password '{name}': {e}")
                logger.warning(f"Failed to create password: {e}")
                if self.reporter:
                    self.reporter.update_progress(failed=1)
                    self.reporter.error(f"Password '{name}': {e}")

        # Row passwords (::Row) - create password and relationship to custom asset
        existing_relationship_keys = self.state.relationships if self.state else set()
        for entity in plan.passwords.row_creates:
            try:
                itglue_id = str(entity.get("id", ""))
                resource_id = str(entity.get("resource_id", ""))
                relationship_entity = {
                    "source_type": "password",
                    "source_id": itglue_id,
                    "target_type": "custom_asset",
                    "target_id": resource_id,
                }
                target_uuid = (
                    self.state.custom_asset_by_itglue_id.get(resource_id)
                    if self.state and resource_id
                    else None
                )

                if self.dry_run:
                    result.created["passwords"] = (
                        result.created.get("passwords", 0) + 1
                    )
                    relationship_entity["target_id"] = target_uuid or ""
                    audit = classify_relationship(
                        relationship_entity,
                        existing_relationship_keys=existing_relationship_keys,
                    )
                    if target_uuid:
                        result.created["relationships"] = (
                            result.created.get("relationships", 0) + 1
                        )
                    else:
                        result.skipped["relationships"] = (
                            result.skipped.get("relationships", 0) + 1
                        )
                    result.relationship_audit.append(audit.to_dict())
                    continue

                name = entity.get("name", "Unnamed")
                password = entity.get("password", "")

                # Create the password
                response = await self.client.create_password(
                    org_id=self.org_id,
                    name=name,
                    password=password,
                    username=entity.get("username"),
                    totp_secret=entity.get("totp_secret") or entity.get("otp_secret"),
                    url=entity.get("url"),
                    notes=entity.get("notes"),
                    metadata={
                        "itglue_id": itglue_id,
                        "resource_type": entity.get("resource_type"),
                        "resource_id": resource_id,
                    },
                    is_enabled=entity.get("is_enabled", True),
                )

                password_uuid = response.get("id")
                if itglue_id and password_uuid:
                    result.id_map[itglue_id] = password_uuid

                result.created["passwords"] = result.created.get("passwords", 0) + 1

                # Create relationship to custom asset
                # Check id_map first (for assets created this run), then state (pre-existing)
                if password_uuid and resource_id:
                    target_uuid = result.id_map.get(resource_id)
                    if not target_uuid and self.state:
                        target_uuid = self.state.custom_asset_by_itglue_id.get(resource_id)
                    if target_uuid:
                        relationship_entity = {
                            "source_type": "password",
                            "source_id": password_uuid,
                            "target_type": "custom_asset",
                            "target_id": target_uuid,
                        }
                        try:
                            await self.client.create_relationship(
                                org_id=self.org_id,
                                source_type="password",
                                source_id=password_uuid,
                                target_type="custom_asset",
                                target_id=target_uuid,
                            )
                            result.created["relationships"] = (
                                result.created.get("relationships", 0) + 1
                            )
                            result.relationship_audit.append(
                                classify_relationship(
                                    relationship_entity,
                                    existing_relationship_keys=existing_relationship_keys,
                                ).to_dict()
                            )
                        except APIError as rel_err:
                            # 409 means relationship already exists - that's fine
                            if rel_err.status_code == 409:
                                result.skipped["relationships"] = (
                                    result.skipped.get("relationships", 0) + 1
                                )
                            else:
                                result.failed["relationships"] = (
                                    result.failed.get("relationships", 0) + 1
                                )
                                result.errors.append(
                                    f"Relationship for password '{name}' -> custom_asset: {rel_err}"
                                )
                                logger.warning(
                                    f"Failed to create relationship for row password: {rel_err}"
                                )
                            result.relationship_audit.append(
                                classify_relationship(
                                    relationship_entity,
                                    existing_relationship_keys=existing_relationship_keys,
                                    error=rel_err,
                                ).to_dict()
                            )
                        except Exception as rel_err:
                            result.failed["relationships"] = (
                                result.failed.get("relationships", 0) + 1
                            )
                            result.errors.append(
                                f"Relationship for password '{name}' -> custom_asset: {rel_err}"
                            )
                            logger.warning(
                                f"Failed to create relationship for row password: {rel_err}"
                            )
                            result.relationship_audit.append(
                                classify_relationship(
                                    relationship_entity,
                                    existing_relationship_keys=existing_relationship_keys,
                                    error=rel_err,
                                ).to_dict()
                            )
                    else:
                        result.skipped["relationships"] = (
                            result.skipped.get("relationships", 0) + 1
                        )
                        result.relationship_audit.append(
                            classify_relationship(
                                {
                                    "source_type": "password",
                                    "source_id": password_uuid,
                                    "target_type": "custom_asset",
                                    "target_id": "",
                                    "target_itglue_id": resource_id,
                                },
                                existing_relationship_keys=existing_relationship_keys,
                            ).to_dict()
                        )

            except Exception as e:
                result.failed["passwords"] = result.failed.get("passwords", 0) + 1
                result.errors.append(f"Password '{entity.get('name')}': {e}")
                logger.warning(f"Failed to create row password: {e}")

    async def _execute_config_types(self, plan: SyncPlan, result: SyncResult) -> None:
        """Execute configuration type creation."""
        for entity in plan.config_types.to_create:
            try:
                if self.dry_run:
                    result.created["config_types"] = (
                        result.created.get("config_types", 0) + 1
                    )
                    continue

                name = entity.get("name", "Unnamed")
                response = await self.client.create_configuration_type(name=name)

                itglue_id = str(entity.get("id", ""))
                if itglue_id and response.get("id"):
                    result.id_map[itglue_id] = response["id"]

                result.created["config_types"] = (
                    result.created.get("config_types", 0) + 1
                )

            except Exception as e:
                result.failed["config_types"] = (
                    result.failed.get("config_types", 0) + 1
                )
                result.errors.append(f"Config type '{entity.get('name')}': {e}")
                logger.warning(f"Failed to create configuration type: {e}")

    async def _execute_config_statuses(
        self, plan: SyncPlan, result: SyncResult
    ) -> None:
        """Execute configuration status creation."""
        for entity in plan.config_statuses.to_create:
            try:
                if self.dry_run:
                    result.created["config_statuses"] = (
                        result.created.get("config_statuses", 0) + 1
                    )
                    continue

                name = entity.get("name", "Unnamed")
                response = await self.client.create_configuration_status(name=name)

                itglue_id = str(entity.get("id", ""))
                if itglue_id and response.get("id"):
                    result.id_map[itglue_id] = response["id"]

                result.created["config_statuses"] = (
                    result.created.get("config_statuses", 0) + 1
                )

            except Exception as e:
                result.failed["config_statuses"] = (
                    result.failed.get("config_statuses", 0) + 1
                )
                result.errors.append(f"Config status '{entity.get('name')}': {e}")
                logger.warning(f"Failed to create configuration status: {e}")

    async def _execute_custom_asset_types(
        self, plan: SyncPlan, result: SyncResult
    ) -> None:
        """Execute custom asset type creation."""
        for entity in plan.custom_asset_types.to_create:
            try:
                if self.dry_run:
                    result.created["custom_asset_types"] = (
                        result.created.get("custom_asset_types", 0) + 1
                    )
                    continue

                name = entity.get("name", "Unnamed")
                fields = entity.get("fields", [])

                response = await self.client.create_custom_asset_type(
                    name=name,
                    fields=fields,
                    display_field_key=entity.get("display_field_key"),
                )

                itglue_id = str(entity.get("id", ""))
                new_type_id = response.get("id", "")

                if itglue_id and new_type_id:
                    result.id_map[itglue_id] = new_type_id

                # UPDATE STATE for subsequent custom asset lookups
                if self.state and new_type_id:
                    name_lower = name.lower()
                    self.state.custom_asset_type_by_name[name_lower] = new_type_id
                    self.state.custom_asset_types[new_type_id] = {
                        "id": new_type_id,
                        "name": name,
                        "fields": fields,
                    }

                result.created["custom_asset_types"] = (
                    result.created.get("custom_asset_types", 0) + 1
                )

            except Exception as e:
                result.failed["custom_asset_types"] = (
                    result.failed.get("custom_asset_types", 0) + 1
                )
                result.errors.append(f"Custom asset type '{entity.get('name')}': {e}")
                logger.warning(f"Failed to create custom asset type: {e}")

    def _coerce_field_value(
        self, value: Any, field_type: str
    ) -> Any:
        """Coerce a field value to the expected type.

        Args:
            value: The value from CSV (usually string)
            field_type: The field type from the type definition

        Returns:
            The value coerced to the appropriate type
        """
        if value is None:
            return None

        # Handle number type
        if field_type == "number":
            if isinstance(value, (int, float)):
                return value
            try:
                # Try to parse as number
                str_val = str(value).strip()
                if not str_val:
                    return None
                if "." in str_val:
                    return float(str_val)
                return int(str_val)
            except (ValueError, TypeError):
                return None

        # Handle checkbox (boolean) type
        if field_type == "checkbox":
            if isinstance(value, bool):
                return value
            str_val = str(value).strip().lower()
            if str_val in ("true", "yes", "1", "on"):
                return True
            if str_val in ("false", "no", "0", "off", ""):
                return False
            return bool(value)

        # Text, textbox, select, date - keep as string
        return value

    async def _execute_custom_assets(
        self, plan: SyncPlan, result: SyncResult
    ) -> None:
        """Execute custom asset creation.

        Handles CSV format: {id, organization_id, asset_type, _type_slug, fields}
        Transforms to API format: {type_id, values, metadata}

        Uses the custom asset type's field definitions to properly map
        CSV field names to API field keys, filter out unknown fields,
        and coerce values to the correct types.
        """
        for entity in plan.custom_assets.to_create:
            itglue_id = str(entity.get("id", ""))
            # Get display name from fields for progress display
            fields = entity.get("fields", {})
            display_name = fields.get("name") or fields.get("Name") or f"Asset {itglue_id}"

            if self.reporter:
                self.reporter.set_current_item(f"Custom Asset: {display_name}")

            try:
                if self.dry_run:
                    result.created["custom_assets"] = (
                        result.created.get("custom_assets", 0) + 1
                    )
                    if self.reporter:
                        self.reporter.update_progress(succeeded=1)
                    continue

                # Resolve type_id from asset_type or _type_slug
                type_id = entity.get("type_id", "")
                if not type_id and self.state:
                    type_slug = entity.get("asset_type") or entity.get("_type_slug", "")
                    if type_slug:
                        # Try slug first, then display name
                        type_id = self.state.custom_asset_type_by_name.get(type_slug.lower(), "")
                        if not type_id:
                            # Convert slug to display name: "ssl-certificates" -> "ssl certificates"
                            type_display_name = type_slug.replace("-", " ").replace("_", " ")
                            type_id = self.state.custom_asset_type_by_name.get(type_display_name.lower(), "")

                if not type_id:
                    result.skipped["custom_assets"] = (
                        result.skipped.get("custom_assets", 0) + 1
                    )
                    type_slug = entity.get("asset_type") or entity.get("_type_slug", "unknown")
                    logger.warning(
                        f"Skipping custom asset {itglue_id}: type '{type_slug}' not found"
                    )
                    if self.reporter:
                        self.reporter.update_progress(skipped=1)
                        self.reporter.warning(f"Custom asset {itglue_id}: type '{type_slug}' not found")
                    continue

                # Get type's field definitions to build field mappings
                # field_name.lower() -> {key: str, type: str}
                type_field_defs: dict[str, dict[str, str]] = {}
                valid_field_keys: set[str] = set()

                if self.state and type_id in self.state.custom_asset_types:
                    type_data = self.state.custom_asset_types[type_id]
                    for field_def in type_data.get("fields", []):
                        field_name = field_def.get("name", "").lower()
                        field_key = field_def.get("key", "")
                        field_type = field_def.get("type", "text")
                        if field_name and field_key:
                            type_field_defs[field_name] = {
                                "key": field_key,
                                "type": field_type,
                            }
                            valid_field_keys.add(field_key)
                        # Also index by generated key (for direct key lookups)
                        generated_key = (
                            field_name.replace(" ", "_")
                            .replace("-", "_")
                            .replace(".", "_")
                        )
                        if generated_key:
                            type_field_defs[generated_key] = {
                                "key": field_key,
                                "type": field_type,
                            }

                # Transform fields dict to values dict using actual API field keys
                values = entity.get("values", {})
                if not values and entity.get("fields"):
                    csv_fields = entity.get("fields", {})
                    values = {}
                    skipped_fields: list[str] = []

                    for field_name, field_value in csv_fields.items():
                        # Skip None values
                        if field_value is None:
                            continue

                        # Look up the actual API field key and type
                        field_name_lower = field_name.lower()
                        if field_name_lower in type_field_defs:
                            field_def = type_field_defs[field_name_lower]
                            field_key = field_def["key"]
                            field_type = field_def["type"]
                        else:
                            # Generate a key to check if it exists
                            generated_key = (
                                field_name.lower()
                                .replace(" ", "_")
                                .replace("-", "_")
                                .replace(".", "_")
                            )
                            # Only include if the generated key is a valid field
                            if valid_field_keys and generated_key not in valid_field_keys:
                                skipped_fields.append(field_name)
                                continue
                            field_key = generated_key
                            field_type = "text"

                        # Coerce the value to the expected type
                        coerced_value = self._coerce_field_value(field_value, field_type)
                        if coerced_value is not None:
                            values[field_key] = coerced_value

                    if skipped_fields:
                        logger.debug(
                            f"Custom asset {itglue_id}: skipped unknown fields: {skipped_fields}"
                        )

                # Handle archived -> is_enabled AND archived field value
                # The CSV parser puts "archived" at top-level (for is_enabled)
                # but the type may also have an "archived" field that needs a value
                is_enabled = entity.get("is_enabled", True)
                archived = entity.get("archived")
                if archived is not None:
                    archived_str = str(archived).lower()
                    is_enabled = archived_str not in ("true", "1", "yes")

                    # If type has "archived" field, include it in values
                    if "archived" in type_field_defs:
                        field_def = type_field_defs["archived"]
                        field_key = field_def["key"]
                        field_type = field_def["type"]
                        coerced_archived = self._coerce_field_value(archived, field_type)
                        if coerced_archived is not None and field_key not in values:
                            values[field_key] = coerced_archived

                # Build metadata with itglue_id
                metadata = entity.get("metadata") or {}
                if itglue_id and "itglue_id" not in metadata:
                    metadata["itglue_id"] = itglue_id

                response = await self.client.create_custom_asset(
                    org_id=self.org_id,
                    type_id=type_id,
                    values=values,
                    metadata=metadata,
                    is_enabled=is_enabled,
                )

                if skra_id := response.get("id"):
                    result.id_map[itglue_id] = skra_id
                    # Track type_id for cell writes
                    result.asset_type_map[itglue_id] = type_id

                    # Upload attachments
                    # For custom assets, use the asset_type slug as entity_type
                    if self.doc_processor and self.export_path:
                        asset_type_slug = entity.get("asset_type") or entity.get("_type_slug", "")
                        if asset_type_slug:
                            attachment_count = await self._upload_entity_attachments(
                                asset_type_slug, itglue_id, skra_id
                            )
                            if attachment_count > 0 and self.reporter:
                                self.reporter.info(f"Uploaded {attachment_count} attachments")

                result.created["custom_assets"] = (
                    result.created.get("custom_assets", 0) + 1
                )
                if self.reporter:
                    disabled = 1 if not is_enabled else 0
                    self.reporter.update_progress(succeeded=1, disabled=disabled)

            except Exception as e:
                result.failed["custom_assets"] = (
                    result.failed.get("custom_assets", 0) + 1
                )
                result.errors.append(f"Custom asset '{itglue_id}': {e}")
                logger.warning(f"Failed to create custom asset: {e}")
                if self.reporter:
                    self.reporter.update_progress(failed=1)
                    self.reporter.error(f"Custom asset '{itglue_id}': {e}")

    async def _execute_cell_writes(
        self, plan: SyncPlan, result: SyncResult
    ) -> None:
        """Execute cell writes - update custom asset fields with password values.

        For passwords with resource_type containing "StructuredData::Cell",
        the password value should be written into the custom asset field.

        The resource_id points to the custom asset's ITGlue ID.
        The field to update is determined from the password name or metadata.
        """
        if not self.state:
            # Cannot process cell writes without state for lookups
            if plan.passwords.cell_writes:
                logger.warning(
                    f"Skipping {len(plan.passwords.cell_writes)} cell_writes: "
                    "no state provided for lookups"
                )
                result.skipped["cell_writes"] = (
                    result.skipped.get("cell_writes", 0)
                    + len(plan.passwords.cell_writes)
                )
            return

        # Track skipped cell writes for summary logging
        skipped_not_in_org: list[str] = []

        for entity in plan.passwords.cell_writes:
            try:
                resource_id = str(entity.get("resource_id", ""))
                password_value = entity.get("password", "")
                password_name = entity.get("name", "")

                if self.dry_run:
                    result.created["cell_writes"] = (
                        result.created.get("cell_writes", 0) + 1
                    )
                    continue

                # Look up the custom asset UUID from ITGlue resource_id
                # Check result.id_map first (assets created this sync run)
                # Then fall back to state (assets that already existed)
                asset_uuid = result.id_map.get(resource_id)
                if not asset_uuid:
                    asset_uuid = self.state.custom_asset_by_itglue_id.get(resource_id)
                if not asset_uuid:
                    result.skipped["cell_writes"] = (
                        result.skipped.get("cell_writes", 0) + 1
                    )
                    # Track for summary - likely a cross-org reference
                    skipped_not_in_org.append(resource_id)
                    logger.debug(
                        f"Cell write skipped: custom asset {resource_id} not in "
                        "synced org (likely cross-org reference)"
                    )
                    continue

                # Get type_id - check asset_type_map first (newly created assets)
                # then fall back to state (existing assets)
                type_id = result.asset_type_map.get(resource_id, "")
                if not type_id:
                    asset_data = self.state.custom_assets.get(asset_uuid)
                    if asset_data:
                        type_id = asset_data.get("type_id", "")
                if not type_id:
                    result.skipped["cell_writes"] = (
                        result.skipped.get("cell_writes", 0) + 1
                    )
                    logger.warning(
                        f"Cell write skipped: type_id not found for asset {asset_uuid}"
                    )
                    continue

                # Determine which field to update based on password name
                # The password name typically matches the field name in IT Glue
                # We use the password name as the field key
                field_key = password_name

                # Update the custom asset with the password value
                await self.client.update_custom_asset(
                    org_id=self.org_id,
                    type_id=type_id,
                    asset_id=asset_uuid,
                    values={field_key: password_value},
                )

                result.created["cell_writes"] = (
                    result.created.get("cell_writes", 0) + 1
                )

            except Exception as e:
                result.failed["cell_writes"] = (
                    result.failed.get("cell_writes", 0) + 1
                )
                result.errors.append(
                    f"Cell write for '{entity.get('name')}' "
                    f"(resource_id={entity.get('resource_id')}): {e}"
                )
                logger.warning(f"Failed to execute cell write: {e}")

        # Log summary of skipped cell writes (cross-org references are common)
        if skipped_not_in_org:
            logger.info(
                f"Skipped {len(skipped_not_in_org)} cell writes: target assets not "
                "in synced org (likely cross-org references to unsynced orgs)"
            )

    async def _execute_relationships(
        self, plan: SyncPlan, result: SyncResult
    ) -> None:
        """Execute relationship creation.

        Resolves ITGlue IDs to UUIDs using:
        1. result.id_map - entities created in this sync run
        2. self.state lookups - entities that already existed
        """
        audit_results: list[RelationshipAuditResult] = []
        existing_relationship_keys = self.state.relationships if self.state else set()
        # Run-local view of known links, seeded from the pre-run fetch. Keys
        # created (or 409-confirmed) during this run are added so repeats and
        # resume retries short-circuit without another POST.
        seen_keys = set(existing_relationship_keys)

        for entity in plan.relationships.to_create:
            source_id = entity.get("source_id", "")
            target_id = entity.get("target_id", "")
            try:
                # Resolve source_id - prefer id_map (newly created) over pre-filled
                source_itglue_id = entity.get("source_itglue_id", "")
                # Prefer id_map (newly created entities) over pre-filled source_id
                if source_itglue_id and source_itglue_id in result.id_map:
                    source_id = result.id_map[source_itglue_id]
                elif not source_id and source_itglue_id and self.state:
                    # Fall back to state lookup (entity already existed)
                    source_type = entity.get("source_type", "")
                    if source_type == "password":
                        source_id = self.state.password_by_itglue_id.get(
                            source_itglue_id, ""
                        )

                # Resolve target_id - prefer id_map (newly created) over pre-filled
                target_itglue_id = entity.get("target_itglue_id", "")
                # Prefer id_map (newly created entities) over pre-filled target_id
                if target_itglue_id and target_itglue_id in result.id_map:
                    target_id = result.id_map[target_itglue_id]
                elif not target_id and target_itglue_id and self.state:
                    # Fall back to state lookup (entity already existed)
                    target_type = entity.get("target_type", "")
                    if target_type == "configuration":
                        target_id = self.state.config_by_itglue_id.get(
                            target_itglue_id, ""
                        )
                    elif target_type == "location":
                        target_id = self.state.location_by_itglue_id.get(
                            target_itglue_id, ""
                        )
                    elif target_type == "document":
                        target_id = self.state.document_by_itglue_id.get(
                            target_itglue_id, ""
                        )
                    elif target_type == "custom_asset":
                        target_id = self.state.custom_asset_by_itglue_id.get(
                            target_itglue_id, ""
                        )

                resolved_entity = {
                    **entity,
                    "source_id": source_id,
                    "target_id": target_id,
                }
                preflight_audit = classify_relationship(
                    resolved_entity,
                    existing_relationship_keys=seen_keys,
                )

                if preflight_audit.status.value == "duplicate_existing":
                    result.skipped["relationships"] = (
                        result.skipped.get("relationships", 0) + 1
                    )
                    audit_results.append(preflight_audit)
                    continue

                # Skip if we couldn't resolve both IDs
                if not source_id or not target_id:
                    result.skipped["relationships"] = (
                        result.skipped.get("relationships", 0) + 1
                    )
                    source_desc = source_id or f"itglue:{source_itglue_id}"
                    target_desc = target_id or f"itglue:{target_itglue_id}"
                    missing_side = (
                        f"source {entity.get('source_type', '')} ({source_desc})"
                        if not source_id
                        else f"target {entity.get('target_type', '')} ({target_desc})"
                    )
                    skip_audit = classify_relationship(
                        resolved_entity,
                        existing_relationship_keys=seen_keys,
                        reason=(
                            f"could not resolve {missing_side}; sync the "
                            f"{'source' if not source_id else 'target'} entity "
                            f"first (link {source_desc} -> {target_desc}), then "
                            "re-run relationship sync"
                        ),
                    )
                    audit_results.append(skip_audit)
                    logger.warning(
                        f"Skipping relationship: {skip_audit.reason}"
                    )
                    continue

                if self.dry_run:
                    result.created["relationships"] = (
                        result.created.get("relationships", 0) + 1
                    )
                    audit_results.append(preflight_audit)
                    continue

                await self.client.create_relationship(
                    org_id=self.org_id,
                    source_type=entity.get("source_type", ""),
                    source_id=source_id,
                    target_type=entity.get("target_type", ""),
                    target_id=target_id,
                )

                result.created["relationships"] = (
                    result.created.get("relationships", 0) + 1
                )
                if preflight_audit.relationship_key:
                    seen_keys.add(preflight_audit.relationship_key)
                audit_results.append(preflight_audit)

            except APIError as e:
                # 409 means relationship already exists - that's fine
                resolved_entity = {
                    **entity,
                    "source_id": source_id,
                    "target_id": target_id,
                }
                audit = classify_relationship(
                    resolved_entity,
                    existing_relationship_keys=seen_keys,
                    error=e,
                )
                audit_results.append(audit)
                if e.status_code == 409:
                    result.skipped["relationships"] = (
                        result.skipped.get("relationships", 0) + 1
                    )
                    if audit.relationship_key:
                        seen_keys.add(audit.relationship_key)
                else:
                    result.failed["relationships"] = (
                        result.failed.get("relationships", 0) + 1
                    )
                    source = entity.get("source_id") or entity.get("source_itglue_id", "?")
                    target = entity.get("target_id") or entity.get("target_itglue_id", "?")
                    result.errors.append(f"Relationship '{source}' -> '{target}': {e}")
                    logger.warning(f"Failed to create relationship: {e}")
            except Exception as e:
                resolved_entity = {
                    **entity,
                    "source_id": source_id,
                    "target_id": target_id,
                }
                audit_results.append(
                    classify_relationship(
                        resolved_entity,
                        existing_relationship_keys=seen_keys,
                        error=e,
                    )
                )
                result.failed["relationships"] = (
                    result.failed.get("relationships", 0) + 1
                )
                source = entity.get("source_id") or entity.get("source_itglue_id", "?")
                target = entity.get("target_id") or entity.get("target_itglue_id", "?")
                result.errors.append(f"Relationship '{source}' -> '{target}': {e}")
                logger.warning(f"Failed to create relationship: {e}")

        result.relationship_audit.extend(audit.to_dict() for audit in audit_results)
        result.relationship_summary = summarize_relationship_audit(
            result.relationship_audit
        )

    async def _execute_configuration_updates(
        self, plan: SyncPlan, result: SyncResult
    ) -> None:
        """Execute configuration updates for existing entities with changes."""
        for entity in plan.configurations.to_update:
            try:
                uuid = entity.get("uuid", "")
                changes = entity.get("changes", {})

                if self.dry_run:
                    result.updated["configurations"] = (
                        result.updated.get("configurations", 0) + 1
                    )
                    continue

                await self.client.update_configuration(
                    org_id=self.org_id,
                    config_id=uuid,
                    **changes,
                )

                result.updated["configurations"] = (
                    result.updated.get("configurations", 0) + 1
                )
                logger.info(
                    f"Updated configuration {uuid} with changes: {list(changes.keys())}"
                )

            except Exception as e:
                result.failed["configurations"] = (
                    result.failed.get("configurations", 0) + 1
                )
                itglue_id = entity.get("itglue_id", "?")
                result.errors.append(f"Configuration update '{itglue_id}': {e}")
                logger.warning(f"Failed to update configuration: {e}")

    async def _execute_location_updates(
        self, plan: SyncPlan, result: SyncResult
    ) -> None:
        """Execute location updates for existing entities with changes."""
        for entity in plan.locations.to_update:
            try:
                uuid = entity.get("uuid", "")
                changes = entity.get("changes", {})

                if self.dry_run:
                    result.updated["locations"] = (
                        result.updated.get("locations", 0) + 1
                    )
                    continue

                await self.client.update_location(
                    org_id=self.org_id,
                    location_id=uuid,
                    **changes,
                )

                result.updated["locations"] = (
                    result.updated.get("locations", 0) + 1
                )
                logger.info(
                    f"Updated location {uuid} with changes: {list(changes.keys())}"
                )

            except Exception as e:
                result.failed["locations"] = (
                    result.failed.get("locations", 0) + 1
                )
                itglue_id = entity.get("itglue_id", "?")
                result.errors.append(f"Location update '{itglue_id}': {e}")
                logger.warning(f"Failed to update location: {e}")

    async def _execute_document_updates(
        self, plan: SyncPlan, result: SyncResult
    ) -> None:
        """Execute document updates for existing entities with changes."""
        for entity in plan.documents.to_update:
            try:
                uuid = entity.get("uuid", "")
                changes = entity.get("changes", {})

                if self.dry_run:
                    result.updated["documents"] = (
                        result.updated.get("documents", 0) + 1
                    )
                    continue

                await self.client.update_document(
                    org_id=self.org_id,
                    doc_id=uuid,
                    **changes,
                )

                result.updated["documents"] = (
                    result.updated.get("documents", 0) + 1
                )
                logger.info(
                    f"Updated document {uuid} with changes: {list(changes.keys())}"
                )

            except Exception as e:
                result.failed["documents"] = (
                    result.failed.get("documents", 0) + 1
                )
                itglue_id = entity.get("itglue_id", "?")
                result.errors.append(f"Document update '{itglue_id}': {e}")
                logger.warning(f"Failed to update document: {e}")

    async def _execute_password_updates(
        self, plan: SyncPlan, result: SyncResult
    ) -> None:
        """Execute password updates for existing entities with changes."""
        for entity in plan.passwords.to_update:
            try:
                uuid = entity.get("uuid", "")
                changes = entity.get("changes", {})

                if self.dry_run:
                    result.updated["passwords"] = (
                        result.updated.get("passwords", 0) + 1
                    )
                    continue

                await self.client.update_password(
                    org_id=self.org_id,
                    password_id=uuid,
                    **changes,
                )

                result.updated["passwords"] = (
                    result.updated.get("passwords", 0) + 1
                )
                logger.info(
                    f"Updated password {uuid} with changes: {list(changes.keys())}"
                )

            except Exception as e:
                result.failed["passwords"] = (
                    result.failed.get("passwords", 0) + 1
                )
                itglue_id = entity.get("itglue_id", "?")
                result.errors.append(f"Password update '{itglue_id}': {e}")
                logger.warning(f"Failed to update password: {e}")
