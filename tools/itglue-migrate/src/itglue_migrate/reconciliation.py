"""Reconciliation report models for IT Glue migration rehearsals."""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from itglue_migrate.sync_differ import SyncPlan
    from itglue_migrate.sync_executor import SyncResult


ENTITY_TYPES = (
    "organizations",
    "config_types",
    "config_statuses",
    "custom_asset_types",
    "locations",
    "configurations",
    "custom_assets",
    "documents",
    "passwords",
    "relationships",
)


@dataclass
class EntityReconciliation:
    """Counts for one entity type in a migration reconciliation report."""

    planned_create: int = 0
    planned_update: int = 0
    existing: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    duplicate: int = 0
    failed: int = 0
    errors: int = 0

    def to_dict(self) -> dict[str, int]:
        """Convert to JSON-safe dict."""
        return {
            "planned_create": self.planned_create,
            "planned_update": self.planned_update,
            "existing": self.existing,
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "duplicate": self.duplicate,
            "failed": self.failed,
            "errors": self.errors,
        }


@dataclass
class OrganizationReconciliation:
    """Reconciliation section for one organization."""

    name: str
    itglue_id: str
    skra_id: str | None = None
    dry_run: bool = False
    entities: dict[str, EntityReconciliation] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    attachment_summary: dict[str, Any] | None = None
    relationship_summary: dict[str, Any] | None = None
    relationship_audit: list[dict[str, Any]] | None = None
    # Deprecated alias for skra_id (pre-rename callers, e.g. plan files).
    bifrost_id: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.bifrost_id is not None:
            warnings.warn(
                "bifrost_id is deprecated, use skra_id instead",
                DeprecationWarning,
                stacklevel=2,
            )
            if self.skra_id is None:
                self.skra_id = self.bifrost_id

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-safe dict."""
        return {
            "name": self.name,
            "itglue_id": self.itglue_id,
            "skra_id": self.skra_id,
            "dry_run": self.dry_run,
            "entities": {
                entity_type: counts.to_dict()
                for entity_type, counts in sorted(self.entities.items())
            },
            "warnings": self.warnings,
            "errors": self.errors,
            "attachment_summary": self.attachment_summary,
            "relationship_summary": self.relationship_summary,
            "relationship_audit": self.relationship_audit,
        }


@dataclass
class ReconciliationReport:
    """Top-level migration reconciliation artifact."""

    generated_at: str
    export_path: str
    target: str
    dry_run: bool
    organizations: list[OrganizationReconciliation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        export_path: Path,
        target: str,
        dry_run: bool,
        generated_at: str | None = None,
    ) -> ReconciliationReport:
        """Create a report with generated metadata.

        Pass ``generated_at`` to pin the timestamp (tests, byte-stable
        fixtures, and report-to-report comparisons). When omitted the
        current UTC time is used, which is the only nondeterministic
        field in the serialized report.
        """
        return cls(
            generated_at=(
                generated_at
                if generated_at is not None
                else datetime.now(UTC).isoformat()
            ),
            export_path=str(export_path),
            target=target,
            dry_run=dry_run,
        )

    def summary(self) -> dict[str, Any]:
        """Build aggregate operator summary counts."""
        totals = {entity_type: EntityReconciliation() for entity_type in ENTITY_TYPES}
        warning_count = len(self.warnings)
        error_count = len(self.errors)

        for org in self.organizations:
            warning_count += len(org.warnings)
            error_count += len(org.errors)
            for entity_type, counts in org.entities.items():
                aggregate = totals.setdefault(entity_type, EntityReconciliation())
                aggregate.planned_create += counts.planned_create
                aggregate.planned_update += counts.planned_update
                aggregate.existing += counts.existing
                aggregate.created += counts.created
                aggregate.updated += counts.updated
                aggregate.skipped += counts.skipped
                aggregate.duplicate += counts.duplicate
                aggregate.failed += counts.failed
                aggregate.errors += counts.errors

        failed_total = sum(counts.failed for counts in totals.values())
        skipped_total = sum(counts.skipped for counts in totals.values())
        follow_up_required = (
            failed_total > 0
            or error_count > 0
            or any(
                _attachment_follow_up_required(org.attachment_summary)
                for org in self.organizations
            )
            or any(
                _relationship_follow_up_required(org.relationship_summary)
                for org in self.organizations
            )
        )

        return {
            "organization_count": len(self.organizations),
            "warning_count": warning_count,
            "error_count": error_count,
            "failed_count": failed_total,
            "skipped_count": skipped_total,
            "follow_up_required": follow_up_required,
            "entities": {
                entity_type: counts.to_dict()
                for entity_type, counts in sorted(totals.items())
            },
        }

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-safe dict."""
        return {
            "schema_version": 1,
            "generated_at": self.generated_at,
            "export_path": self.export_path,
            "target": self.target,
            "dry_run": self.dry_run,
            "summary": self.summary(),
            "organizations": [org.to_dict() for org in self.organizations],
            "warnings": self.warnings,
            "errors": self.errors,
        }

    def write_json(self, path: Path) -> None:
        """Write the report as stable, pretty JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def build_plan_counts(plan: SyncPlan) -> dict[str, EntityReconciliation]:
    """Build reconciliation counts from a sync plan."""
    mapping = {
        "organizations": plan.organizations,
        "config_types": plan.config_types,
        "config_statuses": plan.config_statuses,
        "custom_asset_types": plan.custom_asset_types,
        "locations": plan.locations,
        "configurations": plan.configurations,
        "custom_assets": plan.custom_assets,
        "documents": plan.documents,
    }

    counts: dict[str, EntityReconciliation] = {}
    for entity_type, entity_plan in mapping.items():
        counts[entity_type] = EntityReconciliation(
            planned_create=len(entity_plan.to_create),
            planned_update=len(entity_plan.to_update),
            existing=len(entity_plan.existing),
            skipped=len(entity_plan.skipped),
        )

    counts["passwords"] = EntityReconciliation(
        planned_create=len(plan.passwords.to_create)
        + len(plan.passwords.cell_writes)
        + len(plan.passwords.row_creates),
        planned_update=len(plan.passwords.to_update),
        existing=len(plan.passwords.existing),
    )
    counts["relationships"] = EntityReconciliation(
        planned_create=len(plan.relationships.to_create),
        existing=len(plan.relationships.existing),
        duplicate=len(plan.relationships.existing),
    )
    return counts


def apply_result_counts(
    counts: dict[str, EntityReconciliation],
    result: SyncResult,
) -> dict[str, EntityReconciliation]:
    """Overlay execution result counts onto plan reconciliation counts."""
    for entity_type in ENTITY_TYPES:
        counts.setdefault(entity_type, EntityReconciliation())

    for entity_type, value in result.created.items():
        counts.setdefault(entity_type, EntityReconciliation()).created = value
    for entity_type, value in result.updated.items():
        counts.setdefault(entity_type, EntityReconciliation()).updated = value
    for entity_type, value in result.skipped.items():
        counts.setdefault(entity_type, EntityReconciliation()).skipped += value
    for entity_type, value in result.failed.items():
        counts.setdefault(entity_type, EntityReconciliation()).failed = value
        counts[entity_type].errors += value

    relationship_summary = result.relationship_summary or {}
    counts["relationships"].duplicate = int(relationship_summary.get("duplicate", 0))

    return counts


def _attachment_follow_up_required(summary: dict[str, Any] | None) -> bool:
    """Return true when attachment verification found operator-actionable issues."""
    if not summary:
        return False

    failure_categories = summary.get("failure_categories", {})
    orphaned_folders = int(summary.get("orphaned_folders", 0) or 0)
    return orphaned_folders > 0 or any(
        int(value or 0) > 0 for value in failure_categories.values()
    )


def _relationship_follow_up_required(summary: dict[str, Any] | None) -> bool:
    """Return true when relationship audit found actionable non-success outcomes."""
    if not summary:
        return False

    follow_up_keys = {
        "failed",
        "missing_source",
        "missing_target",
        "transient_error",
    }
    return any(int(summary.get(key, 0) or 0) > 0 for key in follow_up_keys)
