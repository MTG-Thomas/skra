#!/usr/bin/env bash
set -euo pipefail

# --- Provisioned-file preservation ---
# config/garage.toml is TRACKED in git (dev defaults committed) while .env
# is git-ignored. A `git checkout --force` therefore restores the dev admin
# token over a provisioned one, which breaks garage-init auth (403) and
# wedges every service gated on garage-init completion. These helpers stash
# a modified tracked file aside before checkout and restore it afterwards,
# falling back to legacy pre-rename trees on a fresh box.
preserve_provisioned_file() {
  # $1 = repo root, $2 = tracked path (relative). Prints the backup path,
  # or nothing when the working copy is unmodified or missing.
  local root="$1" rel="$2"
  [ -f "${root}/${rel}" ] || return 0
  if ( cd "${root}" && git diff --quiet -- "${rel}" 2>/dev/null ); then
    return 0
  fi
  local backup_dir; backup_dir="$(mktemp -d)"
  cp "${root}/${rel}" "${backup_dir}/$(basename "${rel}")"
  printf '%s\n' "${backup_dir}/$(basename "${rel}")"
}

restore_provisioned_file() {
  # $1 = repo root, $2 = tracked path (relative), $3 = backup path (maybe
  # empty). Restores the backup; otherwise seeds from the first legacy tree
  # holding the file; otherwise leaves the checkout version in place.
  local root="$1" rel="$2" backup="${3:-}" candidate
  if [ -n "${backup}" ] && [ -f "${backup}" ]; then
    cp "${backup}" "${root}/${rel}"
    rm -rf "$(dirname "${backup}")"
    return 0
  fi
  for candidate in "${LEGACY_WORKTREE:-}" \
      /home/thomas/deploy/bifrost-docs-main \
      /home/thomas/workspace/bifrost-docs; do
    [ -n "${candidate}" ] || continue
    if [ -f "${candidate}/${rel}" ]; then
      mkdir -p "${root}/$(dirname "${rel}")"
      cp "${candidate}/${rel}" "${root}/${rel}"
      return 0
    fi
  done
  return 0
}

# Harness seam: sourcing with SKRA_DEPLOY_LIB_ONLY=1 loads the helpers above
# without running a deployment (see scripts/tests/test_deploy_test_vm.sh).
if [ "${SKRA_DEPLOY_LIB_ONLY:-}" = "1" ]; then
  return 0 2>/dev/null || exit 0
fi

REPO_URL="${REPO_URL:-https://github.com/MTG-Thomas/skra.git}"
BRANCH="${BRANCH:-main}"
DEPLOY_SHA="${DEPLOY_SHA:?DEPLOY_SHA is required}"
DEPLOY_SHA_SHORT="${DEPLOY_SHA_SHORT:-${DEPLOY_SHA:0:7}}"
DEPLOY_ROOT="${DEPLOY_ROOT:-/home/thomas/deploy/skra-main}"
LEGACY_WORKTREE="${LEGACY_WORKTREE:-/home/thomas/workspace/skra}"
HEALTH_URL="${HEALTH_URL:-https://dev.docs.midtowntg.com/health}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-skra-dev}"
COMPOSE_FILES=(
  -p "${COMPOSE_PROJECT}"
  -f docker-compose.yml
  -f docker-compose.test-vm.yml
)
# Targets without TLS termination (no /etc/letsencrypt, e.g. the LXC
# validation host) set SKRA_TARGET_SSL=0 to skip the ssl compose file.
if [ "${SKRA_TARGET_SSL:-1}" != "0" ]; then
  COMPOSE_FILES+=(-f docker-compose.ssl.yml)
fi

API_IMAGE="${SKRA_API_IMAGE:-ghcr.io/mtg-thomas/skra-api:${DEPLOY_SHA_SHORT}}"
CLIENT_IMAGE="${SKRA_CLIENT_IMAGE:-ghcr.io/mtg-thomas/skra-client:${DEPLOY_SHA_SHORT}}"

mkdir -p "$(dirname "${DEPLOY_ROOT}")"

if [ ! -d "${DEPLOY_ROOT}/.git" ]; then
  git clone "${REPO_URL}" "${DEPLOY_ROOT}"
fi

# Stash a provisioned config/garage.toml before checkout clobbers it with
# the tracked dev defaults (see helpers above). No-op on fresh clones.
GARAGE_BACKUP="$(preserve_provisioned_file "${DEPLOY_ROOT}" config/garage.toml)"

cd "${DEPLOY_ROOT}"
git fetch origin "${BRANCH}" --tags
git checkout --force "${DEPLOY_SHA}"
git clean -fd \
  -e .env \
  -e config/garage.toml

# Restore the provisioned copy, else seed from a legacy pre-rename tree.
restore_provisioned_file "${DEPLOY_ROOT}" config/garage.toml "${GARAGE_BACKUP}"

if [ ! -f .env ] && [ -f "${LEGACY_WORKTREE}/.env" ]; then
  cp "${LEGACY_WORKTREE}/.env" .env
fi

export SKRA_API_IMAGE="${API_IMAGE}"
export SKRA_CLIENT_IMAGE="${CLIENT_IMAGE}"

docker compose "${COMPOSE_FILES[@]}" pull init api worker client
docker compose "${COMPOSE_FILES[@]}" up -d --remove-orphans
docker image prune -f

for attempt in {1..30}; do
  if curl -fsS "${HEALTH_URL}" >/dev/null; then
    docker compose "${COMPOSE_FILES[@]}" ps
    echo "Deployment healthy: ${HEALTH_URL}"
    exit 0
  fi
  sleep 5
done

docker compose "${COMPOSE_FILES[@]}" ps
if [ "${SKRA_TARGET_SSL:-1}" != "0" ]; then
  docker compose "${COMPOSE_FILES[@]}" logs --tail=120 api client ssl-proxy
else
  docker compose "${COMPOSE_FILES[@]}" logs --tail=120 api client
fi
echo "Deployment did not become healthy: ${HEALTH_URL}" >&2
exit 1
