"""Console rendering of the relationship audit breakdown (issue #25)."""

from __future__ import annotations

from itglue_migrate.cli import _display_sync_result
from itglue_migrate.sync_executor import SyncResult


def _result_with_relationships() -> SyncResult:
    return SyncResult(
        created={"relationships": 2},
        skipped={"relationships": 3},
        failed={"relationships": 1},
        relationship_summary={
            "created": 2,
            "skipped": 1,
            "duplicate": 2,
            "failed": 1,
            "missing_source": 1,
            "missing_target": 0,
            "transient_error": 1,
        },
    )


def test_display_sync_result_shows_relationship_breakdown(
    capsys: object,
) -> None:
    """The operator table must expose duplicate/missing/transient counts."""
    _display_sync_result(_result_with_relationships())

    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "Relationship detail" in out
    assert "duplicate" in out
    assert "missing_source" in out
    assert "transient_error" in out


def test_display_sync_result_omits_breakdown_without_relationships(
    capsys: object,
) -> None:
    """No relationship activity means no extra section."""
    _display_sync_result(SyncResult(created={"configurations": 1}))

    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "Relationship detail" not in out
