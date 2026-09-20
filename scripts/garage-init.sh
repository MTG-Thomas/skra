#!/bin/sh
# Garage initialization script (issues #107, #109).
# Runs as a one-shot container (alpine:3) after Garage is healthy.
# Idempotent: safe to re-run on stack restarts.
#
# Key lifecycle modes (GARAGE_KEY_MODE; auto-selected when unset: legacy
# pair present => import, pair absent => managed, partial pair => fail):
#
#   managed (default) - Garage-native lifecycle, no key import:
#     * First run creates a key via POST /v1/key (AddKey); Garage mints the
#       ID and secret. The secret is written once to GARAGE_CREDS_FILE
#       (default /run/garage-creds/s3.env, mode 600) on a shared volume
#       consumed by api/worker via BIFROST_DOCS_S3_CREDENTIALS_FILE.
#     * Reruns look the key up by exact name (GET /v1/key?list) and refresh
#       the credentials file from the stored secret (showSecretKey=true),
#       so restarts never mint duplicate keys.
#     * Rotation is explicit: GARAGE_ROTATE=1 creates a new timestamped key,
#       repoints the credentials file at it, and prints the superseded key
#       ID. Restart dependents, then revoke the old key with a follow-up run
#       setting GARAGE_REVOKE_KEY_ID=<id> (POST /v1/bucket/deny); full key
#       deletion (DELETE /v1/key) stays manual.
#     * The active key name is tracked in <creds-dir>/s3.keyname so rotated
#       names survive restarts. Ambiguity (several keys, missing secret)
#       fails closed.
#
#   import (restore-only) - legacy deterministic import via POST
#   /v1/key/import for backup-restore and adoption of pre-existing keys.
#   The Admin API spec reserves import for migrations/restore and warns
#   against routine use to mint custom key IDs, so this mode requires the
#   legacy GARAGE_ACCESS_KEY_ID/GARAGE_SECRET_ACCESS_KEY pair explicitly
#   and is NOT the default.
#
# Neither mode ever prints a secret. Only key IDs and key names reach stdout.
set -e

ADMIN="${GARAGE_ADMIN_URL:-http://garage:3903}"
AUTH="Authorization: Bearer ${GARAGE_ADMIN_TOKEN}"
MODE="${GARAGE_KEY_MODE:-}"
KEY_NAME="${GARAGE_KEY_NAME:-bifrost-docs-key}"
CREDS_FILE="${GARAGE_CREDS_FILE:-/run/garage-creds/s3.env}"
STATE_FILE="${GARAGE_CREDS_FILE%/*}/s3.keyname"

fail() {
    echo "[garage-init] ERROR: $1" >&2
    exit 1
}

api_get() {
    # GET a path; fail closed on transport errors. Prints the body.
    # $2 (optional) is failure context prepended to the error message.
    wget -qO- --header="${AUTH}" "${ADMIN}$1" 2>/dev/null \
        || fail "${2:+$2 - }admin API request failed: GET $1"
}

api_post() {
    # POST a JSON body; fail closed on transport errors. Prints the body.
    # $3 (optional) is failure context prepended to the error message.
    wget -qO- --header="${AUTH}" \
        --header="Content-Type: application/json" \
        --post-data="$2" "${ADMIN}$1" 2>/dev/null \
        || fail "${3:+$3 - }admin API request failed: POST $1"
}

json_field() {
    # Extract the first "field":"value" string from JSON on stdin.
    # $1 = field name. Prints the value or nothing.
    grep -o "\"$1\"[ ]*:[ ]*\"[^\"]*\"" | head -1 | sed 's/^"[^"]*"[ ]*:[ ]*"//; s/"$//'
}

key_id_for_name() {
    # Print access key IDs (one per line) whose list entry name exactly
    # matches $1. List entries look like {"id":"GK...","name":"..."} with
    # varying whitespace. grep/sed only (busybox awk lacks 3-arg match).
    printf '%s' "$2" | tr '{}' '\n\n' \
        | grep "\"name\" *: *\"$1\"" \
        | grep -o '"id" *: *"[^"]*"' \
        | sed 's/^"id" *: *"//; s/"$//'
}

write_creds_file() {
    # $1 = key ID, $2 = secret. Writes KEY=VALUE readable ONLY by the app
    # identity: the api image pins app to uid/gid 15000 (see Dockerfile),
    # while this container runs as root, so a plain 0600 file would be
    # unreadable across the shared volume. chown by number (alpine has no
    # app user) then lock to owner-only perms. Secrets stay non-world-readable.
    dir=$(dirname "${CREDS_FILE}")
    [ -d "${dir}" ] || fail "credentials directory missing: ${dir} (mount the garage-creds volume)"
    uid="${GARAGE_CREDS_UID:-15000}"
    gid="${GARAGE_CREDS_GID:-15000}"
    tmp="${CREDS_FILE}.tmp.$$"
    umask 077
    {
        printf '# Managed by garage-init; do not edit. Regenerated on reruns.\n'
        printf 'S3_ACCESS_KEY_ID=%s\n' "$1"
        printf 'S3_SECRET_ACCESS_KEY=%s\n' "$2"
    } > "${tmp}"
    chown "${uid}:${gid}" "${tmp}" "${STATE_FILE}" 2>/dev/null || chown "${uid}:${gid}" "${tmp}"
    chmod 600 "${tmp}"
    mv "${tmp}" "${CREDS_FILE}"
    printf '%s\n' "${ACTIVE_NAME}" > "${STATE_FILE}"
    chown "${uid}:${gid}" "${STATE_FILE}"
    chmod 600 "${STATE_FILE}"
}

echo "[garage-init] Waiting for admin API..."
until wget -qO /dev/null --header="${AUTH}" "${ADMIN}/v1/health" 2>/dev/null; do
  sleep 2
done
echo "[garage-init] Garage is up."

# Get this node's ID — handle both compact and spaced JSON
STATUS=$(api_get "/v1/status")
NODE_ID=$(echo "${STATUS}" | grep -o '"node"[^,}]*' | grep -o '"[a-f0-9][a-f0-9]*"' | tr -d '"' | head -1)
echo "[garage-init] Node ID: ${NODE_ID}"

if [ -z "${NODE_ID}" ]; then
  echo "[garage-init] ERROR: could not parse node ID. Raw status:"
  echo "${STATUS}"
  exit 1
fi

# Assign node to layout zone with 10 GB capacity (idempotent)
wget -qO /dev/null \
  --header="${AUTH}" \
  --header="Content-Type: application/json" \
  --post-data="[{\"id\":\"${NODE_ID}\",\"zone\":\"dc1\",\"capacity\":10737418240,\"tags\":[]}]" \
  "${ADMIN}/v1/layout" 2>/dev/null || true

# Apply layout at version 1 (idempotent)
wget -qO /dev/null \
  --header="${AUTH}" \
  --header="Content-Type: application/json" \
  --post-data='{"version":1}' \
  "${ADMIN}/v1/layout/apply" 2>/dev/null || true

echo "[garage-init] Layout applied. Waiting for ring..."
sleep 3

# Create bucket — capture response to extract ID even if bucket already exists
BUCKET_RESP=$(wget -qO- \
  --header="${AUTH}" \
  --header="Content-Type: application/json" \
  --post-data='{"globalAlias":"bifrost-docs"}' \
  "${ADMIN}/v1/bucket" 2>/dev/null || true)

# If bucket already existed, the creation returns error — fetch it directly
if [ -z "${BUCKET_RESP}" ] || echo "${BUCKET_RESP}" | grep -qi "error\|already"; then
  BUCKET_RESP=$(api_get "/v1/bucket?globalAlias=bifrost-docs")
fi

BUCKET_ID=$(echo "${BUCKET_RESP}" | grep -o '"id"[^,}]*' | grep -o '"[a-f0-9-][a-f0-9-]*"' | tr -d '"' | head -1)
echo "[garage-init] Bucket ID: ${BUCKET_ID}"

if [ -z "${BUCKET_ID}" ]; then
  echo "[garage-init] ERROR: could not obtain bucket ID. Response:"
  echo "${BUCKET_RESP}"
  exit 1
fi

# Optional revocation of a superseded key from a previous rotation, run
# AFTER the operator restarts dependents on the new credentials: deactivates
# its read/write/owner flags on this bucket (POST /v1/bucket/deny — note the
# inverted semantics: true deactivates). Revokes only the exact ID given,
# never by name matching. Full key deletion (DELETE /v1/key, unsupported by
# wget) stays a documented manual admin step.
if [ -n "${GARAGE_REVOKE_KEY_ID:-}" ]; then
    if api_post "/v1/bucket/deny" "{\"bucketId\":\"${BUCKET_ID}\",\"accessKeyId\":\"${GARAGE_REVOKE_KEY_ID}\",\"permissions\":{\"read\":true,\"write\":true,\"owner\":true}}" >/dev/null; then
        echo "[garage-init] Revoked bucket access for superseded key ${GARAGE_REVOKE_KEY_ID}."
    else
        fail "could not revoke key ${GARAGE_REVOKE_KEY_ID}"
    fi
fi

# Backward-compatible mode selection (issue #107): an explicit
# GARAGE_KEY_MODE always wins. Otherwise the legacy pair selects import
# mode (existing deployments keep working with zero changes), its absence
# selects managed mode (new deployments mint natively), and a partial pair
# fails closed instead of silently rotating or importing half credentials.
# Placed after the helpers above (fail() must exist before use).
if [ -z "${MODE}" ]; then
    if [ -n "${GARAGE_ACCESS_KEY_ID:-}" ] && [ -n "${GARAGE_SECRET_ACCESS_KEY:-}" ]; then
        MODE="import"
        echo "[garage-init] Auto-selected import mode (legacy key pair present)."
    elif [ -n "${GARAGE_ACCESS_KEY_ID:-}" ] || [ -n "${GARAGE_SECRET_ACCESS_KEY:-}" ]; then
        [ -n "${GARAGE_ACCESS_KEY_ID:-}" ] \
            || fail "GARAGE_SECRET_ACCESS_KEY is set without GARAGE_ACCESS_KEY_ID; refusing to guess the mode (set both or neither)"
        fail "GARAGE_ACCESS_KEY_ID is set without GARAGE_SECRET_ACCESS_KEY; refusing to guess the mode (set both or neither)"
    else
        MODE="managed"
        echo "[garage-init] Auto-selected managed mode (no legacy key pair)."
    fi
fi

# --- Restore-only import mode (backup-restore / adoption) -------------------
if [ "${MODE}" = "import" ]; then
    [ -n "${GARAGE_ACCESS_KEY_ID:-}" ] \
        || fail "import mode requires GARAGE_ACCESS_KEY_ID (restore-only; default managed mode mints keys natively)"
    [ -n "${GARAGE_SECRET_ACCESS_KEY:-}" ] \
        || fail "import mode requires GARAGE_SECRET_ACCESS_KEY (restore-only; default managed mode mints keys natively)"
    # Garage v1.3.1 only accepts key IDs as `GK` + 24 hex chars and secrets
    # as 64 hex chars. Validate upfront: without this, rejected imports
    # surface later as a cryptic S3 "No such key".
    case "${GARAGE_ACCESS_KEY_ID}" in
        GK????????????????????????) ;;
        *)
            echo "[garage-init] ERROR: GARAGE_ACCESS_KEY_ID must be 'GK' followed by 24 hex chars" >&2
            exit 1
            ;;
    esac
    case "${GARAGE_ACCESS_KEY_ID}" in
        GK*[!0-9a-f]*) fail "GARAGE_ACCESS_KEY_ID suffix must be hex" ;;
    esac
    case "${GARAGE_SECRET_ACCESS_KEY}" in
        ????????????????????????????????????????????????????????????????) ;;
        *)
            echo "[garage-init] ERROR: GARAGE_SECRET_ACCESS_KEY must be 64 hex chars" >&2
            exit 1
            ;;
    esac
    case "${GARAGE_SECRET_ACCESS_KEY}" in
        *[!0-9a-f]*) fail "GARAGE_SECRET_ACCESS_KEY must be hex" ;;
    esac

    # Decide whether the key must be imported by listing existing keys, then -
    # only when our key ID is listed - fetch its stored secret and compare it
    # in memory. A proven mismatch fails naming only the key ID. An absent key
    # falls through to the strict import below. List or detail fetch failures
    # fail closed: no path prints success for unverified credentials, and
    # neither secret is ever printed.
    KEY_LIST=$(api_get "/v1/key?list" "could not list keys")
    SKIP_IMPORT=0
    if printf '%s' "${KEY_LIST}" | grep -q "\"${GARAGE_ACCESS_KEY_ID}\""; then
        KEY_INFO=$(api_get "/v1/key?id=${GARAGE_ACCESS_KEY_ID}&showSecretKey=true" \
            "could not fetch stored secret for key ${GARAGE_ACCESS_KEY_ID}")
        STORED_SECRET=$(printf '%s' "${KEY_INFO}" \
            | grep -o '"secretAccessKey"[ ]*:[ ]*"[^"]*"' | head -1 \
            | sed 's/^"secretAccessKey"[ ]*:[ ]*"//; s/"$//') || true
        [ -n "${STORED_SECRET}" ] || fail "Garage did not disclose the stored secret; cannot verify credentials"
        if [ "${STORED_SECRET}" != "${GARAGE_SECRET_ACCESS_KEY}" ]; then
            fail "key ${GARAGE_ACCESS_KEY_ID} exists with a different secret; refusing to overwrite (rotate via Garage admin API)"
        fi
        echo "[garage-init] Stored secret matches configuration; skipping import."
        SKIP_IMPORT=1
    else
        echo "[garage-init] Key not present; will import."
    fi

    # Import access key with the configured secret, unless the lookup above
    # already proved the stored secret matches. Any rejection fails loudly;
    # a stale grant from an older secret can never satisfy this run.
    if [ "${SKIP_IMPORT}" != "1" ]; then
        if api_post "/v1/key/import" "{\"accessKeyId\":\"${GARAGE_ACCESS_KEY_ID}\",\"secretAccessKey\":\"${GARAGE_SECRET_ACCESS_KEY}\",\"name\":\"${KEY_NAME}\"}" "key import request failed" >/dev/null; then
            echo "[garage-init] Key imported."
        else
            fail "key import request failed"
        fi
    fi
    RESOLVED_KEY_ID="${GARAGE_ACCESS_KEY_ID}"
else
    [ "${MODE}" = "managed" ] \
        || fail "unknown GARAGE_KEY_MODE '${MODE}' (want managed or import)"
    case "${KEY_NAME}" in
        *[!A-Za-z0-9_-]*|'') fail "GARAGE_KEY_NAME must be non-empty [A-Za-z0-9_-]" ;;
    esac

    # --- Managed mode: Garage-native key lifecycle --------------------------
    # The active key name persists across restarts so rotated names are
    # honored; a fresh volume starts from KEY_NAME.
    ACTIVE_NAME="${KEY_NAME}"
    if [ -f "${STATE_FILE}" ]; then
        SAVED=$(tr -d ' \t\r\n' < "${STATE_FILE}" 2>/dev/null || true)
        [ -n "${SAVED}" ] && ACTIVE_NAME="${SAVED}"
    fi

    KEY_LIST=$(api_get "/v1/key?list" "could not list keys")
    MATCHES=$(key_id_for_name "${ACTIVE_NAME}" "${KEY_LIST}")
    N_MATCHES=$(printf '%s' "${MATCHES}" | grep -c . || true)

    if [ -n "${GARAGE_ROTATE:-}" ]; then
        # Explicit rotation: mint a new timestamped key, repoint the
        # credentials file, keep the old key until the operator restarts
        # dependents and prunes it (see GARAGE_PRUNE_KEY_ID above).
        STAMP=$(date -u +%Y%m%d-%H%M%S)
        NEW_NAME="${KEY_NAME}-${STAMP}"
        CREATED=$(api_post "/v1/key" "{\"name\":\"${NEW_NAME}\"}")
        NEW_ID=$(printf '%s' "${CREATED}" | json_field accessKeyId)
        NEW_SECRET=$(printf '%s' "${CREATED}" | json_field secretAccessKey)
        [ -n "${NEW_ID}" ] || fail "key creation did not return an ID"
        [ -n "${NEW_SECRET}" ] || fail "key creation did not return a secret"
        ACTIVE_NAME="${NEW_NAME}"
        write_creds_file "${NEW_ID}" "${NEW_SECRET}"
        echo "[garage-init] Rotated: new key ${NEW_ID} (${NEW_NAME}) written to credentials file."
        if [ "${N_MATCHES}" -gt 0 ]; then
            echo "[garage-init] Superseded key(s) still active: $(printf '%s' "${MATCHES}" | tr '\n' ' ')"
            echo "[garage-init] Restart api, then revoke the old key ID(s) with a follow-up run setting GARAGE_REVOKE_KEY_ID=<id>."
        fi
        RESOLVED_KEY_ID="${NEW_ID}"
    elif [ "${N_MATCHES}" -eq 1 ]; then
        # Idempotent rerun: reuse the existing key, refreshing the
        # credentials file from the stored secret (self-healing when the
        # volume was lost; the volume is the only secret copy otherwise).
        RESOLVED_KEY_ID=$(printf '%s' "${MATCHES}" | head -1)
        KEY_INFO=$(api_get "/v1/key?id=${RESOLVED_KEY_ID}&showSecretKey=true" \
            "could not fetch stored secret for key ${RESOLVED_KEY_ID}")
        STORED_SECRET=$(printf '%s' "${KEY_INFO}" | json_field secretAccessKey)
        [ -n "${STORED_SECRET}" ] || fail "Garage did not disclose the stored secret for ${RESOLVED_KEY_ID}; cannot rewrite credentials file"
        write_creds_file "${RESOLVED_KEY_ID}" "${STORED_SECRET}"
        echo "[garage-init] Reusing existing key ${RESOLVED_KEY_ID}; credentials file refreshed."
    elif [ "${N_MATCHES}" -eq 0 ]; then
        # Clean install (or post-restore empty cluster): mint via AddKey.
        CREATED=$(api_post "/v1/key" "{\"name\":\"${ACTIVE_NAME}\"}")
        RESOLVED_KEY_ID=$(printf '%s' "${CREATED}" | json_field accessKeyId)
        NEW_SECRET=$(printf '%s' "${CREATED}" | json_field secretAccessKey)
        [ -n "${RESOLVED_KEY_ID}" ] || fail "key creation did not return an ID"
        [ -n "${NEW_SECRET}" ] || fail "key creation did not return a secret"
        write_creds_file "${RESOLVED_KEY_ID}" "${NEW_SECRET}"
        echo "[garage-init] Created key ${RESOLVED_KEY_ID} (${ACTIVE_NAME})."
    else
        fail "several keys named '${ACTIVE_NAME}' exist; refusing to guess (delete extras or set GARAGE_KEY_NAME)"
    fi
fi

bucket_keys_region() {
    # Print the bucket's keys array region for permission checks.
    BUCKET_JSON=$(api_get "/v1/bucket?globalAlias=bifrost-docs")
    [ -n "${BUCKET_JSON}" ] || fail "empty bucket state response"
    printf '%s' "${BUCKET_JSON}" | sed -n '/"keys": *\[/,/"objects":/p'
}

key_has_full_access() {
    # True when the entry for the resolved key itself holds
    # read/write/owner. Flags are matched per entry (split on entry
    # boundaries), never across the whole keys array, so another key's
    # permissions cannot satisfy this check. Spacing after colons varies
    # (compact vs pretty JSON), so it is allowed in every pattern.
    KEYS_REGION=$(bucket_keys_region) || return 1
    # Newlines/tabs are folded to spaces first so the matcher below needs
    # no escape-heavy whitespace classes (portable across mawk/busybox/gawk).
    printf '%s' "${KEYS_REGION}" | tr '\n\t' '  ' | awk -v id="${RESOLVED_KEY_ID}" '
        { buf = buf $0 }
        END {
            n = split(buf, recs, /}[, ]*[{]/)
            for (i = 1; i <= n; i++) {
                pat = "\"accessKeyId\" *: *\"" id "\""
                if (recs[i] ~ pat &&
                    recs[i] ~ /"read" *: *true/ &&
                    recs[i] ~ /"write" *: *true/ &&
                    recs[i] ~ /"owner" *: *true/) exit 0
            }
            exit 1
        }'
}

# Grant key full access to bucket; any failure fails the container.
if api_post "/v1/bucket/allow" "{\"bucketId\":\"${BUCKET_ID}\",\"accessKeyId\":\"${RESOLVED_KEY_ID}\",\"permissions\":{\"read\":true,\"write\":true,\"owner\":true}}" "bucket permission grant request failed" >/dev/null; then
    echo "[garage-init] Key permissions set."
else
    fail "bucket permission grant request failed"
fi

# Confirm the key itself actually holds read/write/owner before success.
if key_has_full_access; then
    echo "[garage-init] Key verified with read/write/owner on bucket (key: ${RESOLVED_KEY_ID})."
else
    fail "key ${RESOLVED_KEY_ID} lacks read/write/owner on bucket after grant"
fi
echo "[garage-init] Initialization complete."
