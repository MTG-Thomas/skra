# Organization access in the single-MSP deployment

Status: existing V1 behavior, recorded 2026-09-19

## Decision

Skra's current deployment has one MSP workspace. Authenticated users have a
global role (`reader`, `contributor`, `administrator`, or `owner`) across that
workspace. Organizations are client documentation partitions. They are not
independent tenants or an authorization boundary between users of the same
workspace.

An organization ID in an API route selects the records to read or change.
The browser's persisted `currentOrg` selects a navigation context. Neither
one grants permission. The API must enforce the user's global role for every
operation, including API-key requests and global list/search routes.

This records the deliberate V1 choice in
`docs/plans/2026-01-13-remove-user-org-scoping.md`. Migration `020` removed
`user_organizations` and `api_keys.organization_id`, and
`get_execution_context()` in `api/src/core/auth.py` returns `org_id=None` for
every user. This decision also corrects the stale `ExecutionContext` comments
that described the former membership model.

## Consequences

- A reader may view permitted records in every client organization. A
  contributor may edit permitted records in every client organization. Admin
  and owner capabilities remain gated by their global roles.
- An API key inherits the current role and active state of its owning user.
  It has no organization scope under this model.
- Disabled organizations and disabled records need explicit, consistent
  visibility rules across org routes, global routes, search, and exports.
- The UI must never use `currentOrg` as evidence of authorization. Query keys
  must still include organization or global scope to avoid showing stale data.

## Required verification

Issue #73 tracks the enforcement work. Integration tests should cover two
organizations, every role, API keys, disabled organizations, org routes,
global lists, and search. Tests must confirm that a role cannot perform an
operation above its level, regardless of organization ID or browser state.

## Future tenant boundary

If Skra serves unrelated MSPs in one deployment, introduce a separate tenant
identity and migration. Do not infer tenancy from the existing organization
ID or revive `user_organizations` without defining tenant-owned users, keys,
roles, storage, search, background jobs, and exports together.
