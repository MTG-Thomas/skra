# Skra rename — data & operator migration guide

For existing `bifrost-docs` installs moving to `skra`. Fresh installs: use the
new names directly, nothing below applies except the registry note.

## Env vars

Every `BIFROST_DOCS_*` variable is now `SKRA_*` (same suffix). For one release
the API reads `BIFROST_DOCS_*` as a fallback when the `SKRA_*` counterpart is
unset and logs a `DeprecationWarning` per key. Migrate `.env` at leisure, then
the shim is removed. Precedence: explicit init arg > `SKRA_*` > `BIFROST_DOCS_*` >
default. The migrator CLI accepts `SKRA_API_URL`/`SKRA_API_TOKEN` with the
`BIFROST_*` names as fallback; `plan.json` files may use `skra_id` (legacy
`bifrost_id` still read).

## What needs no action

- **Encrypted secrets (passwords, TOTP, custom-asset fields):** the HKDF info
  string (`bifrost-docs-secrets-encryption`) and default `fernet_salt` are
  frozen on purpose. Secrets decrypt exactly as before.
- **API keys:** pre-rename `bifrost_docs…` keys keep authenticating (HTTP +
  WebSocket). New keys are issued with the `skra_` prefix. Rotate at leisure.
- **TOTP:** the issuer string is display-only. Existing authenticator entries
  keep working; only newly enrolled ones show `Skra`.
- **WebAuthn:** only the RP display name changed; RP ID is hostname-based.

## What needs action

- **Re-login after deploy.** JWT issuer/audience changed to `skra-api` /
  `skra-client`, so all sessions invalidate. Browser `localStorage` persist
  keys changed (`skra-auth`, `skra-organization`); stale keys are orphaned
  and harmless.
- **Postgres.** Compose defaults are now user/db `skra` (test: `skra` /
  `skra_test`). Existing volumes keep working untouched — but if you want the
  names to match: `pg_dump`, recreate, restore; or
  `ALTER DATABASE bifrost_docs RENAME TO skra` (no connections) plus matching
  `SKRA_DATABASE_URL`. Backup first; rollback is restoring the dump.
- **S3 / Garage / Azure.** New default bucket/container is `skra`. Existing
  buckets keep serving. To consolidate: create `skra`, mirror
  (`mc mirror old/skra-bucket new/skra`), verify object counts, flip
  `SKRA_S3_BUCKET`, keep the old bucket until verified. Same pattern for the
  Azure container.
- **Docker volumes.** `skra-postgres_data` etc. are new empty volumes. Either
  adopt them with a dump/restore, or pin the old volume names in compose to
  keep data in place (simplest for dev).
- **Images.** Pull `ghcr.io/mtg-thomas/skra-api` / `skra-client`. Old
  `bifrost-docs-*` tags stay pullable until cleanup; do not delete them until
  validation passes.
- **Prometheus dashboards.** Metric prefix changed `bifrost_docs_*` →
  `skra_*`. Update queries/alerts; expect a series break at deploy.
- **Azure proof resources** (`rg-bifrost-docs-neon-dev`, container app, KV
  secret name now `skra-secret-key` in bicep). Live cloud names were NOT
  renamed — re-provision to consolidate, or leave (functional as-is).

## Registry note

PyPI/npm `skra` were free at rename time but are unreserved (no credentials in
this environment) — claim both on first publish. A small unrelated Go address
book already exists at `github.com/johannesheinz/skra`; our images are
org-namespaced (`ghcr.io/mtg-thomas/skra-*`), so there is no technical
collision, only shared search results.
