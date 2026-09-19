#!/bin/sh
# Garage initialization script.
# Runs as a one-shot container (alpine:3) after Garage is healthy.
# Idempotent: safe to re-run on stack restarts.
set -e

ADMIN="http://garage:3903"
AUTH="Authorization: Bearer ${GARAGE_ADMIN_TOKEN}"

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

# Import access key with deterministic credentials (idempotent)
wget -qO /dev/null \
  --header="${AUTH}" \
  --header="Content-Type: application/json" \
  --post-data="{\"accessKeyId\":\"${GARAGE_ACCESS_KEY_ID}\",\"secretAccessKey\":\"${GARAGE_SECRET_ACCESS_KEY}\",\"name\":\"bifrost-docs-key\"}" \
  "${ADMIN}/v1/key/import" 2>/dev/null || true

echo "[garage-init] Key imported."

# Grant key full access to bucket (idempotent)
wget -qO /dev/null \
  --header="${AUTH}" \
  --header="Content-Type: application/json" \
  --post-data="{\"bucketId\":\"${BUCKET_ID}\",\"accessKeyId\":\"${GARAGE_ACCESS_KEY_ID}\",\"permissions\":{\"read\":true,\"write\":true,\"owner\":true}}" \
  "${ADMIN}/v1/bucket/allow" 2>/dev/null || true

echo "[garage-init] Key permissions set. Initialization complete."
