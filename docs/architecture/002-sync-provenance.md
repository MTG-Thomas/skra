# Docs-owned sync provenance

Status: implemented for core synced entities, recorded 2026-09-19
Related: #19 (epic), #34 (contract), #35 (provenance UI follow-up),
MTG-Thomas/bifrost#108 (integration contract),
`docs/plans/2026-04-24-docs-to-bifrost-sync-boundary.md`

## Decision

Provenance lives entirely in Docs. Each core synced entity row carries a
nullable `sync_metadata` JSONB column validated by the shared
`SyncMetadata` contract (`api/src/models/contracts/sync.py`). No Bifrost
platform change is required or assumed, per the #108 boundary: mapping,
matching, and provenance interpretation are Docs behavior.

## Contract

`SyncMetadata` identifies the source system and record plus sync state:

| Field | Meaning |
|-------|---------|
| `source_system` | Vendor/upstream system, e.g. `itglue`, `halo`, `bifrost` |
| `source_tenant_id` | Upstream tenant scope the record came from |
| `external_id` | Stable upstream record ID (`source_record_id` accepted as alias) |
| `last_synced_at` | Last observation time (`observed_at` accepted as alias) |
| `sync_status` | Docs-side sync state, e.g. `synced`, `observed` |
| `sync_hash` | Payload hash for change detection (`payload_hash` alias) |
| `source_url` | Optional operator link back to the upstream record |

`extra="forbid"`: unknown fields are rejected so UI (#35) and migrators
can rely on the shape. `sync_metadata_to_storage()` converts a validated
model to the canonical JSON-safe dict written to the column.

## Coverage

| Entity | Table | Since |
|--------|-------|-------|
| Configuration | `configurations` | migration `20260424_100000` |
| Custom asset | `custom_assets` | migration `20260424_100000` |
| Organization | `organizations` | migration `20260919_100000` |
| Location | `locations` | migration `20260919_100000` |
| Document | `documents` | migration `20260919_100000` |
| Password | `passwords` | migration `20260919_100000` |

## Write behavior

- Accepted on `*Create` and `*Update` request bodies as an optional
  `SyncMetadata` object. Omitted means "no provenance change": create
  stores null, update leaves the stored value untouched.
- Only replacing, never merging: an update with `sync_metadata` set
  overwrites the whole provenance object.
- Guards follow the entity's normal write role: contributor or above for
  locations, documents, passwords, configurations, and custom assets;
  administrator for organizations. Provenance is operator/migrator
  attested input, not a trust boundary — any writer with the role can
  set it. Never put secrets in it; password secrets stay in the
  encrypted columns and are never derived from provenance.

## Read behavior

- Returned as `sync_metadata` on every `*Public` response, null when the
  row has no provenance. Absent provenance never fails a read.
- Org scoping is the row's own scoping: org-child rows are served only
  through their organization's routes, so provenance never leaks across
  organizations. Organization rows are the partitions themselves (see
  `001-organization-access.md`); their provenance is visible to any
  authenticated reader of the organization, same as the row.
- Reveal endpoints (e.g. password reveal) include provenance unchanged;
  provenance never carries secret material.

## Follow-ups (out of scope)

- Sync orchestration and matching logic are not part of this contract.
- Provenance display UI is #35 and consumes this contract directly.
