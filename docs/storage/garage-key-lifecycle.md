# Garage key lifecycle (issues #107, #109)

## Problem

`garage-init` minted deterministic `GARAGE_ACCESS_KEY_ID` values through
`POST /v1/key/import`. The Garage Admin API v1.3.1 spec reserves import for
migrations and backup restore and warns against routine use for custom key
IDs, because storage-layer key lookup conventions may change. Preseeded
credentials also cannot rotate without operator surgery outside the stack.

## Design (implemented)

Garage-native lifecycle with one file-based secret handoff:

- **Managed mode (default).** First run creates a key via `POST /v1/key`
  (AddKey); Garage mints ID + secret. The secret is written once to
  `s3.env` (mode 600) on the `garage-creds` Docker volume, consumed by the
  API via `BIFROST_DOCS_S3_CREDENTIALS_FILE`. Explicit
  `BIFROST_DOCS_S3_ACCESS_KEY`/`_SECRET_KEY` env still wins when set.
- **Idempotent rerun.** The active key name persists in `s3.keyname` next
  to the credentials. Reruns find the key by exact name (`GET /v1/key?list`),
  re-fetch the secret (`showSecretKey=true`), and rewrite the file — a lost
  volume self-heals; restarts never mint duplicates. Ambiguity fails closed.
- **Explicit rotation.** `GARAGE_ROTATE=1` mints a timestamped key, repoints
  the file, and prints superseded IDs. After restarting dependents, a
  follow-up run with `GARAGE_REVOKE_KEY_ID=<id>` deactivates the old grant
  (`POST /v1/bucket/deny`; full `DELETE /v1/key` stays manual — busybox
  wget cannot send DELETE).
- **Import mode (restore-only).** `GARAGE_KEY_MODE=import` keeps the legacy
  deterministic import for backup-restore and adoption, with the #99
  secret-match verification. Not the default; never used routinely.
- **Never prints secrets.** Only key IDs and names reach stdout (tested).

## Migration / backward compatibility

- Existing deployments already run the imported key: keep them on
  `GARAGE_KEY_MODE=import` (unchanged behavior, #99 verification intact).
  Move to managed only via an explicit rotation window, never implicitly.
- New deployments get managed mode with no preshared key material: the
  only required secret is `GARAGE_ADMIN_TOKEN`.
- API precedence (unchanged behavior when file absent): explicit env >
  credentials file > unconfigured (S3 off). `dev.yml` fixture overrides
  are untouched.
- Worker mounts nothing new (it sets no S3 env today); if a worker S3 path
  appears later, mount the same volume read-only.

## Runbook

- Clean install: `up -d` (init runs automatically). Verify with
  `docker compose logs garage-init` (key ID, no secret).
- Restart: `up -d` again; init reuses the key and rewrites the file.
- Rotate: `GARAGE_ROTATE=1 up garage-init`, restart `api`, then
  `GARAGE_REVOKE_KEY_ID=<old-id> up garage-init`.
- Recover lost volume: restart `garage-init`; the file is rebuilt from the
  stored secret. If the key itself was deleted cluster-side, init mints a
  fresh one (data remains; bucket alias is stable).
- Restore from backup: `GARAGE_KEY_MODE=import` with the legacy pair.

## Live proof (pending VM handoff)

Clean install + restart + rotation against real Garage v1.3.1 on VM101
after lane #111 tears down: isolated project, stub-free, verifying
`showSecretKey` round-trip, file perms, and post-revoke inaccessibility.
