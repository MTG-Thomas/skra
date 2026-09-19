"""Unit tests for scripts/garage-init.sh fail-open behavior (issue #98).

Runs the real init script against a stub Garage admin API over local HTTP:
happy path, invalid credential formats, import/allow rejections, the
post-grant permission confirmation, idempotent reruns, and secret redaction.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "garage-init.sh"
NODE_ID = "8a9d31ecd543f98562fe74583782ef4bd5492a7abfe3e8e0f2ae63fac158700d"
BUCKET_ID = "4110a5b90612fc800f3277b37ece51c149a0a6abd1348cf4d3cb50cb68a099b4"
VALID_KEY_ID = "GK731dc147d0c5b0fcb188d4d8"
VALID_SECRET = "0123456789abcdef" * 4


class StubState:
    """Scripted Garage admin API behavior plus a call log."""

    def __init__(self) -> None:
        self.grants: dict[str, dict[str, bool]] = {}
        self.imported: set[str] = set()
        self.calls: list[str] = []
        self.import_status = 200
        self.import_body: dict[str, Any] | None = None
        self.allow_status = 200
        self.allow_body: dict[str, Any] | None = None
        self.record_allow = True


def make_handler(state: StubState) -> type[BaseHTTPRequestHandler]:
    """Build a request handler bound to stub state."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def _send(self, status: int, body: Any) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _read_json(self) -> Any:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length) or b"{}")

        def do_GET(self) -> None:
            if self.path == "/v1/health":
                self._send(200, {})
            elif self.path == "/v1/status":
                self._send(200, {"node": NODE_ID})
            elif self.path.startswith("/v1/bucket"):
                keys = [
                    {
                        "accessKeyId": key_id,
                        "name": "bifrost-docs-key",
                        "permissions": perms,
                    }
                    for key_id, perms in state.grants.items()
                ]
                self._send(
                    200,
                    {
                        "id": BUCKET_ID,
                        "globalAliases": ["bifrost-docs"],
                        "keys": keys,
                        "objects": 0,
                    },
                )
            else:
                self._send(404, {})

        def do_POST(self) -> None:
            if self.path in ("/v1/layout", "/v1/layout/apply"):
                self._read_json()
                self._send(200, {})
            elif self.path == "/v1/bucket":
                self._read_json()
                self._send(200, {"id": BUCKET_ID})
            elif self.path == "/v1/key/import":
                payload = self._read_json()
                state.calls.append("import")
                if state.import_status != 200:
                    body = state.import_body or {
                        "code": "InvalidRequest",
                        "message": "stubbed import failure",
                    }
                    self._send(state.import_status, body)
                else:
                    state.imported.add(payload.get("accessKeyId", ""))
                    self._send(200, state.import_body or {})
            elif self.path == "/v1/bucket/allow":
                payload = self._read_json()
                state.calls.append("allow")
                if payload.get("accessKeyId") not in state.imported:
                    self._send(
                        400,
                        {"code": "InvalidRequest", "message": "unknown key"},
                    )
                elif state.allow_status != 200:
                    body = state.allow_body or {
                        "code": "InvalidRequest",
                        "message": "stubbed allow failure",
                    }
                    self._send(state.allow_status, body)
                else:
                    if state.record_allow:
                        state.grants[payload["accessKeyId"]] = payload["permissions"]
                    self._send(200, state.allow_body or {})
            else:
                self._send(404, {})

    return Handler


@pytest.fixture
def stub_api() -> Any:
    """Run a stub Garage admin API on localhost; yield (url, state)."""
    state = StubState()
    server = HTTPServer(("127.0.0.1", 0), make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", state
    server.shutdown()
    thread.join()


def run_script(url: str, key_id: str, secret: str) -> subprocess.CompletedProcess[str]:
    """Run garage-init.sh against the stub API."""
    env = {
        **os.environ,
        "GARAGE_ADMIN_URL": url,
        "GARAGE_ADMIN_TOKEN": "test-admin-token",
        "GARAGE_ACCESS_KEY_ID": key_id,
        "GARAGE_SECRET_ACCESS_KEY": secret,
    }
    return subprocess.run(["sh", str(SCRIPT)], capture_output=True, text=True, timeout=60, env=env)


def assert_secret_absent(result: subprocess.CompletedProcess[str], secret: str) -> None:
    assert secret not in result.stdout
    assert secret not in result.stderr


FULL_PERMS = {"read": True, "write": True, "owner": True}


def test_success_imports_grants_and_verifies(stub_api: Any) -> None:
    url, state = stub_api
    result = run_script(url, VALID_KEY_ID, VALID_SECRET)

    assert result.returncode == 0, result.stderr
    assert "Key verified with read/write/owner" in result.stdout
    assert state.calls == ["import", "allow"]
    assert state.grants[VALID_KEY_ID] == FULL_PERMS
    assert_secret_absent(result, VALID_SECRET)


def test_invalid_key_id_format_fails_before_any_import(stub_api: Any) -> None:
    url, state = stub_api
    result = run_script(url, "not-a-garage-key", VALID_SECRET)

    assert result.returncode != 0
    assert "must be 'GK' followed by 24 hex chars" in result.stderr
    assert state.calls == []
    assert_secret_absent(result, VALID_SECRET)


def test_invalid_secret_format_fails(stub_api: Any) -> None:
    url, state = stub_api
    result = run_script(url, VALID_KEY_ID, "not-hex-at-all")

    assert result.returncode != 0
    assert "must be 64 hex chars" in result.stderr
    assert state.calls == []


def test_import_rejection_fails_without_grant(stub_api: Any) -> None:
    url, state = stub_api
    state.import_status = 400
    state.import_body = {"code": "InvalidRequest", "message": "Nope: bad key"}
    result = run_script(url, VALID_KEY_ID, VALID_SECRET)

    assert result.returncode != 0
    assert "key import failed" in result.stderr
    assert "Key verified" not in result.stdout
    assert state.calls == ["import", "allow"]
    assert_secret_absent(result, VALID_SECRET)


def test_allow_rejection_fails(stub_api: Any) -> None:
    url, state = stub_api
    state.allow_status = 400
    state.allow_body = {"code": "InvalidRequest", "message": "Denied grant"}
    result = run_script(url, VALID_KEY_ID, VALID_SECRET)

    assert result.returncode != 0
    assert "lacks read/write/owner" in result.stderr
    assert "Key verified" not in result.stdout
    assert state.calls == ["import", "allow"]
    assert_secret_absent(result, VALID_SECRET)


def test_missing_grant_confirmation_fails(stub_api: Any) -> None:
    url, state = stub_api
    state.record_allow = False
    result = run_script(url, VALID_KEY_ID, VALID_SECRET)

    assert result.returncode != 0
    assert "lacks read/write/owner" in result.stderr
    assert_secret_absent(result, VALID_SECRET)


def test_idempotent_rerun_skips_import_and_allow(stub_api: Any) -> None:
    url, state = stub_api
    state.grants[VALID_KEY_ID] = dict(FULL_PERMS)
    result = run_script(url, VALID_KEY_ID, VALID_SECRET)

    assert result.returncode == 0, result.stderr
    assert "already has read/write/owner" in result.stdout
    assert state.calls == []
    assert_secret_absent(result, VALID_SECRET)
