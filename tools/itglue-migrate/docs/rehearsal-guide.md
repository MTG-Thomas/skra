# Migration Rehearsal Guide

This guide explains how to use the seeded migration fixture for testing and rehearsing IT Glue migrations.

## Quick Start

### Prerequisites

1. Bifrost Docs API running locally or in a test environment
2. Valid API token for the Bifrost Docs API
3. Migration tool installed: `cd tools/itglue-migrate && pip install -e ".[dev]"`

### Run Rehearsal Migration

```bash
# Navigate to migration tool
cd tools/itglue-migrate

# Set your API credentials
export BIFROST_API_URL="http://localhost:8080"
export BIFROST_TOKEN="your-api-token-here"

# 1. Preview the migration
python -m itglue_migrate.cli preview \
    --export ../../tests/fixtures/minimal-export \
    --api-url $BIFROST_API_URL \
    --token $BIFROST_TOKEN \
    --output /tmp/test-migration-plan.json

# 2. Run in dry-run mode first
python -m itglue_migrate.cli run \
    --export ../../tests/fixtures/minimal-export \
    --plan /tmp/test-migration-plan.json \
    --api-url $BIFROST_API_URL \
    --token $BIFROST_TOKEN \
    --dry-run

# 3. If dry-run looks good, run for real
python -m itglue_migrate.cli run \
    --export ../../tests/fixtures/minimal-export \
    --plan /tmp/test-migration-plan.json \
    --api-url $BIFROST_API_URL \
    --token $BIFROST_TOKEN

# 4. For API-state reconciliation rehearsals, run sync with a report artifact
python -m itglue_migrate.cli sync \
    --export-path ../../tests/fixtures/minimal-export \
    --api-url $BIFROST_API_URL \
    --token $BIFROST_TOKEN \
    --all \
    --dry-run \
    --reconciliation-output /tmp/test-reconciliation-report.json
```

## What the Fixture Contains

The `minimal-export` fixture is a complete but minimal IT Glue export with:

- **2 Organizations**: "Acme Corp Test" and "Test Technologies Inc"
- **2 Configurations**: A test server and a test workstation
- **1 Document**: A test onboarding guide document
- **1 Location**: A test main office location
- **2 Passwords**: Test admin and user passwords

All data is synthetic and clearly labeled as test data. It is safe to commit to version control and safe to migrate into test environments.

## Use Cases

### 1. CI/CD Testing

The smoke test (`tests/integration/test_migration_smoke.py`) validates:
- Export structure validation passes
- All CSV files are parseable
- ImportContext can be created
- Plan generation works

Run in CI:
```bash
cd tools/itglue-migrate
pytest tests/integration/test_migration_smoke.py -v --tb=short
```

### 2. Local Development

Use the fixture to test migration changes without needing real IT Glue exports:

```bash
# Test field inference changes
python -m itglue_migrate.cli preview --export ../../tests/fixtures/minimal-export ...

# Test new import logic
python -m itglue_migrate.cli run --export ../../tests/fixtures/minimal-export --dry-run ...
```

### 3. Pre-Production Rehearsal

Before running a real customer migration, validate your setup:

1. Deploy Bifrost Docs to a test environment
2. Run the fixture migration against it
3. Verify entities appear correctly in the UI
4. Check logs for any errors

### 4. Reconciliation Reports

Use `--reconciliation-output` with the `sync` command to write a JSON
reconciliation artifact somewhere explicit for a rehearsal or CI run, such as
`/tmp/test-reconciliation-report.json`.

The report includes:

- `schema_version` and generation metadata
- aggregate `summary` counts for operator review (`organization_count`,
  `warning_count`, `error_count`, `failed_count`, `skipped_count`,
  `follow_up_required`, plus per-entity totals)
- one `organizations[]` entry per synced organization
- per-entity counts for planned creates, planned updates, existing, created,
  updated, skipped, duplicate, failed, and errors
- warnings and errors suitable for follow-up triage
- per-org `attachment_summary` with embedded-image mismatch counts in
  `attachment_summary.embedded_images` (`expected_count`, `present_count`,
  `failure_count`, `failures`) and
  `attachment_summary.failure_categories.broken_embedded_image`
- per-org `relationship_summary` with `failed`, `missing_source`,
  `missing_target`, and `transient_error` counts

`summary.follow_up_required` is true when any entity failed, any error was
recorded, any `failure_categories` count is nonzero (including broken
embedded images), or any actionable `relationship_summary` count is nonzero.
Per-org attachment orphaned folders are intentionally not attributed per org
(`attachment_summary.orphaned_scope` is `"not_reported_per_org"`); use the
`preview` plan's `attachment_validation` for global orphaned-folder triage.

Password values are never included in reconciliation output.

### 5. Post-Import Fidelity Verification

After a sync or run, use the read-only `verify` command to check that
migrated attachments and embedded document images survived the import:

```bash
python -m itglue_migrate.cli verify \
    --export-path ../../tests/fixtures/minimal-export \
    --api-url $BIFROST_API_URL \
    --token $BIFROST_TOKEN \
    --all \
    --output /tmp/test-fidelity-report.json
```

- Use `--org "Name"` for a single organization or `--all` for every
  organization in the export.
- Add `--check-urls` to also probe migrated download/image URLs for
  reachability (HEAD with GET fallback). Probes follow an explicit
  allowlist: the API host plus `--allowed-hosts "storage.example.com,..."`.
  Unlisted destinations (including private/link-local redirect targets) are
  refused without a request, and every redirect hop is re-validated. Name
  every storage/image host explicitly; listing an internal host is an
  explicit trust decision. Without `--check-urls`, verification is fully
  offline-safe apart from the required read-only API listing calls.
- The command is read-only: it issues GET requests (plus HEAD/GET probes
  with `--check-urls`) and never creates, updates, or deletes anything.
- Exit code is `0` when clean and `1` when any failure is found, so rehearsal
  CI can gate on it.

Failure categories (shared with the reconciliation vocabulary):

- `missing_upload` — export file (or exported image) with no migrated
  counterpart, or an exported document absent from the API (its images are
  then unverifiable). Same-name files are counted per occurrence, so a
  duplicated filename missing one copy still fails.
- `unexpected_upload` — migrated attachment with no matching export file
- `unresolved_entity` — migrated attachment whose entity could not be matched
  to the export via `metadata.itglue_id` (investigate before deleting), or
  whose record lacks a filename/entity reference and therefore cannot be
  verified at all
- `broken_embedded_image` — embedded image file missing from the export
- `broken_link` — migrated document content still contains a relative image
  link that was never rewritten to a migrated URL
- `inaccessible_url` — migrated download/image URL was not reachable
  (`--check-urls` only)
- `missing_organization` — exported organization absent from the API, so
  nothing under it could be verified
- `api_error` — a read needed for verification failed (attachment listing or
  document fetch); the error text is in the failure message

Each failure carries the organization, entity type, entity/attachment IDs,
filename or document/source reference needed to investigate.

`--output` writes a JSON report (`schema_version`, per-organization
`attachments`/`embedded_images` sections, aggregate `summary` with
`failure_categories` and `follow_up_required`). Because the category keys
match the reconciliation report vocabulary, the per-org `failure_categories`
map can be folded into reconciliation artifacts for combined triage.

For live rehearsals you need a Bifrost Docs API holding migrated fixture
data (local stack or test VM). VM 101 is currently reserved by the rename
lane — coordinate before scheduling rehearsal runs there.

## Extending the Fixture

To add more test scenarios, you can:

1. Add more rows to existing CSV files
2. Add custom asset type CSVs (any filename not in the core list)
3. Create additional fixtures in subdirectories

Example custom asset type:
```csv
# ssl-certificates.csv
id,organization_id,name,expiration_date,vendor,domains,archived
6001,1001,Test SSL Cert,2026-12-31,TestCA,test.example.com,false
```

## Safety Guidelines

- ✅ Always use "Test" or synthetic data in fixtures
- ✅ Include warnings in password notes
- ✅ Use example.com or test domains in URLs
- ✅ Never commit real customer data
- ✅ Mark test organizations clearly

## Troubleshooting

### "Export path does not exist"

Make sure you're running from the `tools/itglue-migrate` directory and using the correct relative path:
```bash
cd tools/itglue-migrate
python -m itglue_migrate.cli preview --export ../../tests/fixtures/minimal-export ...
```

### "No organizations found"

Check that `organizations.csv` exists and has valid data with `id` and `name` columns.

### API connection errors

Verify your API URL and token:
```bash
curl -H "Authorization: Bearer $BIFROST_TOKEN" $BIFROST_API_URL/api/health
```

## Related Documentation

- `docs/plans/MIGRATION_TOOL.md` - Full migration tool documentation
- `tests/fixtures/minimal-export/README.md` - Fixture data reference
- `docs/ROADMAP.md` - Project roadmap and priorities
