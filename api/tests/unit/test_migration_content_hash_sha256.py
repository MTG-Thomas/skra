"""Migration assertions for content_hash SHA-256 widening (refs #134).

The downgrade shrinks VARCHAR(64) back to VARCHAR(32) while rows hold
64-char SHA-256 hashes. PostgreSQL rejects that rewrite unless each
content_hash is first recomputed as MD5 from the stored plaintext
searchable_text (non-nullable Text column).
"""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260920_100001_widen_content_hash_sha256.py"
)


def load_migration() -> object:
    """Load the migration module without Alembic context."""
    spec = importlib.util.spec_from_file_location("content_hash_sha256_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestContentHashMigration:
    """Downgrade must backfill MD5 hashes before shrinking the column."""

    def test_downgrade_backfills_md5_before_shrink(self) -> None:
        """UPDATE ... md5(searchable_text) must precede the alter_column."""
        module = load_migration()
        mock_op = MagicMock()
        calls: list[str] = []
        mock_op.execute.side_effect = lambda *a, **k: calls.append("execute")
        mock_op.alter_column.side_effect = lambda *a, **k: calls.append("alter_column")

        with patch.object(module, "op", mock_op):
            module.downgrade()

        mock_op.execute.assert_called_once_with(
            "UPDATE embedding_index SET content_hash = md5(searchable_text)"
        )
        assert calls == ["execute", "alter_column"]

    def test_upgrade_widens_to_64(self) -> None:
        """Upgrade must widen the column to VARCHAR(64)."""
        import sqlalchemy as sa

        module = load_migration()
        mock_op = MagicMock()

        with patch.object(module, "op", mock_op):
            module.upgrade()

        _, kwargs = mock_op.alter_column.call_args
        assert isinstance(kwargs["type_"], sa.String)
        assert kwargs["type_"].length == 64
