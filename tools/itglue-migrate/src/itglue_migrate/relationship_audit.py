"""Pure helpers for auditing relationship sync outcomes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class RelationshipAuditStatus(StrEnum):
    """Relationship audit outcome categories."""

    CREATED = "created"
    SKIPPED = "skipped"
    DUPLICATE_EXISTING = "duplicate_existing"
    FAILED = "failed"
    MISSING_SOURCE = "missing_source"
    MISSING_TARGET = "missing_target"
    TRANSIENT_ERROR = "transient_error"


COUNT_KEYS: tuple[str, ...] = (
    "created",
    "skipped",
    "duplicate",
    "failed",
    "missing_source",
    "missing_target",
    "transient_error",
)

_STATUS_COUNT_KEYS: dict[RelationshipAuditStatus, str] = {
    RelationshipAuditStatus.CREATED: "created",
    RelationshipAuditStatus.SKIPPED: "skipped",
    RelationshipAuditStatus.DUPLICATE_EXISTING: "duplicate",
    RelationshipAuditStatus.FAILED: "failed",
    RelationshipAuditStatus.MISSING_SOURCE: "missing_source",
    RelationshipAuditStatus.MISSING_TARGET: "missing_target",
    RelationshipAuditStatus.TRANSIENT_ERROR: "transient_error",
}


@dataclass(frozen=True)
class RelationshipAuditResult:
    """Classified relationship outcome for reconciliation reporting."""

    status: RelationshipAuditStatus
    relationship: Mapping[str, Any]
    source_type: str
    source_id: str | None
    target_type: str
    target_id: str | None
    relationship_key: str | None = None
    error: str | None = None
    reason: str | None = None

    @property
    def count_key(self) -> str:
        """Return the reconciliation JSON counter bucket for this outcome."""
        return _STATUS_COUNT_KEYS[self.status]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation of the audit result."""
        return {
            "status": self.status.value,
            "count_key": self.count_key,
            "relationship_key": self.relationship_key,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "error": self.error,
            "reason": self.reason,
        }


def relationship_key(
    source_type: str,
    source_id: str,
    target_type: str,
    target_id: str,
) -> str:
    """Build the ExistingState.relationships key format."""
    return f"{source_type}:{source_id}:{target_type}:{target_id}"


def classify_relationship(
    relationship: Mapping[str, Any],
    *,
    existing_relationship_keys: Iterable[str],
    resolved_ids: Mapping[str, str] | None = None,
    operation: str | RelationshipAuditStatus | None = None,
    error: BaseException | str | None = None,
    reason: str | None = None,
) -> RelationshipAuditResult:
    """Classify a relationship sync outcome.

    Relationship dictionaries may contain resolved UUID fields (``source_id`` or
    ``target_id``) and/or ITGlue IDs (``source_itglue_id`` or
    ``target_itglue_id``) matching ``SyncPlan.relationships.to_create`` entries.
    ``resolved_ids`` can supply run-time ITGlue ID to UUID mappings.
    ``reason`` overrides the synthesized actionable reason; when omitted, a
    default reason is derived from the outcome so skips are auditable.
    """
    resolved_ids = resolved_ids or {}
    source_type = str(relationship.get("source_type") or "")
    target_type = str(relationship.get("target_type") or "")
    source_id = _resolve_id(relationship, "source", resolved_ids)
    target_id = _resolve_id(relationship, "target", resolved_ids)
    existing_keys = set(existing_relationship_keys)
    key = (
        relationship_key(source_type, source_id, target_type, target_id)
        if source_id and target_id
        else None
    )

    status: RelationshipAuditStatus
    error_text = _error_text(error)

    if key and _relationship_already_exists(key, source_type, source_id, target_type, target_id, existing_keys):
        status = RelationshipAuditStatus.DUPLICATE_EXISTING
    elif _is_duplicate_error(error):
        status = RelationshipAuditStatus.DUPLICATE_EXISTING
    elif not source_id:
        status = RelationshipAuditStatus.MISSING_SOURCE
    elif not target_id:
        status = RelationshipAuditStatus.MISSING_TARGET
    elif error is not None and _is_transient_error(error):
        status = RelationshipAuditStatus.TRANSIENT_ERROR
    elif error is not None:
        status = RelationshipAuditStatus.FAILED
    elif _normalize_operation(operation) is RelationshipAuditStatus.SKIPPED:
        status = RelationshipAuditStatus.SKIPPED
    else:
        status = RelationshipAuditStatus.CREATED

    if reason is None:
        reason = _default_reason(
            status,
            relationship=relationship,
            source_type=source_type,
            target_type=target_type,
            relationship_key=key,
            error_text=error_text,
        )

    return RelationshipAuditResult(
        status=status,
        relationship=relationship,
        source_type=source_type,
        source_id=source_id,
        target_type=target_type,
        target_id=target_id,
        relationship_key=key,
        error=error_text,
        reason=reason,
    )


def _default_reason(
    status: RelationshipAuditStatus,
    *,
    relationship: Mapping[str, Any],
    source_type: str,
    target_type: str,
    relationship_key: str | None,
    error_text: str | None,
) -> str | None:
    """Synthesize an actionable reason for a relationship outcome."""
    if status is RelationshipAuditStatus.CREATED:
        return None
    if status is RelationshipAuditStatus.MISSING_SOURCE:
        ref = _side_reference(relationship, "source")
        return (
            f"source {source_type or 'entity'} ({ref}) has no migrated UUID; "
            "sync the source entity first, then re-run relationship sync"
        )
    if status is RelationshipAuditStatus.MISSING_TARGET:
        ref = _side_reference(relationship, "target")
        return (
            f"target {target_type or 'entity'} ({ref}) has no migrated UUID; "
            "sync the target entity first, then re-run relationship sync"
        )
    if status is RelationshipAuditStatus.DUPLICATE_EXISTING:
        return (
            f"link {relationship_key or 'unknown'} already exists; "
            "no action needed on resume"
        )
    if status is RelationshipAuditStatus.TRANSIENT_ERROR:
        detail = f": {error_text}" if error_text else ""
        return f"transient error{detail}; safe to retry on resume"
    if status is RelationshipAuditStatus.FAILED:
        detail = f": {error_text}" if error_text else ""
        return f"create request failed{detail}; inspect the error and re-run"
    return "skipped before create attempt"


def _side_reference(relationship: Mapping[str, Any], side: str) -> str:
    """Return the most identifying reference for an unresolved link side."""
    direct = relationship.get(f"{side}_id")
    if direct:
        return str(direct)
    itglue_id = relationship.get(f"{side}_itglue_id")
    if itglue_id:
        return f"itglue:{itglue_id}"
    return "unknown"


def summarize_relationship_audit(
    audit_results: Iterable[RelationshipAuditResult | Mapping[str, Any]],
) -> dict[str, int]:
    """Count classified relationship audit results for reconciliation JSON."""
    counts = dict.fromkeys(COUNT_KEYS, 0)
    for result in audit_results:
        if isinstance(result, RelationshipAuditResult):
            count_key = result.count_key
        else:
            count_key = str(result.get("count_key") or "")
        if count_key in counts:
            counts[count_key] += 1
    return counts


def _resolve_id(
    relationship: Mapping[str, Any],
    side: str,
    resolved_ids: Mapping[str, str],
) -> str | None:
    direct_id = relationship.get(f"{side}_id")
    if direct_id:
        return str(direct_id)

    itglue_id = relationship.get(f"{side}_itglue_id")
    if itglue_id and str(itglue_id) in resolved_ids:
        return str(resolved_ids[str(itglue_id)])

    return None


def _relationship_already_exists(
    key: str,
    source_type: str,
    source_id: str,
    target_type: str,
    target_id: str,
    existing_keys: set[str],
) -> bool:
    reverse_key = relationship_key(target_type, target_id, source_type, source_id)
    return key in existing_keys or reverse_key in existing_keys


def _normalize_operation(
    operation: str | RelationshipAuditStatus | None,
) -> RelationshipAuditStatus | None:
    if isinstance(operation, RelationshipAuditStatus):
        return operation
    if not operation:
        return None

    normalized = operation.lower()
    if normalized == RelationshipAuditStatus.SKIPPED.value:
        return RelationshipAuditStatus.SKIPPED
    if normalized == RelationshipAuditStatus.CREATED.value:
        return RelationshipAuditStatus.CREATED
    return None


def _error_text(error: BaseException | str | None) -> str | None:
    if error is None:
        return None
    return str(error)


def _is_duplicate_error(error: BaseException | str | None) -> bool:
    return _error_status_code(error) == 409


def _is_transient_error(error: BaseException | str | None) -> bool:
    if isinstance(error, TimeoutError):
        return True

    status_code = _error_status_code(error)
    if status_code in {408, 429}:
        return True
    if status_code is not None and 500 <= status_code <= 599:
        return True

    message = str(error).lower()
    transient_terms = ("timeout", "timed out", "rate limit", "temporarily", "unavailable")
    return any(term in message for term in transient_terms)


def _error_status_code(error: BaseException | str | None) -> int | None:
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    return None
