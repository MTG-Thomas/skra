"""Tests for relationship audit classification helpers."""

from __future__ import annotations

from itglue_migrate.relationship_audit import (
    RelationshipAuditStatus,
    classify_relationship,
    summarize_relationship_audit,
)


def relationship(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "source_type": "password",
        "source_id": "pwd-uuid-1",
        "source_itglue_id": "pwd-1",
        "target_type": "configuration",
        "target_id": "cfg-uuid-1",
        "target_itglue_id": "cfg-1",
    }
    data.update(overrides)
    return data


def test_classify_duplicate_when_relationship_key_already_exists() -> None:
    audit = classify_relationship(
        relationship(),
        existing_relationship_keys={"password:pwd-uuid-1:configuration:cfg-uuid-1"},
    )

    assert audit.status is RelationshipAuditStatus.DUPLICATE_EXISTING
    assert audit.count_key == "duplicate"
    assert audit.relationship_key == "password:pwd-uuid-1:configuration:cfg-uuid-1"


def test_classify_missing_source_when_source_id_cannot_be_resolved() -> None:
    audit = classify_relationship(
        relationship(source_id=None, source_itglue_id="missing-pwd"),
        existing_relationship_keys=set(),
        resolved_ids={"cfg-1": "cfg-uuid-1"},
    )

    assert audit.status is RelationshipAuditStatus.MISSING_SOURCE
    assert audit.count_key == "missing_source"
    assert audit.source_id is None


def test_classify_missing_target_when_target_id_cannot_be_resolved() -> None:
    audit = classify_relationship(
        relationship(target_id=None, target_itglue_id="missing-cfg"),
        existing_relationship_keys=set(),
        resolved_ids={"pwd-1": "pwd-uuid-1"},
    )

    assert audit.status is RelationshipAuditStatus.MISSING_TARGET
    assert audit.count_key == "missing_target"
    assert audit.target_id is None


def test_classify_failed_api_error() -> None:
    audit = classify_relationship(
        relationship(),
        existing_relationship_keys=set(),
        error=ValueError("validation failed"),
    )

    assert audit.status is RelationshipAuditStatus.FAILED
    assert audit.count_key == "failed"
    assert audit.error == "validation failed"


def test_summarize_relationship_audit_counts_mixed_statuses() -> None:
    audits = [
        classify_relationship(
            relationship(target_id="cfg-created"),
            existing_relationship_keys=set(),
            operation="created",
        ),
        classify_relationship(
            relationship(target_id="cfg-existing"),
            existing_relationship_keys={"password:pwd-uuid-1:configuration:cfg-existing"},
        ),
        classify_relationship(
            relationship(source_id=None, source_itglue_id="missing-pwd"),
            existing_relationship_keys=set(),
        ),
        classify_relationship(
            relationship(target_id=None, target_itglue_id="missing-cfg"),
            existing_relationship_keys=set(),
        ),
        classify_relationship(
            relationship(target_id="cfg-failed"),
            existing_relationship_keys=set(),
            error=RuntimeError("boom"),
        ),
        classify_relationship(
            relationship(target_id="cfg-transient"),
            existing_relationship_keys=set(),
            error=TimeoutError("timed out"),
        ),
        classify_relationship(
            relationship(target_id="cfg-skipped"),
            existing_relationship_keys=set(),
            operation="skipped",
        ),
    ]

    assert summarize_relationship_audit(audits) == {
        "created": 1,
        "skipped": 1,
        "duplicate": 1,
        "failed": 1,
        "missing_source": 1,
        "missing_target": 1,
        "transient_error": 1,
    }


def test_summarize_relationship_audit_accepts_serialized_results() -> None:
    audit = classify_relationship(
        relationship(),
        existing_relationship_keys=set(),
    )

    summary = summarize_relationship_audit([audit.to_dict()])

    assert summary["created"] == 1


def test_missing_source_reason_names_itglue_id_and_next_step() -> None:
    audit = classify_relationship(
        relationship(source_id=""),
        existing_relationship_keys=set(),
    )

    assert audit.status is RelationshipAuditStatus.MISSING_SOURCE
    assert audit.reason is not None
    assert "pwd-1" in audit.reason
    assert "re-run" in audit.reason


def test_missing_target_reason_names_itglue_id_and_next_step() -> None:
    audit = classify_relationship(
        relationship(target_id=""),
        existing_relationship_keys=set(),
    )

    assert audit.status is RelationshipAuditStatus.MISSING_TARGET
    assert audit.reason is not None
    assert "cfg-1" in audit.reason
    assert "re-run" in audit.reason


def test_duplicate_reason_names_link_key() -> None:
    audit = classify_relationship(
        relationship(),
        existing_relationship_keys={"password:pwd-uuid-1:configuration:cfg-uuid-1"},
    )

    assert audit.status is RelationshipAuditStatus.DUPLICATE_EXISTING
    assert audit.reason is not None
    assert "password:pwd-uuid-1:configuration:cfg-uuid-1" in audit.reason


def test_transient_error_reason_says_retry() -> None:
    audit = classify_relationship(
        relationship(),
        existing_relationship_keys=set(),
        error=TimeoutError("timed out"),
    )

    assert audit.status is RelationshipAuditStatus.TRANSIENT_ERROR
    assert audit.reason is not None
    assert "retry" in audit.reason.lower()


def test_explicit_reason_overrides_default() -> None:
    audit = classify_relationship(
        relationship(target_id=""),
        existing_relationship_keys=set(),
        reason="operator skipped: out of scope for cutover",
    )

    assert audit.status is RelationshipAuditStatus.MISSING_TARGET
    assert audit.reason == "operator skipped: out of scope for cutover"


def test_created_result_has_no_reason_but_serializes_key() -> None:
    audit = classify_relationship(
        relationship(),
        existing_relationship_keys=set(),
    )

    assert audit.status is RelationshipAuditStatus.CREATED
    assert audit.reason is None
    payload = audit.to_dict()
    assert payload["reason"] is None
    assert payload["count_key"] == "created"
