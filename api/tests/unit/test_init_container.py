"""Required startup migration/backfill orchestration contracts."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/init_container.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("init_container", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_runs_projection_backfill_after_migrations(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    calls: list[str] = []
    monkeypatch.setattr(module, "run_migrations", lambda: calls.append("migrate") or True)
    monkeypatch.setattr(
        module,
        "run_expiration_projection_backfill",
        lambda: calls.append("backfill") or True,
    )

    assert module.main() == 0
    assert calls == ["migrate", "backfill"]


def test_main_fails_closed_when_projection_backfill_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "run_migrations", lambda: True)
    monkeypatch.setattr(module, "run_expiration_projection_backfill", lambda: False)

    assert module.main() == 1


def test_projection_backfill_invokes_rerunnable_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    seen: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen["command"] = command
        seen.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="complete", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.run_expiration_projection_backfill() is True
    assert seen["command"] == [
        sys.executable,
        "-m",
        "scripts.backfill_expiration_projections",
    ]
    assert seen["check"] is True
    assert seen["timeout"] == 1800


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.TimeoutExpired("backfill", 1800),
        subprocess.CalledProcessError(1, "backfill"),
        FileNotFoundError("python"),
    ],
)
def test_projection_backfill_failure_blocks_startup(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    module = _load_module()

    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise failure

    monkeypatch.setattr(module.subprocess, "run", fail)

    assert module.run_expiration_projection_backfill() is False


def test_projection_backfill_logs_subprocess_output(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    module = _load_module()

    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise subprocess.CalledProcessError(
            1,
            "backfill",
            output="partial progress",
            stderr="database rejected projection",
        )

    monkeypatch.setattr(module.subprocess, "run", fail)

    assert module.run_expiration_projection_backfill() is False
    assert "database rejected projection" in caplog.text
    assert "partial progress" in caplog.text
