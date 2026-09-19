#!/bin/bash
# Trivy image gate for the published API/worker image (issue #82, #84).
# Runs the same HIGH/CRITICAL gate as .github/workflows/ci.yml so local,
# VM, and CI runs share one definition. Requires the trivy binary.
# Usage: ./scripts/trivy-image-gate.sh <image-ref> [trivy-bin]
#   image-ref: e.g. ghcr.io/mtg-thomas/bifrost-docs-api:<sha>
#   trivy-bin: path to trivy (default: trivy on PATH)

set -e

IMAGE_REF=${1:?Usage: $0 <image-ref> [trivy-bin]}
TRIVY_BIN=${2:-trivy}

# Must run from the repository root so .trivyignore.yaml is discovered the
# same way CI discovers it (trivy-action runs in the workspace root).
cd "$(dirname "$0")/.."

exec "$TRIVY_BIN" image \
    --severity HIGH,CRITICAL \
    --scanners vuln \
    --vuln-type os,library \
    --ignore-unfixed \
    --ignorefile .trivyignore.yaml \
    --no-progress \
    --exit-code 1 \
    --format table \
    "$IMAGE_REF"
