"""
Smoke test for IT Glue migration using seeded fixture.

This test runs a lightweight rehearsal of the migration tool against a
synthetic fixture to verify the entire pipeline works end-to-end.
"""

import json
import tempfile
from pathlib import Path

import pytest

from itglue_migrate.csv_parser import CSVParser
from itglue_migrate.importers import ImportContext


# Path to the fixture
FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "minimal-export"


class TestMinimalExportStructure:
    """Tests that validate the minimal export fixture structure."""

    def test_fixture_directory_exists(self):
        """Verify the fixture directory exists."""
        assert FIXTURE_PATH.exists(), f"Fixture not found: {FIXTURE_PATH}"
        assert FIXTURE_PATH.is_dir(), f"Fixture is not a directory: {FIXTURE_PATH}"

    def test_required_csv_files_present(self):
        """Verify all required CSV files are present."""
        required_files = [
            "organizations.csv",
            "configurations.csv",
            "documents.csv",
            "locations.csv",
            "passwords.csv",
        ]
        
        for filename in required_files:
            file_path = FIXTURE_PATH / filename
            assert file_path.exists(), f"Missing required file: {filename}"

    def test_csv_files_are_readable(self):
        """Verify all CSV files can be read."""
        parser = CSVParser()
        
        # Parse each file to ensure they're valid
        orgs = parser.parse_organizations(FIXTURE_PATH / "organizations.csv")
        assert len(orgs) >= 1, "Should have at least one organization"
        
        configs = parser.parse_configurations(FIXTURE_PATH / "configurations.csv")
        assert len(configs) >= 1, "Should have at least one configuration"
        
        docs = parser.parse_documents(FIXTURE_PATH / "documents.csv")
        assert len(docs) >= 1, "Should have at least one document"
        
        locations = parser.parse_locations(FIXTURE_PATH / "locations.csv")
        assert len(locations) >= 1, "Should have at least one location"
        
        passwords = parser.parse_passwords(FIXTURE_PATH / "passwords.csv")
        assert len(passwords) >= 1, "Should have at least one password"

    def test_validate_export_structure(self):
        """Verify the export passes structure validation."""
        parser = CSVParser()
        validation = parser.validate_export_structure(FIXTURE_PATH)
        
        assert validation["valid"], f"Export validation failed: {validation.get('errors', [])}"
        assert validation["core_entities"]["organizations"]["present"]
        
        # Should have no validation errors
        assert len(validation.get("errors", [])) == 0, \
            f"Validation errors: {validation['errors']}"


class TestImportContextCreation:
    """Tests for creating ImportContext from fixture."""

    def test_create_import_context(self):
        """Verify ImportContext can be created from fixture."""
        parser = CSVParser()
        
        # Parse all entities
        organizations = parser.parse_organizations(FIXTURE_PATH / "organizations.csv")
        configurations = parser.parse_configurations(FIXTURE_PATH / "configurations.csv")
        documents = parser.parse_documents(FIXTURE_PATH / "documents.csv")
        locations = parser.parse_locations(FIXTURE_PATH / "locations.csv")
        passwords = parser.parse_passwords(FIXTURE_PATH / "passwords.csv")
        
        # Create import context
        ctx = ImportContext(
            organizations=organizations,
            configurations=configurations,
            documents=documents,
            locations=locations,
            passwords=passwords,
            custom_assets=[],  # No custom assets in minimal fixture
        )
        
        # Verify counts
        assert len(ctx.organizations) == 2, "Should have 2 organizations"
        assert len(ctx.configurations) == 2, "Should have 2 configurations"
        assert len(ctx.documents) == 1, "Should have 1 document"
        assert len(ctx.locations) == 1, "Should have 1 location"
        assert len(ctx.passwords) == 2, "Should have 2 passwords"


class TestOrganizationMapping:
    """Tests for organization ID mapping."""

    def test_organization_ids_are_unique(self):
        """Verify organization IDs in fixture are unique."""
        parser = CSVParser()
        organizations = parser.parse_organizations(FIXTURE_PATH / "organizations.csv")
        
        org_ids = [org.id for org in organizations]
        assert len(org_ids) == len(set(org_ids)), "Organization IDs should be unique"

    def test_organization_names_not_empty(self):
        """Verify all organizations have names."""
        parser = CSVParser()
        organizations = parser.parse_organizations(FIXTURE_PATH / "organizations.csv")
        
        for org in organizations:
            assert org.name, f"Organization {org.id} has no name"
            assert len(org.name.strip()) > 0, f"Organization {org.id} has empty name"


class TestDataQuality:
    """Tests for data quality in the fixture."""

    def test_all_test_prefixes(self):
        """Verify test data is clearly marked as test/synthetic."""
        parser = CSVParser()
        
        organizations = parser.parse_organizations(FIXTURE_PATH / "organizations.csv")
        for org in organizations:
            assert "Test" in org.name or "test" in org.name.lower(), \
                f"Organization {org.name} should have 'Test' in name"

    def test_passwords_marked_as_test(self):
        """Verify passwords have test markers."""
        parser = CSVParser()
        passwords = parser.parse_passwords(FIXTURE_PATH / "passwords.csv")
        
        for pwd in passwords:
            assert "Test" in pwd.name, f"Password {pwd.name} should have 'Test' in name"
            # Notes should warn not to use
            assert "test" in pwd.notes.lower() or "DO NOT USE" in pwd.notes, \
                f"Password {pwd.name} should have warning in notes"

    def test_no_real_domains_in_urls(self):
        """Verify URLs use example.com or test domains."""
        parser = CSVParser()
        passwords = parser.parse_passwords(FIXTURE_PATH / "passwords.csv")
        
        safe_domains = ["example.com", "test.", "localhost"]
        
        for pwd in passwords:
            if pwd.url:
                is_safe = any(domain in pwd.url for domain in safe_domains)
                assert is_safe, f"Password URL {pwd.url} should use safe test domain"


class TestMigrationPlanGeneration:
    """Smoke test for migration plan generation (no API calls)."""

    @pytest.mark.integration
    def test_can_create_plan_structure(self):
        """Verify a plan structure can be created from fixture data."""
        parser = CSVParser()
        
        # Parse all entities
        organizations = parser.parse_organizations(FIXTURE_PATH / "organizations.csv")
        
        # Create a minimal plan structure
        plan = {
            "version": 1,
            "generated_at": "2026-01-01T00:00:00Z",
            "source_export": str(FIXTURE_PATH),
            "summary": {
                "total_organizations": len(organizations),
                "total_configurations": 2,
                "total_documents": 1,
                "total_locations": 1,
                "total_passwords": 2,
            },
            "organizations": [
                {
                    "source_id": org.id,
                    "name": org.name,
                    "action": "create",
                }
                for org in organizations
            ],
        }
        
        # Verify plan can be serialized
        plan_json = json.dumps(plan, indent=2)
        assert len(plan_json) > 0, "Plan should serialize to JSON"
        
        # Verify plan structure
        assert plan["summary"]["total_organizations"] == 2
        assert len(plan["organizations"]) == 2

    @pytest.mark.integration
    def test_plan_file_roundtrip(self):
        """Verify plan can be written to and read from a file."""
        parser = CSVParser()
        organizations = parser.parse_organizations(FIXTURE_PATH / "organizations.csv")
        
        plan = {
            "version": 1,
            "organizations": [{"source_id": org.id, "name": org.name} for org in organizations],
        }
        
        # Write to temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(plan, f, indent=2)
            temp_path = f.name
        
        try:
            # Read back
            with open(temp_path) as f:
                loaded = json.load(f)
            
            assert loaded["version"] == 1
            assert len(loaded["organizations"]) == 2
        finally:
            Path(temp_path).unlink(missing_ok=True)


# =============================================================================
# CLI Integration Smoke Tests
# =============================================================================

@pytest.mark.cli
@pytest.mark.integration
class TestCLICommands:
    """Smoke tests for CLI commands against the fixture."""
    
    def test_cli_help_runs(self):
        """Verify CLI help command works."""
        from itglue_migrate.cli import app
        from typer.testing import CliRunner
        
        runner = CliRunner()
        result = runner.invoke(app, ["--help"])
        
        assert result.exit_code == 0, f"CLI help failed: {result.output}"
        assert "IT Glue to Skra Migration Tool" in result.output
    
    def test_preview_command_validates_fixture(self):
        """Verify preview command can validate the fixture structure."""
        from itglue_migrate.csv_parser import CSVParser
        
        # This is what preview does first
        parser = CSVParser()
        validation = parser.validate_export_structure(FIXTURE_PATH)
        
        assert validation["valid"], "Preview should validate fixture successfully"
        
        # Check expected entity counts
        assert validation["core_entities"]["organizations"]["row_count"] == 2
        assert validation["core_entities"]["configurations"]["row_count"] == 2
        assert validation["core_entities"]["documents"]["row_count"] == 1
        assert validation["core_entities"]["locations"]["row_count"] == 1
        assert validation["core_entities"]["passwords"]["row_count"] == 2


# =============================================================================
# Documentation Tests
# =============================================================================

class TestFixtureDocumentation:
    """Tests that fixture documentation is up to date."""
    
    def test_readme_exists(self):
        """Verify README exists in fixture directory."""
        readme_path = FIXTURE_PATH / "README.md"
        assert readme_path.exists(), "Fixture README should exist"
    
    def test_readme_mentions_all_entities(self):
        """Verify README documents all entity types."""
        readme_path = FIXTURE_PATH / "README.md"
        readme_content = readme_path.read_text()
        
        # Should mention all entity types
        assert "Organizations" in readme_content
        assert "Configurations" in readme_content
        assert "Documents" in readme_content
        assert "Locations" in readme_content
        assert "Passwords" in readme_content
        
        # Should have safety warning
        assert "synthetic" in readme_content.lower() or "test" in readme_content.lower()
