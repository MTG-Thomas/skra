"""Sync differ module for comparing local and remote state.

This module provides dataclasses used by both the differ and executor
to represent sync plans.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from itglue_migrate.csv_parser import slugify_to_display_name
from itglue_migrate.field_inference import column_name_to_key

if TYPE_CHECKING:
    from itglue_migrate.state_fetcher import ExistingState


# Fields to compare for each entity type when checking for updates
CONFIGURATION_COMPARE_FIELDS = (
    "name",
    "serial_number",
    "asset_tag",
    "manufacturer",
    "model",
    "ip_address",
    "mac_address",
    "notes",
)

LOCATION_COMPARE_FIELDS = (
    "name",
    "address_1",
    "address_2",
    "city",
    "region",
    "postal_code",
    "country",
    "phone",
    "notes",
)

DOCUMENT_COMPARE_FIELDS = (
    "name",
    "content",
    "path",
)

PASSWORD_COMPARE_FIELDS = (
    "name",
    "username",
    "url",
    "notes",
    # Note: password value itself cannot be compared as API doesn't return it
)


@dataclass
class EntityPlan:
    """Plan for a single entity type."""

    to_create: list[dict[str, Any]] = field(default_factory=list)
    to_update: list[dict[str, Any]] = field(default_factory=list)
    existing: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RelationshipPlan:
    """Plan for relationships."""

    to_create: list[dict[str, Any]] = field(default_factory=list)
    existing: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PasswordPlan:
    """Plan for passwords with embedded password support."""

    to_create: list[dict[str, Any]] = field(default_factory=list)
    to_update: list[dict[str, Any]] = field(default_factory=list)
    existing: list[dict[str, Any]] = field(default_factory=list)
    # For embedded passwords in custom assets
    cell_writes: list[dict[str, Any]] = field(default_factory=list)
    row_creates: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SyncPlan:
    """Complete sync plan for all entity types."""

    organizations: EntityPlan = field(default_factory=EntityPlan)
    config_types: EntityPlan = field(default_factory=EntityPlan)
    config_statuses: EntityPlan = field(default_factory=EntityPlan)
    custom_asset_types: EntityPlan = field(default_factory=EntityPlan)
    locations: EntityPlan = field(default_factory=EntityPlan)
    configurations: EntityPlan = field(default_factory=EntityPlan)
    custom_assets: EntityPlan = field(default_factory=EntityPlan)
    documents: EntityPlan = field(default_factory=EntityPlan)
    passwords: PasswordPlan = field(default_factory=PasswordPlan)
    relationships: RelationshipPlan = field(default_factory=RelationshipPlan)
    validation_warnings: list[str] = field(default_factory=list)


def _normalize_value(value: Any) -> str:
    """Normalize a value for comparison.

    Converts to string and strips whitespace. Returns empty string for None.
    """
    if value is None:
        return ""
    return str(value).strip()


def _compare_fields(
    csv_entity: dict[str, Any],
    existing_entity: dict[str, Any],
    fields: tuple[str, ...],
) -> dict[str, Any]:
    """Compare fields between CSV and existing entity.

    Args:
        csv_entity: Entity data from CSV export.
        existing_entity: Entity data from API.
        fields: Tuple of field names to compare.

    Returns:
        Dict of changed fields with their new values (from CSV).
        Empty dict if no changes detected.
    """
    changes: dict[str, Any] = {}

    for field_name in fields:
        csv_value = _normalize_value(csv_entity.get(field_name))
        existing_value = _normalize_value(existing_entity.get(field_name))

        if csv_value != existing_value:
            # Use original CSV value (not normalized) for the update
            changes[field_name] = csv_entity.get(field_name)

    return changes


class SyncDiffer:
    """Compares CSV data against API state to produce sync plan.

    This class compares parsed CSV export data against the existing
    state fetched from the API and produces a plan of what needs to
    be created, updated, or skipped.
    """

    def __init__(self, state: ExistingState) -> None:
        """Initialize the differ with existing API state.

        Args:
            state: ExistingState containing current API entity lookups.
        """
        self.state = state

    def diff_organizations(self, csv_orgs: list[dict[str, Any]]) -> EntityPlan:
        """Diff organizations - identify which need to be created.

        Args:
            csv_orgs: List of organization dicts from CSV export containing
                     'id' (ITGlue org ID) and 'name' fields.

        Returns:
            EntityPlan with to_create, existing, and skipped lists populated.
            Duplicate names (case-insensitive) are added to skipped.
        """
        plan = EntityPlan()
        seen_names: set[str] = set()

        for org in csv_orgs:
            org_name = org.get("name", "")
            itglue_id = str(org.get("id", ""))

            if not org_name:
                continue

            # Check for duplicates (case-insensitive)
            name_lower = org_name.lower()
            if name_lower in seen_names:
                plan.skipped.append({
                    "name": org_name,
                    "itglue_id": itglue_id,
                    "reason": "duplicate_name",
                })
                continue
            seen_names.add(name_lower)

            # Check if org exists by itglue_id in metadata
            existing_uuid = self.state.org_by_itglue_id.get(itglue_id)
            if not existing_uuid:
                # Also check by name as fallback
                existing_uuid = self.state.org_by_name.get(org_name.lower())

            if existing_uuid:
                plan.existing.append({
                    "name": org_name,
                    "id": existing_uuid,
                    "itglue_id": itglue_id,
                })
            else:
                plan.to_create.append({
                    "name": org_name,
                    "metadata": {"itglue_id": itglue_id},
                })

        return plan

    def diff_configurations(self, csv_configs: list[dict[str, Any]]) -> EntityPlan:
        """Diff configurations between CSV and API state.

        Args:
            csv_configs: List of configuration dicts from CSV export.

        Returns:
            EntityPlan with to_create, to_update, and existing lists populated.
        """
        plan = EntityPlan()

        for config in csv_configs:
            itglue_id = str(config.get("id", ""))
            if not itglue_id:
                continue

            if itglue_id in self.state.config_by_itglue_id:
                # Entity exists - check if it needs updating
                uuid = self.state.config_by_itglue_id[itglue_id]
                existing = self.state.configs.get(uuid, {})

                changes = _compare_fields(
                    config, existing, CONFIGURATION_COMPARE_FIELDS
                )

                if changes:
                    plan.to_update.append({
                        "itglue_id": itglue_id,
                        "uuid": uuid,
                        "changes": changes,
                        "csv_data": config,
                    })
                else:
                    plan.existing.append(config)
            else:
                plan.to_create.append(config)

        return plan

    def diff_locations(self, csv_locations: list[dict[str, Any]]) -> EntityPlan:
        """Diff locations between CSV and API state.

        Args:
            csv_locations: List of location dicts from CSV export.

        Returns:
            EntityPlan with to_create, to_update, and existing lists populated.
        """
        plan = EntityPlan()

        for location in csv_locations:
            itglue_id = str(location.get("id", ""))
            if not itglue_id:
                continue

            if itglue_id in self.state.location_by_itglue_id:
                # Entity exists - check if it needs updating
                uuid = self.state.location_by_itglue_id[itglue_id]
                existing = self.state.locations.get(uuid, {})

                changes = _compare_fields(
                    location, existing, LOCATION_COMPARE_FIELDS
                )

                if changes:
                    plan.to_update.append({
                        "itglue_id": itglue_id,
                        "uuid": uuid,
                        "changes": changes,
                        "csv_data": location,
                    })
                else:
                    plan.existing.append(location)
            else:
                plan.to_create.append(location)

        return plan

    def diff_documents(self, csv_documents: list[dict[str, Any]]) -> EntityPlan:
        """Diff documents between CSV and API state.

        Args:
            csv_documents: List of document dicts from CSV export.

        Returns:
            EntityPlan with to_create, to_update, existing, and skipped lists populated.
            Duplicate names within the same organization are added to skipped.
        """
        plan = EntityPlan()
        # Track seen doc names per organization: org_id -> set of doc names (lowercase)
        seen_docs: dict[str, set[str]] = {}

        for doc in csv_documents:
            itglue_id = str(doc.get("id", ""))
            if not itglue_id:
                continue

            doc_name = doc.get("name", "")
            org_id = str(doc.get("organization_id", ""))

            # Check for duplicates within same organization (case-insensitive)
            if doc_name:
                doc_name_lower = doc_name.lower()
                if org_id in seen_docs and doc_name_lower in seen_docs[org_id]:
                    plan.skipped.append({
                        "name": doc_name,
                        "itglue_id": itglue_id,
                        "organization_id": org_id,
                        "reason": "duplicate_name",
                    })
                    continue
                seen_docs.setdefault(org_id, set()).add(doc_name_lower)

            if itglue_id in self.state.document_by_itglue_id:
                # Entity exists - check if it needs updating
                uuid = self.state.document_by_itglue_id[itglue_id]
                existing = self.state.documents.get(uuid, {})

                changes = _compare_fields(doc, existing, DOCUMENT_COMPARE_FIELDS)

                if changes:
                    plan.to_update.append({
                        "itglue_id": itglue_id,
                        "uuid": uuid,
                        "changes": changes,
                        "csv_data": doc,
                    })
                else:
                    plan.existing.append(doc)
            else:
                plan.to_create.append(doc)

        return plan

    def diff_passwords(self, csv_passwords: list[dict[str, Any]]) -> PasswordPlan:
        """Diff passwords, handling ::Cell and ::Row specially.

        ::Cell passwords are stored in custom asset fields (cell_writes).
        ::Row passwords create password + relationship (row_creates).
        Regular passwords go to to_create, to_update, or existing.

        Args:
            csv_passwords: List of password dicts from CSV export.

        Returns:
            PasswordPlan with appropriate lists populated.
        """
        plan = PasswordPlan()

        for pwd in csv_passwords:
            itglue_id = str(pwd.get("id", ""))
            if not itglue_id:
                continue

            resource_type = (pwd.get("resource_type") or "").lower()

            # Handle ::Cell - write to custom asset field
            if "structureddata::cell" in resource_type:
                plan.cell_writes.append(pwd)
                continue

            # Handle ::Row - create password + relationship
            if "structureddata::row" in resource_type:
                if itglue_id not in self.state.password_by_itglue_id:
                    plan.row_creates.append(pwd)
                else:
                    plan.existing.append(pwd)
                continue

            # Regular password
            if itglue_id in self.state.password_by_itglue_id:
                # Entity exists - check if it needs updating
                uuid = self.state.password_by_itglue_id[itglue_id]
                existing = self.state.passwords.get(uuid, {})

                changes = _compare_fields(pwd, existing, PASSWORD_COMPARE_FIELDS)

                # Always include password value in changes if CSV has one
                # (we can't compare since API doesn't return it)
                csv_password = pwd.get("password")
                if csv_password:
                    changes["password"] = csv_password

                if changes:
                    plan.to_update.append({
                        "itglue_id": itglue_id,
                        "uuid": uuid,
                        "changes": changes,
                        "csv_data": pwd,
                    })
                else:
                    plan.existing.append(pwd)
            else:
                plan.to_create.append(pwd)

        return plan

    def diff_custom_assets(self, csv_assets: list[dict[str, Any]]) -> EntityPlan:
        """Diff custom assets between CSV and API state.

        Args:
            csv_assets: List of custom asset dicts from CSV export.

        Returns:
            EntityPlan with to_create and existing lists populated.
        """
        plan = EntityPlan()

        for asset in csv_assets:
            itglue_id = str(asset.get("id", ""))
            if not itglue_id:
                continue

            if itglue_id in self.state.custom_asset_by_itglue_id:
                plan.existing.append(asset)
            else:
                plan.to_create.append(asset)

        return plan

    def diff_config_types(self, csv_configs: list[dict[str, Any]]) -> EntityPlan:
        """Extract unique config types and diff against existing.

        Args:
            csv_configs: List of configuration dicts containing
                         'configuration_type' field.

        Returns:
            EntityPlan with unique types in to_create or existing.
        """
        plan = EntityPlan()
        seen: set[str] = set()

        for config in csv_configs:
            type_name = config.get("configuration_type")
            if not type_name or type_name.lower() in seen:
                continue
            seen.add(type_name.lower())

            if type_name.lower() in self.state.config_type_by_name:
                plan.existing.append({"name": type_name})
            else:
                plan.to_create.append({"name": type_name})

        return plan

    def diff_config_statuses(self, csv_configs: list[dict[str, Any]]) -> EntityPlan:
        """Extract unique config statuses and diff against existing.

        Args:
            csv_configs: List of configuration dicts containing
                         'configuration_status' field.

        Returns:
            EntityPlan with unique statuses in to_create or existing.
        """
        plan = EntityPlan()
        seen: set[str] = set()

        for config in csv_configs:
            status_name = config.get("configuration_status")
            if not status_name or status_name.lower() in seen:
                continue
            seen.add(status_name.lower())

            if status_name.lower() in self.state.config_status_by_name:
                plan.existing.append({"name": status_name})
            else:
                plan.to_create.append({"name": status_name})

        return plan

    def diff_custom_asset_types(
        self,
        csv_assets: list[dict[str, Any]],
        field_definitions: dict[str, list[dict[str, Any]]] | None = None,
    ) -> EntityPlan:
        """Extract unique custom asset types and diff against existing.

        Args:
            csv_assets: List of custom asset dicts containing
                        'asset_type' or '_type_slug' field.
            field_definitions: Optional dict mapping type slug to list of
                              field definition dicts (in CSV column order).

        Returns:
            EntityPlan with unique types in to_create or existing.
            For to_create, includes 'fields' list with properly ordered
            field definitions for API creation.
        """
        plan = EntityPlan()
        seen: set[str] = set()
        field_definitions = field_definitions or {}

        for asset in csv_assets:
            # Custom assets have 'asset_type' or '_type_slug' (slug format)
            type_slug = asset.get("asset_type") or asset.get("_type_slug")
            if not type_slug:
                continue

            # Convert slug to display name for comparison with API
            # CSV: "active-directory" -> API: "active directory"
            display_name = slugify_to_display_name(type_slug)

            if display_name.lower() in seen:
                continue
            seen.add(display_name.lower())

            if display_name.lower() in self.state.custom_asset_type_by_name:
                plan.existing.append({"name": display_name, "slug": type_slug})
            else:
                # Build fields list from field definitions (preserves CSV order)
                raw_fields = field_definitions.get(type_slug, [])
                fields = []
                for i, fd in enumerate(raw_fields):
                    field_name = fd.get("name", "")
                    field_key = column_name_to_key(field_name)
                    fields.append({
                        "key": field_key,
                        "name": field_name,
                        "type": fd.get("field_type", "text"),
                        "required": fd.get("required", False),
                        "show_in_list": i < 3,  # Show first 3 columns in list
                    })

                # Set display_field_key to first field if available
                display_field_key = fields[0]["key"] if fields else None

                plan.to_create.append({
                    "name": display_name,
                    "slug": type_slug,
                    "fields": fields,
                    "display_field_key": display_field_key,
                })

        return plan

    def diff_relationships(self, csv_passwords: list[dict[str, Any]]) -> RelationshipPlan:
        """Identify relationships to create from password resource links.

        Examines password resource_type and resource_id fields to determine
        what relationships should be created between passwords and their
        target entities (configurations, locations, documents, custom assets).

        Args:
            csv_passwords: List of password dicts with resource_type and
                          resource_id fields.

        Returns:
            RelationshipPlan with to_create and existing lists.
        """
        plan = RelationshipPlan()

        for pwd in csv_passwords:
            resource_type = (pwd.get("resource_type") or "").lower()
            resource_id = str(pwd.get("resource_id") or "")
            itglue_id = str(pwd.get("id", ""))

            if not resource_type or not resource_id:
                continue

            # Skip ::Cell - handled separately (stored in custom asset fields)
            if "structureddata::cell" in resource_type:
                continue

            # Check if password exists or will be created
            password_uuid = self.state.password_by_itglue_id.get(itglue_id)
            password_will_be_created = password_uuid is None

            # Determine target type and check if target exists
            target_type: str | None = None
            target_uuid: str | None = None

            if resource_type == "configuration":
                target_type = "configuration"
                target_uuid = self.state.config_by_itglue_id.get(resource_id)
            elif resource_type == "location":
                target_type = "location"
                target_uuid = self.state.location_by_itglue_id.get(resource_id)
            elif resource_type == "document":
                target_type = "document"
                target_uuid = self.state.document_by_itglue_id.get(resource_id)
            elif "structureddata" in resource_type:
                # ::Row points to custom asset
                target_type = "custom_asset"
                target_uuid = self.state.custom_asset_by_itglue_id.get(resource_id)

            # Skip if we can't determine target type
            if not target_type:
                continue

            # If password will be created, relationship will also be created
            # (can't check existing relationships without password UUID)
            if password_will_be_created:
                plan.to_create.append({
                    "source_type": "password",
                    "source_itglue_id": itglue_id,  # Store ITGlue ID for later resolution
                    "target_type": target_type,
                    "target_itglue_id": resource_id,  # Store ITGlue ID for later resolution
                    "target_id": target_uuid,  # May be None if target also being created
                })
                continue

            # Password exists - check if relationship already exists
            rel_key = f"password:{password_uuid}:{target_type}:{target_uuid}"
            if target_uuid and rel_key in self.state.relationships:
                plan.existing.append({
                    "source_type": "password",
                    "source_id": password_uuid,
                    "target_type": target_type,
                    "target_id": target_uuid,
                })
            else:
                plan.to_create.append({
                    "source_type": "password",
                    "source_id": password_uuid,
                    "source_itglue_id": itglue_id,
                    "target_type": target_type,
                    "target_itglue_id": resource_id,
                    "target_id": target_uuid,
                })

        return plan

    def validate_data_quality(
        self,
        csv_orgs: list[dict[str, Any]],
        csv_docs: list[dict[str, Any]],
        csv_passwords: list[dict[str, Any]],
    ) -> list[str]:
        """Check data quality and return warnings.

        This method performs pre-sync validation to detect common data quality
        issues that may affect the import. It does not prevent the sync, but
        provides warnings to help users understand potential problems.

        Args:
            csv_orgs: List of organization dicts from CSV export.
            csv_docs: List of document dicts from CSV export.
            csv_passwords: List of password dicts from CSV export.

        Returns:
            List of warning messages describing data quality issues found.
        """
        warnings: list[str] = []

        # Check for duplicate org names (case-insensitive)
        org_names = [o.get("name", "").lower() for o in csv_orgs if o.get("name")]
        duplicate_count = sum(count > 1 for count in Counter(org_names).values())
        if duplicate_count:
            warnings.append(f"Found {duplicate_count} duplicate organization names")

        # Check for empty passwords
        empty_pwds = [p for p in csv_passwords if not p.get("password")]
        if empty_pwds:
            warnings.append(f"Found {len(empty_pwds)} passwords with empty values")

        # Check for empty documents (HTML content that strips to empty)
        def is_empty_content(content: str | None) -> bool:
            if not content:
                return True

            # Match the previous simple tag-stripping behavior in one pass.
            # A regex beginning with an unbounded negated class can retry from
            # every '<' in malformed input and degrade quadratically.
            in_tag = False
            tag_has_content = False
            for char in content:
                if not in_tag:
                    if char == "<":
                        in_tag = True
                        tag_has_content = False
                    elif not char.isspace():
                        return False
                elif char == ">":
                    # The old <[^>]+> expression did not consume empty tags.
                    if not tag_has_content:
                        return False
                    in_tag = False
                else:
                    tag_has_content = True

            # An unterminated tag was text under the previous behavior.
            return not in_tag

        empty_docs = [d for d in csv_docs if is_empty_content(d.get("content"))]
        if empty_docs:
            warnings.append(f"Found {len(empty_docs)} documents with empty content")

        return warnings
