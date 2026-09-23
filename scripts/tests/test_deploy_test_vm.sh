#!/bin/bash
# Harness tests for the provisioned-file helpers in scripts/deploy-test-vm.sh.
# No Docker, no VM, no network: fixture git repos under mktemp exercise the
# real preserve/restore functions against tracked config/garage.toml.
# Run: ./scripts/tests/test_deploy_test_vm.sh  (from the repo root)
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$ROOT/scripts/deploy-test-vm.sh"
PASS=0
FAIL=0

command -v git >/dev/null 2>&1 || { echo "SKIP: git missing"; exit 2; }

# Sourcing enables `set -e` in this shell; expected-failure paths below
# need it off again.
SKRA_DEPLOY_LIB_ONLY=1 source "$SCRIPT"
set +e

ok() { PASS=$((PASS + 1)); echo "ok: $1"; }
bad() { FAIL=$((FAIL + 1)); echo "FAIL: $1"; }

fixture_repo() {
  # $1 = dir. Creates a git repo with tracked config/garage.toml holding
  # "dev-token" content. Prints nothing.
  local dir="$1"
  mkdir -p "$dir/config"
  ( cd "$dir" && git init -q && git config user.email t@t && git config user.name t \
    && echo "dev-token" > config/garage.toml && git add config/garage.toml \
    && git commit -qm init )
}

t_preserve_modified_file() {
  local wd; wd=$(mktemp -d)
  fixture_repo "$wd/repo"
  echo "provisioned-token" > "$wd/repo/config/garage.toml"
  local backup; backup=$(preserve_provisioned_file "$wd/repo" config/garage.toml)
  if [ -n "$backup" ] && [ -f "$backup" ] \
      && [ "$(cat "$backup")" = "provisioned-token" ]; then
    ok "preserve backs up a modified tracked file"
  else
    bad "preserve did not back up the modified file"
  fi
  rm -rf "$wd"
}

t_preserve_unmodified_is_noop() {
  local wd; wd=$(mktemp -d)
  fixture_repo "$wd/repo"
  local backup; backup=$(preserve_provisioned_file "$wd/repo" config/garage.toml)
  if [ -z "$backup" ]; then
    ok "preserve is a no-op for an unmodified file"
  else
    bad "preserve backed up an unmodified file"
  fi
  rm -rf "$wd"
}

t_restore_survives_checkout() {
  # End-to-end of the deploy sequence: provision, preserve, checkout
  # (clobbers), clean, restore.
  local wd; wd=$(mktemp -d)
  fixture_repo "$wd/repo"
  echo "provisioned-token" > "$wd/repo/config/garage.toml"
  local backup; backup=$(preserve_provisioned_file "$wd/repo" config/garage.toml)
  ( cd "$wd/repo" && git checkout -q -- config/garage.toml \
    && git clean -qfd -e config/garage.toml )
  [ "$(cat "$wd/repo/config/garage.toml")" = "dev-token" ] || {
    bad "fixture checkout did not clobber (test setup wrong)"; rm -rf "$wd"; return; }
  restore_provisioned_file "$wd/repo" config/garage.toml "$backup"
  if [ "$(cat "$wd/repo/config/garage.toml")" = "provisioned-token" ]; then
    ok "restore brings back the provisioned file after checkout"
  else
    bad "restore did not bring back the provisioned file"
  fi
  rm -rf "$wd"
}

t_restore_seeds_from_legacy() {
  # Fresh box: no backup, checkout holds dev defaults, legacy tree holds
  # the provisioned file.
  local wd; wd=$(mktemp -d)
  fixture_repo "$wd/repo"
  mkdir -p "$wd/legacy/config"
  echo "legacy-token" > "$wd/legacy/config/garage.toml"
  LEGACY_WORKTREE="$wd/legacy" \
    restore_provisioned_file "$wd/repo" config/garage.toml ""
  if [ "$(cat "$wd/repo/config/garage.toml")" = "legacy-token" ]; then
    ok "restore seeds from the legacy tree when no backup exists"
  else
    bad "restore did not seed from the legacy tree"
  fi
  rm -rf "$wd"
}

t_restore_leaves_checkout_without_source() {
  local wd; wd=$(mktemp -d)
  fixture_repo "$wd/repo"
  LEGACY_WORKTREE="$wd/does-not-exist" \
    restore_provisioned_file "$wd/repo" config/garage.toml ""
  if [ "$(cat "$wd/repo/config/garage.toml")" = "dev-token" ]; then
    ok "restore leaves the checkout version when no source exists"
  else
    bad "restore altered the file with no source available"
  fi
  rm -rf "$wd"
}

t_preserve_modified_file
t_preserve_unmodified_is_noop
t_restore_survives_checkout
t_restore_seeds_from_legacy
t_restore_leaves_checkout_without_source

echo "pass=$PASS fail=$FAIL"
[ "$FAIL" -eq 0 ]
