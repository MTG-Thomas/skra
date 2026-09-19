#!/bin/bash
# Harness tests for scripts/garage-init.sh against a stub Admin API.
# No Docker, no VM: drives the real script with sh + system wget/python3.
# Run: ./scripts/tests/test_garage_init.sh  (from the repo root)
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$ROOT/scripts/garage-init.sh"
STUB="$ROOT/scripts/tests/stub_garage_admin.py"
TOKEN="test-admin-token-0000000000000000"
PASS=0
FAIL=0

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "SKIP: $1 missing"; exit 2; }
}
need python3
need wget
command -v sh >/dev/null || { echo "SKIP: sh missing"; exit 2; }

ok() { PASS=$((PASS + 1)); echo "ok: $1"; }
bad() { FAIL=$((FAIL + 1)); echo "FAIL: $1"; }

start_stub() {
  # $1 = workdir (holds stub.log). Stub runs in background; echo its pid.
  # stdout/stderr MUST redirect elsewhere: an inherited command-substitution
  # pipe would stay open for the stub's lifetime and hang the caller.
  python3 "$STUB" "$PORT" "$1/stub.log" "$TOKEN" >/dev/null 2>&1 & echo $!
}

run_init() {
  # env passthrough via exported vars; always sets admin URL + token.
  # $1 = workdir. Remaining args are extra VAR=value pairs.
  local wd="$1"; shift
  mkdir -p "$wd/creds"
  ( export GARAGE_ADMIN_URL="http://127.0.0.1:$PORT" GARAGE_ADMIN_TOKEN="$TOKEN" \
      GARAGE_CREDS_FILE="$wd/creds/s3.env" "$@"
    sh "$SCRIPT" >"$wd/out.log" 2>&1 )
}

PORT=13903
SECRET_RE='[0-9a-f]\{64\}'

t_managed_clean_install() {
  local wd; wd=$(mktemp -d)
  local pid; pid=$(start_stub "$wd"); sleep 1
  if run_init "$wd"; then
    grep -q '^S3_ACCESS_KEY_ID=GK' "$wd/creds/s3.env" \
      && grep -q '^S3_SECRET_ACCESS_KEY=[0-9a-f]*$' "$wd/creds/s3.env" \
      && grep -q '^bifrost-docs-key$' "$wd/creds/s3.keyname" \
      && grep -c 'POST /v1/key$' "$wd/stub.log" | grep -q '^1$' \
      && [ "$(stat -c '%u:%g:%a' "$wd/creds/s3.env")" = "15000:15000:600" ] \
      && [ "$(stat -c '%u:%g:%a' "$wd/creds/s3.keyname")" = "15000:15000:600" ] \
      && ok "managed clean install mints one key and writes creds" \
      || bad "managed clean install files/requests/ownership wrong"
    # Secret must never reach stdout.
    local sec; sec=$(grep -o '^S3_SECRET_ACCESS_KEY=.*' "$wd/creds/s3.env" | cut -d= -f2)
    grep -q "$sec" "$wd/out.log" && bad "secret leaked to stdout" || ok "secret not on stdout"
  else
    bad "managed clean install exited nonzero"
  fi
  kill "$pid" 2>/dev/null; rm -rf "$wd"
}

t_managed_rerun_reuses() {
  local wd; wd=$(mktemp -d)
  local pid; pid=$(start_stub "$wd"); sleep 1
  run_init "$wd" >/dev/null 2>&1
  : > "$wd/stub.log"
  if run_init "$wd"; then
    grep -q 'Reusing existing key' "$wd/out.log" \
      && ! grep -q 'POST /v1/key$' "$wd/stub.log" \
      && ok "managed rerun reuses key without minting" \
      || bad "managed rerun minted or misreported"
  else
    bad "managed rerun exited nonzero"
  fi
  kill "$pid" 2>/dev/null; rm -rf "$wd"
}

t_managed_rotation_and_revoke() {
  local wd; wd=$(mktemp -d)
  local pid; pid=$(start_stub "$wd"); sleep 1
  run_init "$wd" >/dev/null 2>&1
  local old; old=$(grep -o '^S3_ACCESS_KEY_ID=.*' "$wd/creds/s3.env" | cut -d= -f2)
  if run_init "$wd" GARAGE_ROTATE=1; then
    local new; new=$(grep -o '^S3_ACCESS_KEY_ID=.*' "$wd/creds/s3.env" | cut -d= -f2)
    [ "$new" != "$old" ] && [ -n "$new" ] \
      && grep -q "$old" "$wd/out.log" \
      && ok "rotation mints new key and reports old ID" \
      || bad "rotation did not repoint creds or report old ID"
  else
    bad "rotation exited nonzero"; kill "$pid" 2>/dev/null; rm -rf "$wd"; return
  fi
  if run_init "$wd" GARAGE_REVOKE_KEY_ID="$old"; then
    grep -q 'POST /v1/bucket/deny' "$wd/stub.log" \
      && ok "revoke deactivates old key via deny endpoint" \
      || bad "revoke did not call deny endpoint"
  else
    bad "revoke exited nonzero"
  fi
  kill "$pid" 2>/dev/null; rm -rf "$wd"
}

t_import_mode_needs_pair() {
  local wd; wd=$(mktemp -d)
  local pid; pid=$(start_stub "$wd"); sleep 1
  if run_init "$wd" GARAGE_KEY_MODE=import; then
    bad "import mode without legacy pair should fail"
  else
    ok "import mode fails closed without legacy pair"
  fi
  kill "$pid" 2>/dev/null; rm -rf "$wd"
}

t_import_mode_restores() {
  local wd; wd=$(mktemp -d)
  local pid; pid=$(start_stub "$wd"); sleep 1
  local kid="GK00112233445566778899aabb"
  local sec="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
  if run_init "$wd" GARAGE_KEY_MODE=import GARAGE_ACCESS_KEY_ID="$kid" GARAGE_SECRET_ACCESS_KEY="$sec"; then
    grep -q 'POST /v1/key/import' "$wd/stub.log" \
      && ok "import mode restores legacy pair" \
      || bad "import mode did not call import endpoint"
  else
    bad "import mode exited nonzero"
  fi
  # Rerun with same pair: secret match skips re-import.
  : > "$wd/stub.log"
  if run_init "$wd" GARAGE_KEY_MODE=import GARAGE_ACCESS_KEY_ID="$kid" GARAGE_SECRET_ACCESS_KEY="$sec"; then
    grep -q 'skipping import' "$wd/out.log" \
      && ! grep -q 'POST /v1/key/import' "$wd/stub.log" \
      && ok "import rerun skips on secret match" \
      || bad "import rerun did not skip"
  else
    bad "import rerun exited nonzero"
  fi
  kill "$pid" 2>/dev/null; rm -rf "$wd"
}

t_unknown_mode_fails() {
  local wd; wd=$(mktemp -d)
  local pid; pid=$(start_stub "$wd"); sleep 1
  if run_init "$wd" GARAGE_KEY_MODE=bogus; then
    bad "unknown mode should fail"
  else
    ok "unknown mode fails closed"
  fi
  kill "$pid" 2>/dev/null; rm -rf "$wd"
}

t_managed_clean_install
t_managed_rerun_reuses
t_managed_rotation_and_revoke
t_import_mode_needs_pair
t_import_mode_restores
t_unknown_mode_fails

echo "pass=$PASS fail=$FAIL"
[ "$FAIL" -eq 0 ]
