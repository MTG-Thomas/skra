"""Regression coverage for duplicate-safe organization name uniqueness."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260128_100000_add_unique_organization_name.py"
)


def load_migration() -> object:
    spec = importlib.util.spec_from_file_location(
        "unique_organization_name_migration", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_disambiguates_duplicates_before_unique_index() -> None:
    module = load_migration()
    mock_op = MagicMock()
    calls: list[str] = []
    mock_op.execute.side_effect = lambda *_args, **_kwargs: calls.append("execute")
    mock_op.drop_index.side_effect = lambda *_args, **_kwargs: calls.append("drop")
    mock_op.create_index.side_effect = lambda *_args, **_kwargs: calls.append("create")

    with patch.object(module, "op", mock_op):
        module.upgrade()

    sql = mock_op.execute.call_args.args[0]
    assert "ROW_NUMBER() OVER" in sql
    assert "ranked.duplicate_number > 1" in sql
    assert "LEFT(ranked.name, 207)" in sql
    assert "organization.id::text" in sql
    assert calls == ["execute", "drop", "create"]
    assert mock_op.create_index.call_args.kwargs["unique"] is True
