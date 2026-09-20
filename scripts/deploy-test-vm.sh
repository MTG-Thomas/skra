#!/usr/bin/env bash
set -euo pipefail

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
  -f docker-compose.ssl.yml
)

API_IMAGE="${SKRA_API_IMAGE:-ghcr.io/mtg-thomas/skra-api:${DEPLOY_SHA_SHORT}}"
CLIENT_IMAGE="${SKRA_CLIENT_IMAGE:-ghcr.io/mtg-thomas/skra-client:${DEPLOY_SHA_SHORT}}"

mkdir -p "$(dirname "${DEPLOY_ROOT}")"

if [ ! -d "${DEPLOY_ROOT}/.git" ]; then
  git clone "${REPO_URL}" "${DEPLOY_ROOT}"
fi

cd "${DEPLOY_ROOT}"
git fetch origin "${BRANCH}" --tags
git checkout --force "${DEPLOY_SHA}"
git clean -fd \
  -e .env \
  -e config/garage.toml

if [ ! -f .env ] && [ -f "${LEGACY_WORKTREE}/.env" ]; then
  cp "${LEGACY_WORKTREE}/.env" .env
fi

if [ -f "${LEGACY_WORKTREE}/config/garage.toml" ]; then
  cp "${LEGACY_WORKTREE}/config/garage.toml" config/garage.toml
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
docker compose "${COMPOSE_FILES[@]}" logs --tail=120 api client ssl-proxy
echo "Deployment did not become healthy: ${HEALTH_URL}" >&2
exit 1
