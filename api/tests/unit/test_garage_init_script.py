"""Unit tests for scripts/garage-init.sh fail-open behavior (issue #98).

Runs the real init script against a stub Garage admin API over local HTTP:
happy path, invalid credential formats, import/allow rejections, the
post-grant permission confirmation, idempotent reruns, and secret redaction.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
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
        self.key_secrets: dict[str, str] = {}
        self.key_endpoint = True
        self.list_endpoint = True
        self.omit_secret = False
        self.detail_status = 200
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
            elif self.path.startswith("/v1/key"):
                from urllib.parse import parse_qs, urlparse

                query = urlparse(self.path).query
                if query == "list" or query.startswith("list&"):
                    if not state.list_endpoint:
                        self._send(
                            400,
                            {
                                "code": "InvalidRequest",
                                "message": "Bad request: Unknown API endpoint: GET /v1/key?list",
                            },
                        )
                        return
                    self._send(
                        200,
                        [{"id": kid, "name": "skra-key"} for kid in state.key_secrets],
                    )
                    return
                if not state.key_endpoint:
                    self._send(
                        400,
                        {
                            "code": "InvalidRequest",
                            "message": "Bad request: Unknown API endpoint: GET /v1/key",
                        },
                    )
                    return
                if state.detail_status != 200:
                    self._send(state.detail_status, {})
                    return
                qs = parse_qs(urlparse(self.path).query)
                kid = qs.get("id", [""])[0]
                show = qs.get("showSecretKey", ["false"])[0]
                if kid not in state.key_secrets:
                    self._send(400, {"code": "InvalidRequest", "message": "No such key"})
                elif show != "true" or state.omit_secret:
                    self._send(200, {"accessKeyId": kid, "name": "skra-key"})
                else:
                    self._send(
                        200,
                        {
                            "accessKeyId": kid,
                            "name": "skra-key",
                            "secretAccessKey": state.key_secrets[kid],
                        },
                    )
            elif self.path.startswith("/v1/bucket"):
                keys = [
                    {
                        "accessKeyId": key_id,
                        "name": "skra-key",
                        "permissions": perms,
                    }
                    for key_id, perms in state.grants.items()
                ]
                self._send(
                    200,
                    {
                        "id": BUCKET_ID,
                        "globalAliases": ["skra"],
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
                    state.key_secrets[payload.get("accessKeyId", "")] = payload.get(
                        "secretAccessKey", ""
                    )
                    self._send(200, state.import_body or {})
            elif self.path == "/v1/bucket/allow":
                payload = self._read_json()
                state.calls.append("allow")
                if (
                    payload.get("accessKeyId") not in state.imported
                    and payload.get("accessKeyId") not in state.key_secrets
                ):
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
    """Run garage-init.sh against the stub API.

    Provides a throwaway credentials directory like the production volume
    mount (import mode writes s3.env there), with ownership pinned to the
    current user so the script's chown succeeds with or without root.
    The path is attached as result.creds_file for content assertions.
    """
    creds_dir = tempfile.mkdtemp(prefix="garage-creds-")
    creds_file = os.path.join(creds_dir, "s3.env")
    env = {
        **os.environ,
        "GARAGE_ADMIN_URL": url,
        "GARAGE_ADMIN_TOKEN": "test-admin-token",
        "GARAGE_ACCESS_KEY_ID": key_id,
        "GARAGE_SECRET_ACCESS_KEY": secret,
        "GARAGE_CREDS_FILE": creds_file,
        "GARAGE_CREDS_UID": str(os.getuid()),
        "GARAGE_CREDS_GID": str(os.getgid()),
    }
    result = subprocess.run(
        ["sh", str(SCRIPT)], capture_output=True, text=True, timeout=60, env=env
    )
    result.creds_file = creds_file  # type: ignore[attr-defined]
    return result


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


def test_import_writes_credentials_file_for_pair(stub_api: Any) -> None:
    """Import mode persists the pair where api/worker load it from."""
    url, state = stub_api
    result = run_script(url, VALID_KEY_ID, VALID_SECRET)

    assert result.returncode == 0, result.stderr
    content = Path(result.creds_file).read_text()
    assert f"S3_ACCESS_KEY_ID={VALID_KEY_ID}" in content
    assert f"S3_SECRET_ACCESS_KEY={VALID_SECRET}" in content


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


def test_import_failure_fails_despite_existing_grant(stub_api: Any) -> None:
    # Wrong-secret rerun scenario: the key ID already holds permissions from
    # an older secret, but this run's import is rejected. Success must not
    # print; the stale grant must not satisfy this run.
    url, state = stub_api
    state.import_status = 400
    state.import_body = {"code": "InvalidRequest", "message": "Nope: bad key"}
    result = run_script(url, VALID_KEY_ID, VALID_SECRET)

    assert result.returncode != 0
    assert "key import request failed" in result.stderr
    assert "Key verified" not in result.stdout
    assert "Initialization complete." not in result.stdout
    assert state.calls == ["import"]
    assert_secret_absent(result, VALID_SECRET)


def test_allow_rejection_fails(stub_api: Any) -> None:
    url, state = stub_api
    state.allow_status = 400
    state.allow_body = {"code": "InvalidRequest", "message": "Denied grant"}
    result = run_script(url, VALID_KEY_ID, VALID_SECRET)

    assert result.returncode != 0
    assert "bucket permission grant request failed" in result.stderr
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


def test_matching_secret_skips_import(stub_api: Any) -> None:
    # The lookup proves the stored secret equals the configured one, so
    # import is skipped; grant and confirmation still run.
    url, state = stub_api
    state.key_secrets[VALID_KEY_ID] = VALID_SECRET
    state.grants[VALID_KEY_ID] = dict(FULL_PERMS)
    result = run_script(url, VALID_KEY_ID, VALID_SECRET)

    assert result.returncode == 0, result.stderr
    assert "Stored secret matches configuration" in result.stdout
    assert "Key verified with read/write/owner" in result.stdout
    assert state.calls == ["allow"]
    assert_secret_absent(result, VALID_SECRET)


def test_wrong_secret_fails_before_import(stub_api: Any) -> None:
    # The review scenario: key ID holds permissions from an older secret.
    # The lookup detects the mismatch and fails naming only the key ID;
    # neither secret may appear in output and no import is attempted.
    url, state = stub_api
    state.key_secrets[VALID_KEY_ID] = "f" * 64
    state.grants[VALID_KEY_ID] = dict(FULL_PERMS)
    result = run_script(url, VALID_KEY_ID, VALID_SECRET)

    assert result.returncode != 0
    assert "different secret" in result.stderr
    assert VALID_KEY_ID in result.stderr
    assert "Key verified" not in result.stdout
    assert "Initialization complete." not in result.stdout
    assert state.calls == []
    assert_secret_absent(result, VALID_SECRET)
    assert_secret_absent(result, "f" * 64)


def test_first_boot_imports_absent_key(stub_api: Any) -> None:
    # First boot: the key list is empty, so the flow imports, grants,
    # and confirms. The absent-key lookup answer is positive (empty
    # list), never an abort.
    url, state = stub_api
    result = run_script(url, VALID_KEY_ID, VALID_SECRET)

    assert result.returncode == 0, result.stderr
    assert "Key not present; will import." in result.stdout
    assert "Key verified with read/write/owner" in result.stdout
    assert state.calls == ["import", "allow"]
    assert_secret_absent(result, VALID_SECRET)


def test_missing_list_endpoint_fails_closed(stub_api: Any) -> None:
    url, state = stub_api
    state.list_endpoint = False
    result = run_script(url, VALID_KEY_ID, VALID_SECRET)

    assert result.returncode != 0
    assert "could not list keys" in result.stderr
    assert "Key verified" not in result.stdout
    assert state.calls == []
    assert_secret_absent(result, VALID_SECRET)


def test_detail_fetch_failure_fails_closed(stub_api: Any) -> None:
    url, state = stub_api
    state.key_secrets[VALID_KEY_ID] = VALID_SECRET
    state.detail_status = 500
    result = run_script(url, VALID_KEY_ID, VALID_SECRET)

    assert result.returncode != 0
    assert "could not fetch stored secret" in result.stderr
    assert state.calls == []
    assert_secret_absent(result, VALID_SECRET)


def test_undisclosed_secret_fails_closed(stub_api: Any) -> None:
    # The key is listed, so it exists, but without the secret field there
    # is nothing to compare: fail rather than import blindly.
    url, state = stub_api
    state.key_secrets[VALID_KEY_ID] = VALID_SECRET
    state.omit_secret = True
    result = run_script(url, VALID_KEY_ID, VALID_SECRET)

    assert result.returncode != 0
    assert "did not disclose the stored secret" in result.stderr
    assert state.calls == []
    assert_secret_absent(result, VALID_SECRET)


OTHER_KEY_ID = "GK000000000000000000000001"


def test_other_key_permissions_do_not_satisfy_target(stub_api: Any) -> None:
    # The review's exact scenario: the target entry exists but is
    # permissionless while another key holds full access. Region-wide
    # flag greps falsely accepted this; per-entry matching must not.
    url, state = stub_api
    state.key_secrets[VALID_KEY_ID] = VALID_SECRET
    state.grants[OTHER_KEY_ID] = {"read": True, "write": True, "owner": True}
    state.grants[VALID_KEY_ID] = {"read": True, "write": False, "owner": False}
    state.record_allow = False
    result = run_script(url, VALID_KEY_ID, VALID_SECRET)

    assert result.returncode != 0
    assert "lacks read/write/owner" in result.stderr
    assert "Key verified" not in result.stdout
    assert_secret_absent(result, VALID_SECRET)


def test_target_key_accepted_beside_weaker_key(stub_api: Any) -> None:
    url, state = stub_api
    state.key_secrets[VALID_KEY_ID] = VALID_SECRET
    state.grants[OTHER_KEY_ID] = {"read": True, "write": False, "owner": False}
    result = run_script(url, VALID_KEY_ID, VALID_SECRET)

    assert result.returncode == 0, result.stderr
    assert "Key verified with read/write/owner" in result.stdout
    assert_secret_absent(result, VALID_SECRET)
