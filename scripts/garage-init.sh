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

bucket_keys_region() {
    # Print the bucket's keys array region for permission checks.
    wget -qO- --header="${AUTH}" "${ADMIN}/v1/bucket?globalAlias=bifrost-docs" 2>/dev/null \
        | sed -n '/"keys": *\[/,/"objects":/p' || fail "could not fetch bucket state"
}

key_has_full_access() {
    # True when the configured key holds read/write/owner on the bucket.
    # Spacing after colons varies (compact vs pretty JSON), so allow it.
    KEYS_REGION=$(bucket_keys_region) || return 1
    printf '%s' "${KEYS_REGION}" | grep -q "\"accessKeyId\": *\"${GARAGE_ACCESS_KEY_ID}\"" &&
        printf '%s' "${KEYS_REGION}" | grep -q '"read": *true' &&
        printf '%s' "${KEYS_REGION}" | grep -q '"write": *true' &&
        printf '%s' "${KEYS_REGION}" | grep -q '"owner": *true'
}

if key_has_full_access; then
    echo "[garage-init] Key already has read/write/owner on bucket; nothing to do."
    echo "[garage-init] Initialization complete."
    exit 0
fi

# Import access key. A repeated import of an existing key can fail here;
# the grant and the final confirmation below arbitrate the real outcome.
IMPORT_OK=1
if wget -qO /dev/null \
    --header="${AUTH}" \
    --header="Content-Type: application/json" \
    --post-data="{\"accessKeyId\":\"${GARAGE_ACCESS_KEY_ID}\",\"secretAccessKey\":\"${GARAGE_SECRET_ACCESS_KEY}\",\"name\":\"bifrost-docs-key\"}" \
    "${ADMIN}/v1/key/import" 2>/dev/null; then
    IMPORT_OK=0
    echo "[garage-init] Key imported."
fi

# Grant key full access to bucket.
if wget -qO /dev/null \
    --header="${AUTH}" \
    --header="Content-Type: application/json" \
    --post-data="{\"bucketId\":\"${BUCKET_ID}\",\"accessKeyId\":\"${GARAGE_ACCESS_KEY_ID}\",\"permissions\":{\"read\":true,\"write\":true,\"owner\":true}}" \
    "${ADMIN}/v1/bucket/allow" 2>/dev/null; then
    echo "[garage-init] Key permissions set."
fi

# Confirm the key actually holds read/write/owner before declaring success.
# This is the arbiter: a failed import or grant cannot print success.
if key_has_full_access; then
    echo "[garage-init] Key verified with read/write/owner on bucket."
else
    if [ "${IMPORT_OK}" -ne 0 ]; then
        fail "key import failed and key ${GARAGE_ACCESS_KEY_ID} has no bucket access"
    else
        fail "key ${GARAGE_ACCESS_KEY_ID} lacks read/write/owner on bucket after grant"
    fi
fi
echo "[garage-init] Initialization complete."
