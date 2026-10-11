from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPOSITORY_ROOT / ".zap" / "redact_output.py"
SPEC = importlib.util.spec_from_file_location("redact_output", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
redact_output = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(redact_output)

HOOK_MODULE_PATH = REPOSITORY_ROOT / ".zap" / "auth_header_hook.py"
HOOK_SPEC = importlib.util.spec_from_file_location("auth_header_hook", HOOK_MODULE_PATH)
assert HOOK_SPEC is not None and HOOK_SPEC.loader is not None
auth_header_hook = importlib.util.module_from_spec(HOOK_SPEC)
HOOK_SPEC.loader.exec_module(auth_header_hook)


def test_auth_header_hook_adds_rule_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ZAP_AUTH_HEADER_VALUE", "Bearer sensitive-token")
    zap = Mock()

    auth_header_hook.zap_started(zap, "https://example.test/openapi.json")

    zap.replacer.add_rule.assert_called_once_with(
        description="auth-header",
        enabled=True,
        matchtype="REQ_HEADER",
        matchregex=False,
        matchstring="Authorization",
        replacement="Bearer sensitive-token",
    )


def test_auth_header_hook_fails_closed_without_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ZAP_AUTH_HEADER_VALUE", raising=False)

    with pytest.raises(RuntimeError, match="ZAP_AUTH_HEADER_VALUE is required"):
        auth_header_hook.zap_started(Mock(), "https://example.test/openapi.json")


def test_create_safe_artifacts_redacts_reports_and_console(tmp_path: Path) -> None:
    secret = b"sensitive-token"
    source = tmp_path / "raw"
    source.mkdir()
    (source / "report.json").write_bytes(
        b'{"header":"Bearer sensitive-token","token":"sensitive-token"}'
    )
    console_source = tmp_path / "raw-console.log"
    console_source.write_bytes(b"request Authorization: Bearer sensitive-token")

    destination = tmp_path / "safe"
    console_destination = tmp_path / "safe-console.log"
    redact_output.create_safe_artifacts(
        source, destination, console_source, console_destination, secret
    )

    report = (destination / "report.json").read_bytes()
    console = console_destination.read_bytes()
    assert secret not in report
    assert secret not in console
    assert report.count(redact_output.REDACTION) == 2
    assert redact_output.REDACTION in console


def test_create_safe_artifacts_rejects_generated_symlinks(tmp_path: Path) -> None:
    source = tmp_path / "raw"
    source.mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("outside")
    (source / "report.html").symlink_to(target)
    console_source = tmp_path / "console.log"
    console_source.write_text("clean")

    destination = tmp_path / "safe"
    with pytest.raises(ValueError, match="non-regular"):
        redact_output.create_safe_artifacts(
            source,
            destination,
            console_source,
            tmp_path / "safe-console.log",
            b"secret",
        )

    assert not destination.exists()


def test_redact_bytes_rejects_empty_secret() -> None:
    with pytest.raises(ValueError, match="empty secret"):
        redact_output.redact_bytes(b"content", b"")
