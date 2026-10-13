"""Unit tests for sync_differ module."""

import pytest

from itglue_migrate.state_fetcher import ExistingState
from itglue_migrate.sync_differ import (
    EntityPlan,
    PasswordPlan,
    RelationshipPlan,
    SyncDiffer,
    SyncPlan,
)


class TestEntityPlan:
    """Tests for EntityPlan dataclass."""

    def test_init_defaults(self) -> None:
        """EntityPlan should initialize with empty lists."""
        plan = EntityPlan()

        assert plan.to_create == []
        assert plan.to_update == []
        assert plan.existing == []
        assert plan.skipped == []

    def test_init_with_data(self) -> None:
        """EntityPlan should accept data on init."""
        plan = EntityPlan(
            to_create=[{"id": "1"}],
            to_update=[{"id": "2"}],
            existing=[{"id": "3"}],
            skipped=[{"id": "4"}],
        )

        assert len(plan.to_create) == 1
        assert len(plan.to_update) == 1
        assert len(plan.existing) == 1
        assert len(plan.skipped) == 1


class TestRelationshipPlan:
    """Tests for RelationshipPlan dataclass."""

    def test_init_defaults(self) -> None:
        """RelationshipPlan should initialize with empty lists."""
        plan = RelationshipPlan()

        assert plan.to_create == []
        assert plan.existing == []

    def test_init_with_data(self) -> None:
        """RelationshipPlan should accept data on init."""
        plan = RelationshipPlan(
            to_create=[{"source_id": "1"}],
            existing=[{"source_id": "2"}],
        )

        assert len(plan.to_create) == 1
        assert len(plan.existing) == 1


class TestPasswordPlan:
    """Tests for PasswordPlan dataclass."""

    def test_init_defaults(self) -> None:
        """PasswordPlan should initialize with empty lists."""
        plan = PasswordPlan()

        assert plan.to_create == []
        assert plan.to_update == []
        assert plan.existing == []
        assert plan.cell_writes == []
        assert plan.row_creates == []

    def test_init_with_data(self) -> None:
        """PasswordPlan should accept data on init."""
        plan = PasswordPlan(
            to_create=[{"id": "1"}],
            cell_writes=[{"id": "2"}],
            row_creates=[{"id": "3"}],
        )

        assert len(plan.to_create) == 1
        assert len(plan.cell_writes) == 1
        assert len(plan.row_creates) == 1


class TestSyncPlan:
    """Tests for SyncPlan dataclass."""

    def test_init_defaults(self) -> None:
        """SyncPlan should initialize with default plans."""
        plan = SyncPlan()

        assert isinstance(plan.organizations, EntityPlan)
        assert isinstance(plan.config_types, EntityPlan)
        assert isinstance(plan.config_statuses, EntityPlan)
        assert isinstance(plan.custom_asset_types, EntityPlan)
        assert isinstance(plan.locations, EntityPlan)
        assert isinstance(plan.configurations, EntityPlan)
        assert isinstance(plan.custom_assets, EntityPlan)
        assert isinstance(plan.documents, EntityPlan)
        assert isinstance(plan.passwords, PasswordPlan)
        assert isinstance(plan.relationships, RelationshipPlan)
        assert plan.validation_warnings == []

    def test_init_with_validation_warnings(self) -> None:
        """SyncPlan should accept validation_warnings on init."""
        plan = SyncPlan(validation_warnings=["Test warning"])

        assert plan.validation_warnings == ["Test warning"]


class TestSyncDifferOrganizations:
    """Tests for SyncDiffer.diff_organizations method."""

    def test_diff_finds_missing_organizations(self) -> None:
        """SyncDiffer identifies orgs in CSV but not in API."""
        state = ExistingState()
        state.org_by_itglue_id["123"] = "uuid-existing"
        state.org_by_name["existing org"] = "uuid-existing"

        csv_orgs = [
            {"id": "123", "name": "Existing Org"},
            {"id": "456", "name": "New Org"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_organizations(csv_orgs)

        assert len(plan.to_create) == 1
        assert plan.to_create[0]["name"] == "New Org"
        assert plan.to_create[0]["metadata"]["itglue_id"] == "456"
        assert len(plan.existing) == 1
        assert plan.existing[0]["name"] == "Existing Org"

    def test_diff_all_existing(self) -> None:
        """SyncDiffer correctly identifies all existing orgs."""
        state = ExistingState()
        state.org_by_itglue_id["1"] = "uuid-1"
        state.org_by_itglue_id["2"] = "uuid-2"

        csv_orgs = [
            {"id": "1", "name": "Org 1"},
            {"id": "2", "name": "Org 2"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_organizations(csv_orgs)

        assert len(plan.to_create) == 0
        assert len(plan.existing) == 2

    def test_diff_all_new(self) -> None:
        """SyncDiffer correctly identifies all new orgs."""
        state = ExistingState()

        csv_orgs = [
            {"id": "1", "name": "Org 1"},
            {"id": "2", "name": "Org 2"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_organizations(csv_orgs)

        assert len(plan.to_create) == 2
        assert len(plan.existing) == 0

    def test_diff_matches_by_name_fallback(self) -> None:
        """SyncDiffer matches org by name if itglue_id not found."""
        state = ExistingState()
        state.org_by_name["existing org"] = "uuid-existing"

        csv_orgs = [
            {"id": "123", "name": "Existing Org"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_organizations(csv_orgs)

        assert len(plan.to_create) == 0
        assert len(plan.existing) == 1
        assert plan.existing[0]["id"] == "uuid-existing"

    def test_diff_skips_empty_name(self) -> None:
        """SyncDiffer skips orgs with empty names."""
        state = ExistingState()

        csv_orgs = [
            {"id": "1", "name": ""},
            {"id": "2", "name": "Valid Org"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_organizations(csv_orgs)

        assert len(plan.to_create) == 1
        assert plan.to_create[0]["name"] == "Valid Org"


class TestSyncDifferConfigurations:
    """Tests for SyncDiffer.diff_configurations method."""

    def test_diff_finds_missing_configurations(self) -> None:
        """SyncDiffer identifies configs in CSV but not in API."""
        state = ExistingState()
        state.config_by_itglue_id["123"] = "uuid-existing"
        state.configs["uuid-existing"] = {"name": "Existing Server"}

        csv_configs = [
            {"id": "123", "name": "Existing Server"},
            {"id": "456", "name": "New Server"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_configurations(csv_configs)

        assert len(plan.to_create) == 1
        assert plan.to_create[0]["id"] == "456"
        assert len(plan.existing) == 1
        assert plan.existing[0]["id"] == "123"

    def test_diff_all_existing(self) -> None:
        """SyncDiffer correctly identifies all existing configs (no changes)."""
        state = ExistingState()
        state.config_by_itglue_id["1"] = "uuid-1"
        state.config_by_itglue_id["2"] = "uuid-2"
        state.configs["uuid-1"] = {"name": "Server 1"}
        state.configs["uuid-2"] = {"name": "Server 2"}

        csv_configs = [
            {"id": "1", "name": "Server 1"},
            {"id": "2", "name": "Server 2"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_configurations(csv_configs)

        assert len(plan.to_create) == 0
        assert len(plan.to_update) == 0
        assert len(plan.existing) == 2

    def test_diff_all_new(self) -> None:
        """SyncDiffer correctly identifies all new configs."""
        state = ExistingState()

        csv_configs = [
            {"id": "1", "name": "Server 1"},
            {"id": "2", "name": "Server 2"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_configurations(csv_configs)

        assert len(plan.to_create) == 2
        assert len(plan.existing) == 0

    def test_diff_skips_empty_id(self) -> None:
        """SyncDiffer skips configs with empty ID."""
        state = ExistingState()

        csv_configs = [
            {"id": "", "name": "No ID"},
            {"id": "1", "name": "Has ID"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_configurations(csv_configs)

        assert len(plan.to_create) == 1
        assert plan.to_create[0]["id"] == "1"

    def test_diff_handles_numeric_id(self) -> None:
        """SyncDiffer handles numeric IDs by converting to string."""
        state = ExistingState()
        state.config_by_itglue_id["123"] = "uuid-existing"
        state.configs["uuid-existing"] = {"name": "Numeric ID"}

        csv_configs = [
            {"id": 123, "name": "Numeric ID"},  # Numeric
            {"id": "456", "name": "String ID"},  # String
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_configurations(csv_configs)

        assert len(plan.existing) == 1
        assert len(plan.to_create) == 1


class TestSyncDifferLocations:
    """Tests for SyncDiffer.diff_locations method."""

    def test_diff_finds_missing_locations(self) -> None:
        """SyncDiffer identifies locations in CSV but not in API."""
        state = ExistingState()
        state.location_by_itglue_id["123"] = "uuid-existing"
        state.locations["uuid-existing"] = {"name": "Existing Location"}

        csv_locations = [
            {"id": "123", "name": "Existing Location"},
            {"id": "456", "name": "New Location"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_locations(csv_locations)

        assert len(plan.to_create) == 1
        assert plan.to_create[0]["id"] == "456"
        assert len(plan.existing) == 1

    def test_diff_empty_locations(self) -> None:
        """SyncDiffer handles empty location list."""
        state = ExistingState()

        differ = SyncDiffer(state)
        plan = differ.diff_locations([])

        assert len(plan.to_create) == 0
        assert len(plan.existing) == 0


class TestSyncDifferDocuments:
    """Tests for SyncDiffer.diff_documents method."""

    def test_diff_finds_missing_documents(self) -> None:
        """SyncDiffer identifies documents in CSV but not in API."""
        state = ExistingState()
        state.document_by_itglue_id["123"] = "uuid-existing"
        state.documents["uuid-existing"] = {"name": "Existing Doc"}

        csv_documents = [
            {"id": "123", "name": "Existing Doc"},
            {"id": "456", "name": "New Doc"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_documents(csv_documents)

        assert len(plan.to_create) == 1
        assert plan.to_create[0]["id"] == "456"
        assert len(plan.existing) == 1


class TestSyncDifferCustomAssets:
    """Tests for SyncDiffer.diff_custom_assets method."""

    def test_diff_finds_missing_custom_assets(self) -> None:
        """SyncDiffer identifies custom assets in CSV but not in API."""
        state = ExistingState()
        state.custom_asset_by_itglue_id["123"] = "uuid-existing"

        csv_assets = [
            {"id": "123", "name": "Existing Asset"},
            {"id": "456", "name": "New Asset"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_custom_assets(csv_assets)

        assert len(plan.to_create) == 1
        assert plan.to_create[0]["id"] == "456"
        assert len(plan.existing) == 1


class TestSyncDifferConfigTypes:
    """Tests for SyncDiffer.diff_config_types method."""

    def test_diff_extracts_unique_types(self) -> None:
        """SyncDiffer extracts unique config types from configs."""
        state = ExistingState()
        state.config_type_by_name["server"] = "type-uuid-1"

        csv_configs = [
            {"id": "1", "configuration_type": "Server"},
            {"id": "2", "configuration_type": "Server"},  # Duplicate
            {"id": "3", "configuration_type": "Router"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_config_types(csv_configs)

        # Server exists, Router is new (only 1 unique each)
        assert len(plan.existing) == 1
        assert len(plan.to_create) == 1
        assert plan.to_create[0]["name"] == "Router"

    def test_diff_skips_empty_type(self) -> None:
        """SyncDiffer skips configs without type."""
        state = ExistingState()

        csv_configs = [
            {"id": "1", "configuration_type": ""},
            {"id": "2", "configuration_type": None},
            {"id": "3", "configuration_type": "Server"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_config_types(csv_configs)

        assert len(plan.to_create) == 1
        assert plan.to_create[0]["name"] == "Server"


class TestSyncDifferPasswords:
    """Tests for SyncDiffer.diff_passwords method."""

    def test_diff_finds_missing_passwords(self) -> None:
        """SyncDiffer identifies passwords in CSV but not in API."""
        state = ExistingState()
        state.password_by_itglue_id["123"] = "uuid-existing"
        # Note: Without password value in CSV, nothing to update
        state.passwords["uuid-existing"] = {
            "name": "Existing Password",
            "username": "",
            "url": "",
            "notes": "",
        }

        csv_passwords = [
            {"id": "123", "name": "Existing Password", "resource_type": "Configuration"},
            {"id": "456", "name": "New Password", "resource_type": "Configuration"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_passwords(csv_passwords)

        assert len(plan.to_create) == 1
        assert plan.to_create[0]["id"] == "456"
        # Since no password value in CSV, no updates detected
        assert len(plan.existing) == 1

    def test_diff_separates_cell_writes(self) -> None:
        """SyncDiffer separates ::Cell passwords to cell_writes."""
        state = ExistingState()

        csv_passwords = [
            {
                "id": "1",
                "name": "Cell Password",
                "resource_type": "FlexibleAsset::StructuredData::Cell",
            },
            {"id": "2", "name": "Regular Password", "resource_type": "Configuration"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_passwords(csv_passwords)

        assert len(plan.cell_writes) == 1
        assert plan.cell_writes[0]["id"] == "1"
        assert len(plan.to_create) == 1
        assert plan.to_create[0]["id"] == "2"

    def test_diff_separates_row_creates(self) -> None:
        """SyncDiffer separates ::Row passwords to row_creates."""
        state = ExistingState()

        csv_passwords = [
            {
                "id": "1",
                "name": "Row Password",
                "resource_type": "FlexibleAsset::StructuredData::Row",
            },
            {"id": "2", "name": "Regular Password", "resource_type": "Configuration"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_passwords(csv_passwords)

        assert len(plan.row_creates) == 1
        assert plan.row_creates[0]["id"] == "1"
        assert len(plan.to_create) == 1
        assert plan.to_create[0]["id"] == "2"

    def test_diff_row_existing_goes_to_existing(self) -> None:
        """SyncDiffer puts existing ::Row passwords in existing list."""
        state = ExistingState()
        state.password_by_itglue_id["1"] = "uuid-existing"

        csv_passwords = [
            {
                "id": "1",
                "name": "Existing Row Password",
                "resource_type": "FlexibleAsset::StructuredData::Row",
            },
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_passwords(csv_passwords)

        assert len(plan.existing) == 1
        assert len(plan.row_creates) == 0


class TestSyncDifferRelationships:
    """Tests for SyncDiffer.diff_relationships method."""

    def test_diff_finds_missing_relationships(self) -> None:
        """SyncDiffer identifies relationships to create."""
        state = ExistingState()
        state.password_by_itglue_id["pwd-1"] = "pwd-uuid-1"
        state.config_by_itglue_id["cfg-1"] = "cfg-uuid-1"
        # No existing relationship

        csv_passwords = [
            {
                "id": "pwd-1",
                "name": "Admin Password",
                "resource_type": "Configuration",
                "resource_id": "cfg-1",
            },
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_relationships(csv_passwords)

        assert len(plan.to_create) == 1
        assert plan.to_create[0]["source_id"] == "pwd-uuid-1"
        assert plan.to_create[0]["target_id"] == "cfg-uuid-1"
        assert plan.to_create[0]["source_type"] == "password"
        assert plan.to_create[0]["target_type"] == "configuration"

    def test_diff_skips_existing_relationships(self) -> None:
        """SyncDiffer skips relationships that already exist."""
        state = ExistingState()
        state.password_by_itglue_id["pwd-1"] = "pwd-uuid-1"
        state.config_by_itglue_id["cfg-1"] = "cfg-uuid-1"
        # Existing relationship
        state.relationships.add("password:pwd-uuid-1:configuration:cfg-uuid-1")

        csv_passwords = [
            {
                "id": "pwd-1",
                "name": "Admin Password",
                "resource_type": "Configuration",
                "resource_id": "cfg-1",
            },
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_relationships(csv_passwords)

        assert len(plan.to_create) == 0
        assert len(plan.existing) == 1

    def test_diff_skips_cell_relationships(self) -> None:
        """SyncDiffer skips ::Cell passwords for relationships."""
        state = ExistingState()
        state.password_by_itglue_id["pwd-1"] = "pwd-uuid-1"

        csv_passwords = [
            {
                "id": "pwd-1",
                "name": "Cell Password",
                "resource_type": "FlexibleAsset::StructuredData::Cell",
                "resource_id": "asset-1",
            },
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_relationships(csv_passwords)

        # Cell passwords should not create relationships
        assert len(plan.to_create) == 0
        assert len(plan.existing) == 0

    def test_diff_handles_location_relationships(self) -> None:
        """SyncDiffer handles Location resource type."""
        state = ExistingState()
        state.password_by_itglue_id["pwd-1"] = "pwd-uuid-1"
        state.location_by_itglue_id["loc-1"] = "loc-uuid-1"

        csv_passwords = [
            {
                "id": "pwd-1",
                "name": "Location Password",
                "resource_type": "Location",
                "resource_id": "loc-1",
            },
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_relationships(csv_passwords)

        assert len(plan.to_create) == 1
        assert plan.to_create[0]["target_type"] == "location"
        assert plan.to_create[0]["target_id"] == "loc-uuid-1"

    def test_diff_handles_document_relationships(self) -> None:
        """SyncDiffer handles Document resource type."""
        state = ExistingState()
        state.password_by_itglue_id["pwd-1"] = "pwd-uuid-1"
        state.document_by_itglue_id["doc-1"] = "doc-uuid-1"

        csv_passwords = [
            {
                "id": "pwd-1",
                "name": "Doc Password",
                "resource_type": "Document",
                "resource_id": "doc-1",
            },
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_relationships(csv_passwords)

        assert len(plan.to_create) == 1
        assert plan.to_create[0]["target_type"] == "document"
        assert plan.to_create[0]["target_id"] == "doc-uuid-1"

    def test_diff_handles_custom_asset_relationships(self) -> None:
        """SyncDiffer handles StructuredData (custom asset) relationships."""
        state = ExistingState()
        state.password_by_itglue_id["pwd-1"] = "pwd-uuid-1"
        state.custom_asset_by_itglue_id["asset-1"] = "asset-uuid-1"

        csv_passwords = [
            {
                "id": "pwd-1",
                "name": "Asset Password",
                "resource_type": "FlexibleAsset::StructuredData::Row",
                "resource_id": "asset-1",
            },
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_relationships(csv_passwords)

        assert len(plan.to_create) == 1
        assert plan.to_create[0]["target_type"] == "custom_asset"
        assert plan.to_create[0]["target_id"] == "asset-uuid-1"

    def test_diff_creates_relationship_for_new_password(self) -> None:
        """SyncDiffer creates relationship when password will be created."""
        state = ExistingState()
        # Password not in state (will be created)
        state.config_by_itglue_id["cfg-1"] = "cfg-uuid-1"

        csv_passwords = [
            {
                "id": "pwd-1",
                "name": "New Password",
                "resource_type": "Configuration",
                "resource_id": "cfg-1",
            },
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_relationships(csv_passwords)

        # Relationship should be created (password will be created first)
        assert len(plan.to_create) == 1
        assert plan.to_create[0]["source_itglue_id"] == "pwd-1"
        assert plan.to_create[0]["target_type"] == "configuration"
        assert plan.to_create[0]["target_id"] == "cfg-uuid-1"

    def test_diff_creates_relationship_for_missing_target(self) -> None:
        """SyncDiffer creates relationship even when target UUID is missing."""
        state = ExistingState()
        state.password_by_itglue_id["pwd-1"] = "pwd-uuid-1"
        # Config not in state (might be created by sync)

        csv_passwords = [
            {
                "id": "pwd-1",
                "name": "Password",
                "resource_type": "Configuration",
                "resource_id": "cfg-1",  # Not in state yet
            },
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_relationships(csv_passwords)

        # Relationship should be created (target_id=None, will resolve later)
        assert len(plan.to_create) == 1
        assert plan.to_create[0]["source_id"] == "pwd-uuid-1"
        assert plan.to_create[0]["target_itglue_id"] == "cfg-1"
        assert plan.to_create[0]["target_id"] is None

    def test_diff_skips_empty_resource(self) -> None:
        """SyncDiffer skips relationships with empty resource_type or resource_id."""
        state = ExistingState()
        state.password_by_itglue_id["pwd-1"] = "pwd-uuid-1"

        csv_passwords = [
            {"id": "pwd-1", "name": "No resource", "resource_type": "", "resource_id": ""},
            {
                "id": "pwd-2",
                "name": "No resource type",
                "resource_type": None,
                "resource_id": "cfg-1",
            },
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_relationships(csv_passwords)

        assert len(plan.to_create) == 0


class TestSyncDifferUpdateDetection:
    """Tests for SyncDiffer update detection functionality."""

    def test_diff_configurations_detects_name_change(self) -> None:
        """SyncDiffer detects when configuration name has changed."""
        state = ExistingState()
        state.config_by_itglue_id["123"] = "uuid-existing"
        state.configs["uuid-existing"] = {"name": "Old Server Name", "serial_number": "SN123"}

        csv_configs = [
            {"id": "123", "name": "New Server Name", "serial_number": "SN123"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_configurations(csv_configs)

        assert len(plan.to_create) == 0
        assert len(plan.existing) == 0
        assert len(plan.to_update) == 1
        assert plan.to_update[0]["uuid"] == "uuid-existing"
        assert plan.to_update[0]["changes"]["name"] == "New Server Name"

    def test_diff_configurations_no_change_stays_existing(self) -> None:
        """SyncDiffer keeps unchanged configuration in existing list."""
        state = ExistingState()
        state.config_by_itglue_id["123"] = "uuid-existing"
        state.configs["uuid-existing"] = {"name": "Same Name", "serial_number": "SN123"}

        csv_configs = [
            {"id": "123", "name": "Same Name", "serial_number": "SN123"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_configurations(csv_configs)

        assert len(plan.to_create) == 0
        assert len(plan.to_update) == 0
        assert len(plan.existing) == 1

    def test_diff_configurations_detects_multiple_changes(self) -> None:
        """SyncDiffer detects multiple field changes."""
        state = ExistingState()
        state.config_by_itglue_id["123"] = "uuid-existing"
        state.configs["uuid-existing"] = {
            "name": "Old Name",
            "serial_number": "OLD-SN",
            "notes": "Old notes",
        }

        csv_configs = [
            {"id": "123", "name": "New Name", "serial_number": "NEW-SN", "notes": "New notes"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_configurations(csv_configs)

        assert len(plan.to_update) == 1
        changes = plan.to_update[0]["changes"]
        assert "name" in changes
        assert "serial_number" in changes
        assert "notes" in changes

    def test_diff_locations_detects_address_change(self) -> None:
        """SyncDiffer detects when location address has changed."""
        state = ExistingState()
        state.location_by_itglue_id["456"] = "loc-uuid"
        state.locations["loc-uuid"] = {"name": "Main Office", "address_1": "123 Old St"}

        csv_locations = [
            {"id": "456", "name": "Main Office", "address_1": "456 New Ave"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_locations(csv_locations)

        assert len(plan.to_update) == 1
        assert plan.to_update[0]["changes"]["address_1"] == "456 New Ave"

    def test_diff_documents_detects_content_change(self) -> None:
        """SyncDiffer detects when document content has changed."""
        state = ExistingState()
        state.document_by_itglue_id["789"] = "doc-uuid"
        state.documents["doc-uuid"] = {"name": "Runbook", "content": "Old content"}

        csv_documents = [
            {"id": "789", "name": "Runbook", "content": "New content"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_documents(csv_documents)

        assert len(plan.to_update) == 1
        assert plan.to_update[0]["changes"]["content"] == "New content"

    def test_diff_passwords_detects_changes_and_includes_password(self) -> None:
        """SyncDiffer detects password changes and always includes password value."""
        state = ExistingState()
        state.password_by_itglue_id["pwd-1"] = "pwd-uuid"
        state.passwords["pwd-uuid"] = {
            "name": "Old Name",
            "username": "olduser",
            "url": "https://old.com",
        }

        csv_passwords = [
            {
                "id": "pwd-1",
                "name": "New Name",
                "username": "newuser",
                "url": "https://old.com",
                "password": "newpassword123",
                "resource_type": "Configuration",
            },
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_passwords(csv_passwords)

        assert len(plan.to_update) == 1
        changes = plan.to_update[0]["changes"]
        assert changes["name"] == "New Name"
        assert changes["username"] == "newuser"
        assert "url" not in changes  # URL didn't change
        assert changes["password"] == "newpassword123"  # Always included

    def test_diff_normalizes_whitespace(self) -> None:
        """SyncDiffer normalizes whitespace when comparing values."""
        state = ExistingState()
        state.config_by_itglue_id["123"] = "uuid-existing"
        state.configs["uuid-existing"] = {"name": "Server Name", "serial_number": "SN123"}

        csv_configs = [
            {"id": "123", "name": "  Server Name  ", "serial_number": "SN123"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_configurations(csv_configs)

        # Names are the same after normalization, so no update needed
        assert len(plan.to_update) == 0
        assert len(plan.existing) == 1

    def test_diff_handles_none_values(self) -> None:
        """SyncDiffer handles None values correctly."""
        state = ExistingState()
        state.config_by_itglue_id["123"] = "uuid-existing"
        state.configs["uuid-existing"] = {"name": "Server", "serial_number": None}

        csv_configs = [
            {"id": "123", "name": "Server", "serial_number": ""},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_configurations(csv_configs)

        # Both normalize to empty string, so no update
        assert len(plan.to_update) == 0
        assert len(plan.existing) == 1


class TestSyncDifferDuplicateDetection:
    """Tests for duplicate detection in SyncDiffer."""

    def test_diff_organizations_skips_duplicates(self) -> None:
        """Duplicate org names are skipped (case-insensitive)."""
        state = ExistingState()

        csv_orgs = [
            {"id": "1", "name": "Acme Inc"},
            {"id": "2", "name": "ACME INC"},  # Duplicate (case-insensitive)
            {"id": "3", "name": "Other Corp"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_organizations(csv_orgs)

        assert len(plan.to_create) == 2
        assert len(plan.skipped) == 1
        assert plan.skipped[0]["name"] == "ACME INC"
        assert plan.skipped[0]["itglue_id"] == "2"
        assert plan.skipped[0]["reason"] == "duplicate_name"

    def test_diff_organizations_skips_multiple_duplicates(self) -> None:
        """Multiple duplicates of the same name are all skipped."""
        state = ExistingState()

        csv_orgs = [
            {"id": "1", "name": "Acme Inc"},
            {"id": "2", "name": "ACME INC"},
            {"id": "3", "name": "acme inc"},  # Third duplicate
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_organizations(csv_orgs)

        assert len(plan.to_create) == 1
        assert plan.to_create[0]["name"] == "Acme Inc"
        assert len(plan.skipped) == 2

    def test_diff_organizations_keeps_first_existing_match(self) -> None:
        """First org goes to existing if it matches, duplicates skipped."""
        state = ExistingState()
        state.org_by_itglue_id["1"] = "uuid-1"

        csv_orgs = [
            {"id": "1", "name": "Acme Inc"},  # Existing
            {"id": "2", "name": "acme inc"},  # Duplicate - skipped
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_organizations(csv_orgs)

        assert len(plan.existing) == 1
        assert len(plan.to_create) == 0
        assert len(plan.skipped) == 1
        assert plan.skipped[0]["itglue_id"] == "2"

    def test_diff_documents_skips_duplicates_within_same_org(self) -> None:
        """Duplicate doc names within same org are skipped."""
        state = ExistingState()

        csv_docs = [
            {"id": "1", "name": "Network Diagram", "organization_id": "org-1"},
            {"id": "2", "name": "NETWORK DIAGRAM", "organization_id": "org-1"},  # Duplicate
            {"id": "3", "name": "Network Diagram", "organization_id": "org-2"},  # Different org - OK
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_documents(csv_docs)

        assert len(plan.to_create) == 2
        assert len(plan.skipped) == 1
        assert plan.skipped[0]["name"] == "NETWORK DIAGRAM"
        assert plan.skipped[0]["itglue_id"] == "2"
        assert plan.skipped[0]["organization_id"] == "org-1"
        assert plan.skipped[0]["reason"] == "duplicate_name"

    def test_diff_documents_allows_same_name_different_orgs(self) -> None:
        """Same doc name in different orgs is not a duplicate."""
        state = ExistingState()

        csv_docs = [
            {"id": "1", "name": "Runbook", "organization_id": "org-1"},
            {"id": "2", "name": "Runbook", "organization_id": "org-2"},
            {"id": "3", "name": "Runbook", "organization_id": "org-3"},
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_documents(csv_docs)

        assert len(plan.to_create) == 3
        assert len(plan.skipped) == 0

    def test_diff_documents_keeps_first_existing_skips_duplicate(self) -> None:
        """First doc goes to existing/update, duplicate skipped."""
        state = ExistingState()
        state.document_by_itglue_id["1"] = "doc-uuid-1"
        state.documents["doc-uuid-1"] = {"name": "Runbook", "content": "old content"}

        csv_docs = [
            {"id": "1", "name": "Runbook", "organization_id": "org-1", "content": "old content"},
            {"id": "2", "name": "RUNBOOK", "organization_id": "org-1", "content": "other"},  # Duplicate
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_documents(csv_docs)

        assert len(plan.existing) == 1
        assert len(plan.to_create) == 0
        assert len(plan.skipped) == 1
        assert plan.skipped[0]["itglue_id"] == "2"

    def test_diff_documents_handles_empty_org_id(self) -> None:
        """Documents with empty org_id are tracked separately."""
        state = ExistingState()

        csv_docs = [
            {"id": "1", "name": "Global Doc", "organization_id": ""},
            {"id": "2", "name": "GLOBAL DOC", "organization_id": ""},  # Duplicate in empty org
            {"id": "3", "name": "Global Doc", "organization_id": "org-1"},  # Different org - OK
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_documents(csv_docs)

        assert len(plan.to_create) == 2
        assert len(plan.skipped) == 1
        assert plan.skipped[0]["itglue_id"] == "2"

    def test_diff_documents_handles_missing_name(self) -> None:
        """Documents without names are processed (no duplicate check)."""
        state = ExistingState()

        csv_docs = [
            {"id": "1", "name": "", "organization_id": "org-1"},
            {"id": "2", "name": "", "organization_id": "org-1"},  # Both empty - processed
        ]

        differ = SyncDiffer(state)
        plan = differ.diff_documents(csv_docs)

        # Both are processed (empty names are tracked but both go to to_create)
        assert len(plan.to_create) == 2
        assert len(plan.skipped) == 0


class TestSyncDifferValidation:
    """Tests for data quality validation."""

    @pytest.fixture
    def mock_state(self) -> ExistingState:
        """Create an empty ExistingState for testing."""
        return ExistingState()

    def test_validate_detects_duplicate_orgs(self, mock_state: ExistingState) -> None:
        """Duplicate org names are detected (case-insensitive)."""
        differ = SyncDiffer(mock_state)
        orgs = [{"name": "Acme"}, {"name": "ACME"}]
        warnings = differ.validate_data_quality(orgs, [], [])

        assert len(warnings) == 1
        assert any("duplicate" in w.lower() for w in warnings)

    def test_validate_detects_multiple_duplicate_org_names(
        self, mock_state: ExistingState
    ) -> None:
        """Multiple different duplicate org names are counted correctly."""
        differ = SyncDiffer(mock_state)
        orgs = [
            {"name": "Acme"},
            {"name": "ACME"},
            {"name": "Beta Corp"},
            {"name": "BETA CORP"},
        ]
        warnings = differ.validate_data_quality(orgs, [], [])

        assert len(warnings) == 1
        assert "2 duplicate" in warnings[0]

    def test_validate_large_duplicate_and_malformed_html_inputs(
        self, mock_state: ExistingState
    ) -> None:
        differ = SyncDiffer(mock_state)
        orgs = [{"name": f"Org {index // 2}"} for index in range(4_000)]
        docs = [{"name": "Malformed", "content": "<" * 100_000}]

        warnings = differ.validate_data_quality(orgs, docs, [])

        assert any("2000 duplicate" in warning for warning in warnings)
        assert not any("documents have empty content" in warning for warning in warnings)

    def test_validate_no_duplicates_returns_empty(
        self, mock_state: ExistingState
    ) -> None:
        """No warnings when no duplicates exist."""
        differ = SyncDiffer(mock_state)
        orgs = [{"name": "Acme"}, {"name": "Beta"}]
        warnings = differ.validate_data_quality(orgs, [], [])

        assert len(warnings) == 0

    def test_validate_detects_empty_passwords(self, mock_state: ExistingState) -> None:
        """Empty password values are detected."""
        differ = SyncDiffer(mock_state)
        passwords = [{"name": "test", "password": ""}]
        warnings = differ.validate_data_quality([], [], passwords)

        assert len(warnings) == 1
        assert any("empty" in w.lower() for w in warnings)
        assert "1 passwords" in warnings[0]

    def test_validate_detects_multiple_empty_passwords(
        self, mock_state: ExistingState
    ) -> None:
        """Multiple empty passwords are counted."""
        differ = SyncDiffer(mock_state)
        passwords = [
            {"name": "test1", "password": ""},
            {"name": "test2", "password": None},
            {"name": "test3", "password": "secret"},  # Not empty
        ]
        warnings = differ.validate_data_quality([], [], passwords)

        assert len(warnings) == 1
        assert "2 passwords" in warnings[0]

    def test_validate_detects_empty_documents(self, mock_state: ExistingState) -> None:
        """Documents with empty content are detected."""
        differ = SyncDiffer(mock_state)
        docs = [{"name": "Empty Doc", "content": ""}]
        warnings = differ.validate_data_quality([], docs, [])

        assert len(warnings) == 1
        assert any("empty content" in w.lower() for w in warnings)

    def test_validate_detects_html_only_documents(
        self, mock_state: ExistingState
    ) -> None:
        """Documents with HTML tags but no text content are detected."""
        differ = SyncDiffer(mock_state)
        docs = [
            {"name": "HTML Only", "content": "<p></p>"},
            {"name": "Whitespace Only", "content": "<div>   </div>"},
        ]
        warnings = differ.validate_data_quality([], docs, [])

        assert len(warnings) == 1
        assert "2 documents" in warnings[0]

    def test_validate_ignores_non_empty_documents(
        self, mock_state: ExistingState
    ) -> None:
        """Documents with actual content are not flagged."""
        differ = SyncDiffer(mock_state)
        docs = [
            {"name": "Real Doc", "content": "<p>Hello world</p>"},
            {"name": "Plain Doc", "content": "Just text"},
        ]
        warnings = differ.validate_data_quality([], docs, [])

        assert len(warnings) == 0

    def test_validate_returns_all_warnings(self, mock_state: ExistingState) -> None:
        """All validation issues are returned together."""
        differ = SyncDiffer(mock_state)
        orgs = [{"name": "Acme"}, {"name": "ACME"}]
        docs = [{"name": "Empty", "content": ""}]
        passwords = [{"name": "test", "password": ""}]

        warnings = differ.validate_data_quality(orgs, docs, passwords)

        assert len(warnings) == 3
        assert any("duplicate" in w.lower() for w in warnings)
        assert any("empty content" in w.lower() for w in warnings)
        assert any("passwords" in w.lower() for w in warnings)

    def test_validate_handles_empty_inputs(self, mock_state: ExistingState) -> None:
        """Empty input lists return no warnings."""
        differ = SyncDiffer(mock_state)
        warnings = differ.validate_data_quality([], [], [])

        assert len(warnings) == 0

    def test_validate_handles_missing_fields(self, mock_state: ExistingState) -> None:
        """Missing fields are handled gracefully."""
        differ = SyncDiffer(mock_state)
        orgs = [{}]  # No name field
        docs = [{"name": "No Content"}]  # No content field
        passwords = [{"name": "No Password"}]  # No password field

        warnings = differ.validate_data_quality(orgs, docs, passwords)

        # Empty password should be detected, empty doc content should be detected
        assert len(warnings) == 2
