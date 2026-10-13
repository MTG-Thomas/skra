"""Tests for organization filtering in the sync CLI."""

from itglue_migrate.cli import _exclude_skipped_organizations
from itglue_migrate.sync_differ import EntityPlan


def test_excludes_only_exact_duplicate_source_rows() -> None:
    """Skipped duplicates cannot be processed under the first matching org."""
    organizations = [
        {"id": "1", "name": "Acme"},
        {"id": "2", "name": "ACME"},
        {"id": "3", "name": "Other"},
    ]
    plan = EntityPlan(
        skipped=[
            {
                "name": "ACME",
                "itglue_id": "2",
                "source_index": 1,
                "reason": "duplicate_name",
            }
        ]
    )

    assert _exclude_skipped_organizations(organizations, plan) == [
        organizations[0],
        organizations[2],
    ]
