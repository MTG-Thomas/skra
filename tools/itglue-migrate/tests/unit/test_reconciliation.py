"""Tests for migration reconciliation report models."""

from __future__ import annotations

import json
from pathlib import Path

from itglue_migrate.reconciliation import (
    OrganizationReconciliation,
    ReconciliationReport,
    apply_result_counts,
    build_plan_counts,
)
from itglue_migrate.sync_differ import SyncPlan
from itglue_migrate.sync_executor import SyncResult


def test_build_plan_counts_includes_core_entity_counts() -> None:
    """Plan counts should capture creates, updates, existing, and relationship duplicates."""
    plan = SyncPlan()
    plan.configurations.to_create = [{"id": "1"}]
    plan.configurations.to_update = [{"id": "2"}]
    plan.configurations.existing = [{"id": "3"}]
    plan.relationships.to_create = [{"source_id": "pwd-1"}]
    plan.relationships.existing = [{"source_id": "pwd-2"}]

    counts = build_plan_counts(plan)

    assert counts["configurations"].planned_create == 1
    assert counts["configurations"].planned_update == 1
    assert counts["configurations"].existing == 1
    assert counts["relationships"].planned_create == 1
    assert counts["relationships"].duplicate == 1


def test_apply_result_counts_overlays_execution_result() -> None:
    """Execution counts should be included without losing plan counts."""
    plan = SyncPlan()
    plan.documents.to_create = [{"id": "doc-1"}]
    counts = build_plan_counts(plan)
    result = SyncResult(
        created={"documents": 1},
        updated={"configurations": 2},
        skipped={"passwords": 3},
        failed={"relationships": 4},
    )

    merged = apply_result_counts(counts, result)

    assert merged["documents"].planned_create == 1
    assert merged["documents"].created == 1
    assert merged["configurations"].updated == 2
    assert merged["passwords"].skipped == 3
    assert merged["relationships"].failed == 4
    assert merged["relationships"].errors == 4


def test_report_summary_flags_follow_up_for_failures() -> None:
    """Operator summary should flag follow-up when failures are present."""
    report = ReconciliationReport.create(
        export_path=Path("/tmp/export"),
        target="all",
        dry_run=False,
    )
    report.organizations.append(
        OrganizationReconciliation(
            name="Midtown",
            itglue_id="1",
            bifrost_id="org-1",
            dry_run=False,
            entities=apply_result_counts(
                build_plan_counts(SyncPlan()),
                SyncResult(failed={"relationships": 1}),
            ),
        )
    )

    summary = report.summary()

    assert summary["organization_count"] == 1
    assert summary["failed_count"] == 1
    assert summary["follow_up_required"] is True


def test_report_summary_ignores_clean_attachment_and_relationship_summaries() -> None:
    """Clean validation sections should not force operator follow-up."""
    report = ReconciliationReport.create(
        export_path=Path("/tmp/export"),
        target="all",
        dry_run=False,
    )
    report.organizations.append(
        OrganizationReconciliation(
            name="Midtown",
            itglue_id="1",
            bifrost_id="org-1",
            dry_run=False,
            entities=build_plan_counts(SyncPlan()),
            attachment_summary={
                "checked": 4,
                "failed": 0,
                "orphaned_folders": 0,
                "failure_categories": {
                    "missing_file": 0,
                    "broken_api_reference": 0,
                    "count_mismatch": 0,
                },
            },
            relationship_summary={
                "created": 2,
                "skipped": 0,
                "failed": 0,
                "missing_source": 0,
                "missing_target": 0,
                "transient_error": 0,
            },
        )
    )

    assert report.summary()["follow_up_required"] is False


def test_report_summary_flags_follow_up_for_validation_issues() -> None:
    """Validation failures should be surfaced in the operator summary."""
    report = ReconciliationReport.create(
        export_path=Path("/tmp/export"),
        target="all",
        dry_run=False,
    )
    report.organizations.append(
        OrganizationReconciliation(
            name="Midtown",
            itglue_id="1",
            bifrost_id="org-1",
            dry_run=False,
            entities=build_plan_counts(SyncPlan()),
            attachment_summary={
                "failure_categories": {
                    "missing_file": 1,
                    "broken_api_reference": 0,
                    "count_mismatch": 0,
                }
            },
            relationship_summary={"missing_target": 1},
        )
    )

    assert report.summary()["follow_up_required"] is True


def test_apply_result_counts_reports_execution_duplicates() -> None:
    """Execution duplicate links must surface in the relationships row (issue #25)."""
    counts = build_plan_counts(SyncPlan())
    result = SyncResult(
        created={"relationships": 1},
        skipped={"relationships": 2},
        failed={"relationships": 0},
        relationship_summary={
            "created": 1,
            "skipped": 0,
            "duplicate": 2,
            "failed": 0,
            "missing_source": 1,
            "missing_target": 1,
            "transient_error": 0,
        },
    )

    merged = apply_result_counts(counts, result)

    assert merged["relationships"].created == 1
    assert merged["relationships"].skipped == 2
    assert merged["relationships"].duplicate == 2
    assert merged["relationships"].failed == 0


def test_organization_serializes_relationship_audit_reasons() -> None:
    """Per-link audit reasons must survive into the reconciliation JSON (issue #25)."""
    org = OrganizationReconciliation(
        name="Acme",
        itglue_id="1001",
        bifrost_id="org-uuid",
        dry_run=False,
        relationship_summary={"missing_target": 1},
        relationship_audit=[
            {
                "status": "missing_target",
                "count_key": "missing_target",
                "relationship_key": None,
                "source_type": "password",
                "source_id": "pwd-uuid-2",
                "target_type": "configuration",
                "target_id": None,
                "error": None,
                "reason": "could not resolve target configuration "
                "(itglue:cfg-9); sync the target entity first, then "
                "re-run relationship sync",
            }
        ],
    )

    payload = org.to_dict()

    assert payload["relationship_audit"][0]["reason"].startswith(
        "could not resolve target configuration (itglue:cfg-9)"
    )


def test_report_writes_stable_json(tmp_path: Path) -> None:
    """Report writer should produce parseable JSON with schema metadata."""
    report = ReconciliationReport.create(
        export_path=tmp_path / "export",
        target="Midtown",
        dry_run=True,
    )
    output = tmp_path / "reports" / "reconciliation.json"

    report.write_json(output)

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["target"] == "Midtown"
    assert data["dry_run"] is True
    assert data["summary"]["organization_count"] == 0
