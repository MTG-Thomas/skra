#!/bin/sh
# Garage initialization script.
# Runs as a one-shot container (alpine:3) after Garage is healthy.
# Idempotent: safe to re-run on stack restarts.
set -e

ADMIN="${GARAGE_ADMIN_URL:-http://garage:3903}"
AUTH="Authorization: Bearer ${GARAGE_ADMIN_TOKEN}"

fail() {
    echo "[garage-init] ERROR: $1" >&2
    exit 1
}

# Garage v1.3.1 only accepts key IDs as `GK` + 24 hex chars and secrets
# as 64 hex chars. Validate upfront: without this, rejected imports
# surface later as a cryptic S3 "No such key".
case "${GARAGE_ACCESS_KEY_ID}" in
    GK????????????????????????) ;;
    *)
        echo "[garage-init] ERROR: GARAGE_ACCESS_KEY_ID must be 'GK' followed by 24 hex chars" >&2
        echo '[garage-init] Generate with: echo -n "GK$(openssl rand -hex 12)"' >&2
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
        echo "[garage-init] Generate with: openssl rand -hex 32" >&2
        exit 1
        ;;
esac
case "${GARAGE_SECRET_ACCESS_KEY}" in
    *[!0-9a-f]*) fail "GARAGE_SECRET_ACCESS_KEY must be hex" ;;
esac

echo "[garage-init] Waiting for admin API..."
until wget -qO /dev/null --header="${AUTH}" "${ADMIN}/v1/health" 2>/dev/null; do
  sleep 2
done
echo "[garage-init] Garage is up."

# Get this node's ID — handle both compact and spaced JSON
STATUS=$(wget -qO- --header="${AUTH}" "${ADMIN}/v1/status")
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
  BUCKET_RESP=$(wget -qO- \
    --header="${AUTH}" \
    "${ADMIN}/v1/bucket?globalAlias=bifrost-docs" 2>/dev/null || true)
fi

BUCKET_ID=$(echo "${BUCKET_RESP}" | grep -o '"id"[^,}]*' | grep -o '"[a-f0-9-][a-f0-9-]*"' | tr -d '"' | head -1)
echo "[garage-init] Bucket ID: ${BUCKET_ID}"

if [ -z "${BUCKET_ID}" ]; then
  echo "[garage-init] ERROR: could not obtain bucket ID. Response:"
  echo "${BUCKET_RESP}"
  exit 1
fi

# Look up the configured key, asking Garage to disclose its stored secret.
# When the disclosed secret matches, import is safely skipped. A proven
# mismatch fails immediately naming only the key ID. Anything else (absent
# key, undisclosed field, failed fetch) falls through to the strict import
# below, which fails loudly on any real problem - so no path can print
# success for unverified credentials. Neither secret is ever printed.
KEY_INFO=$(wget -qO- --header="${AUTH}" \
    "${ADMIN}/v1/key?id=${GARAGE_ACCESS_KEY_ID}&showSecretKey=true" 2>/dev/null) || true
SKIP_IMPORT=0
if printf '%s' "${KEY_INFO}" | grep -q '"secretAccessKey"'; then
    STORED_SECRET=$(printf '%s' "${KEY_INFO}" \
        | grep -o '"secretAccessKey"[ ]*:[ ]*"[^"]*"' | head -1 \
        | sed 's/^"secretAccessKey"[ ]*:[ ]*"//; s/"$//') || true
    [ -n "${STORED_SECRET}" ] || fail "could not parse stored secret"
    if [ "${STORED_SECRET}" != "${GARAGE_SECRET_ACCESS_KEY}" ]; then
        fail "key ${GARAGE_ACCESS_KEY_ID} exists with a different secret; refusing to overwrite (rotate via Garage admin API)"
    fi
    echo "[garage-init] Stored secret matches configuration; skipping import."
    SKIP_IMPORT=1
fi

bucket_keys_region() {
    # Print the bucket's keys array region for permission checks.
    # wget exit status is checked separately: in a pipeline the shell only
    # sees sed's status, which would mask fetch failures as "no access".
    BUCKET_JSON=$(wget -qO- --header="${AUTH}" "${ADMIN}/v1/bucket?globalAlias=bifrost-docs" 2>/dev/null) \
        || fail "could not fetch bucket state"
    [ -n "${BUCKET_JSON}" ] || fail "empty bucket state response"
    printf '%s' "${BUCKET_JSON}" | sed -n '/"keys": *\[/,/"objects":/p'
}

key_has_full_access() {
    # True when the entry for the configured key itself holds
    # read/write/owner. Flags are matched per entry (split on entry
    # boundaries), never across the whole keys array, so another key's
    # permissions cannot satisfy this check. Spacing after colons varies
    # (compact vs pretty JSON), so it is allowed in every pattern.
    KEYS_REGION=$(bucket_keys_region) || return 1
    # Newlines/tabs are folded to spaces first so the matcher below needs
    # no escape-heavy whitespace classes (portable across mawk/busybox/gawk).
    printf '%s' "${KEYS_REGION}" | tr '\n\t' '  ' | awk -v id="${GARAGE_ACCESS_KEY_ID}" '
        { buf = buf $0 }
        END {
            n = split(buf, recs, /}, *{/)
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

# Import access key with the configured secret, unless the lookup above
# already proved the stored secret matches. Any rejection fails loudly;
# a stale grant from an older secret can never satisfy this run.
if [ "${SKIP_IMPORT}" != "1" ]; then
    if wget -qO /dev/null \
        --header="${AUTH}" \
        --header="Content-Type: application/json" \
        --post-data="{\"accessKeyId\":\"${GARAGE_ACCESS_KEY_ID}\",\"secretAccessKey\":\"${GARAGE_SECRET_ACCESS_KEY}\",\"name\":\"bifrost-docs-key\"}" \
        "${ADMIN}/v1/key/import" 2>/dev/null; then
        echo "[garage-init] Key imported."
    else
        fail "key import request failed"
    fi
fi

# Grant key full access to bucket; any failure fails the container.
if wget -qO /dev/null \
    --header="${AUTH}" \
    --header="Content-Type: application/json" \
    --post-data="{\"bucketId\":\"${BUCKET_ID}\",\"accessKeyId\":\"${GARAGE_ACCESS_KEY_ID}\",\"permissions\":{\"read\":true,\"write\":true,\"owner\":true}}" \
    "${ADMIN}/v1/bucket/allow" 2>/dev/null; then
    echo "[garage-init] Key permissions set."
else
    fail "bucket permission grant request failed"
fi

# Confirm the key itself actually holds read/write/owner before success.
if key_has_full_access; then
    echo "[garage-init] Key verified with read/write/owner on bucket."
else
    fail "key ${GARAGE_ACCESS_KEY_ID} lacks read/write/owner on bucket after grant"
fi
echo "[garage-init] Initialization complete."
