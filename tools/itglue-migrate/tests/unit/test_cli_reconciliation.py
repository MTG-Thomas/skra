"""Sync reconciliation attachment/image summary coverage.

Locks the contract that the sync JSON report carries embedded-image
mismatch counts inside ``attachment_summary`` so issue #23 criterion
"attachment/image mismatch counts if available" stays demonstrable.
"""

from __future__ import annotations

from pathlib import Path

from itglue_migrate.cli import (
    _build_attachment_validation_summary,
    _build_per_org_plan,
)
from itglue_migrate.reconciliation import (
    OrganizationReconciliation,
    ReconciliationReport,
    build_plan_counts,
)
from itglue_migrate.sync_differ import EntityPlan, SyncPlan
from itglue_migrate.verification import BROKEN_EMBEDDED_IMAGE


def _write_doc_with_image(export: Path, src: str) -> None:
    doc_dir = export / "documents" / "DOC-1-200 HTML Document"
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "index.html").write_text(
        f"<p>doc</p><img src=\"{src}\">", encoding="utf-8"
    )


def test_live_per_org_plan_does_not_retry_global_creation() -> None:
    org = {"id": "1", "name": "Acme"}
    global_plan = EntityPlan(to_create=[org])

    live = _build_per_org_plan(org, global_plan, dry_run=False)
    preview = _build_per_org_plan(org, global_plan, dry_run=True)

    assert live.to_create == []
    assert live.existing == [org]
    assert preview.to_create == [org]


def test_orphaned_attachment_folders_require_follow_up(
    tmp_path: Path, monkeypatch
) -> None:
    from itglue_migrate import cli

    validation = type(
        "Validation",
        (),
        {"to_dict": lambda self: {"total_orphaned_folders": 2, "orphaned": []}},
    )()
    monkeypatch.setattr(cli, "validate_attachments", lambda *_args, **_kwargs: validation)
    monkeypatch.setattr(cli, "collect_embedded_image_references", lambda *_args: [])
    monkeypatch.setattr(
        cli,
        "verify_embedded_images",
        lambda *_args: type(
            "Images",
            (),
            {"failures": [], "expected_count": 0, "present_count": 0},
        )(),
    )

    summary = _build_attachment_validation_summary(
        tmp_path,
        configurations=[],
        locations=[],
        documents=[],
        passwords=[],
        custom_assets=[],
    )
    report = ReconciliationReport.create(export_path=tmp_path, target="all", dry_run=True)
    report.organizations.append(
        OrganizationReconciliation(
            name="Acme",
            itglue_id="1",
            bifrost_id="org-1",
            dry_run=True,
            entities=build_plan_counts(SyncPlan()),
            attachment_summary=summary,
        )
    )

    assert summary["orphaned_folders"] == 2
    assert report.summary()["follow_up_required"] is True


def test_attachment_summary_carries_broken_image_mismatch(tmp_path: Path) -> None:
    """Broken embedded images must appear as mismatch counts in the report."""
    _write_doc_with_image(tmp_path, "missing.png")
    documents = [{"id": "200", "name": "HTML Document", "organization_id": "1"}]

    summary = _build_attachment_validation_summary(
        tmp_path,
        configurations=[],
        locations=[],
        documents=documents,
        passwords=[],
        custom_assets=[],
    )

    assert summary["failure_categories"] == {BROKEN_EMBEDDED_IMAGE: 1}
    embedded = summary["embedded_images"]
    assert embedded["expected_count"] == 1
    assert embedded["present_count"] == 0
    assert embedded["failure_count"] == 1
    assert embedded["failures"][0]["category"] == BROKEN_EMBEDDED_IMAGE
    assert embedded["failures"][0]["document_id"] == "200"


def test_attachment_summary_clean_images_keep_follow_up_clear(
    tmp_path: Path,
) -> None:
    """Present images must not force operator follow-up; broken ones must."""
    doc_dir = tmp_path / "documents" / "DOC-1-200 HTML Document"
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "present.png").write_bytes(b"PNG")
    _write_doc_with_image(tmp_path, "present.png")
    documents = [{"id": "200", "name": "HTML Document", "organization_id": "1"}]

    clean = _build_attachment_validation_summary(
        tmp_path,
        configurations=[],
        locations=[],
        documents=documents,
        passwords=[],
        custom_assets=[],
    )
    assert clean["embedded_images"]["failure_count"] == 0

    clean_report = ReconciliationReport.create(
        export_path=tmp_path, target="all", dry_run=True
    )
    clean_report.organizations.append(
        OrganizationReconciliation(
            name="Acme",
            itglue_id="1",
            bifrost_id="org-1",
            dry_run=True,
            entities=build_plan_counts(SyncPlan()),
            attachment_summary=clean,
        )
    )
    assert clean_report.summary()["follow_up_required"] is False

    (doc_dir / "present.png").unlink()
    broken = _build_attachment_validation_summary(
        tmp_path,
        configurations=[],
        locations=[],
        documents=documents,
        passwords=[],
        custom_assets=[],
    )
    broken_report = ReconciliationReport.create(
        export_path=tmp_path, target="all", dry_run=True
    )
    broken_report.organizations.append(
        OrganizationReconciliation(
            name="Acme",
            itglue_id="1",
            bifrost_id="org-1",
            dry_run=True,
            entities=build_plan_counts(SyncPlan()),
            attachment_summary=broken,
        )
    )
    assert broken_report.summary()["follow_up_required"] is True
