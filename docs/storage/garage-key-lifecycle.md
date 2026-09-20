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
  `s3.env` on the `garage-creds` Docker volume, consumed by **api and
  worker** via `BIFROST_DOCS_S3_CREDENTIALS_FILE` (both mount the volume
  read-only; the worker runs the same image). Explicit
  `BIFROST_DOCS_S3_ACCESS_KEY`/`_SECRET_KEY` env still wins when set.
- **Cross-container ownership.** garage-init runs as root (alpine) while
  the app runs as `app`; a root-owned 0600 file would be unreadable. The
  Dockerfile pins `app` to uid/gid 15000 and init chowns both state files
  to `GARAGE_CREDS_UID:GARAGE_CREDS_GID` (default 15000, set in compose)
  before locking to mode 600 — owner-readable, non-world-readable,
  verified: uid 15000 reads, any other UID is denied.
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

- Mode auto-selects with no operator action: a legacy pair in `.env`
  selects import mode (existing deployments behave exactly as before, #99
  verification intact); its absence selects managed mode (new deployments
  mint natively, only `GARAGE_ADMIN_TOKEN` required); a partial pair fails
  closed naming the missing half. Explicit `GARAGE_KEY_MODE` always wins.
- Move an existing install to managed only via an explicit rotation
  window, never implicitly: adopt the minted key, restart api+worker, then
  revoke the legacy grant.
- API precedence (atomic pair): both explicit keys or neither (a partial
  explicit pair fails startup); otherwise the credentials file, which must
  contain both values; otherwise unconfigured (S3 off). `dev.yml` fixture
  overrides are untouched.
- Worker mounts the same credentials volume read-only and loads the file
  at startup: include `worker` in every restart check and in rotation
  (restart both `api` and `worker` before revoking).

## Runbook

- Clean install: `up -d` (init runs automatically). Verify with
  `docker compose logs garage-init` (key ID, no secret).
- Restart: `up -d` again; init reuses the key and rewrites the file.
- Rotate: `GARAGE_ROTATE=1 up garage-init`, restart **both `api` and
  `worker`** (both read the credentials file at startup), then
  `GARAGE_REVOKE_KEY_ID=<old-id> up garage-init`. Restarting only one
  leaves the other on the superseded key until its next restart.
- Recover lost volume: restart `garage-init`; the file is rebuilt from the
  stored secret. If the key itself was deleted cluster-side, init mints a
  fresh one (data remains; bucket alias is stable).
- Recover lost volume after rotation: the re-run fails closed naming the
  detected rotated generations (it will not fall back to the possibly
  revoked base key). Restore `s3.keyname` from backup — or from the
  `Rotated: new key <id> (<name>)` log line — then re-run. Never delete
  rotated keys to clear this error; that destroys the only record of the
  active generation.
- Restore from backup: `GARAGE_KEY_MODE=import` with the legacy pair.

## Live proof (VM101, isolated project, torn down after)

Clean install mints one key; restart reuses (inventory stays 1);
`api`+`worker` read the 0600 file as uid 15000; sha-verified S3 PUT/GET
as the app user before and after rotation; rotation mints + repoints;
revoked key denied (`http=403 code=AccessDenied` on PUT and GET from a
root-context probe) with the active key round-tripping in the same pass.
