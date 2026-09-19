# Skra architecture recovery plan

This plan turns the September 18 architecture review into work that can be
verified and merged. The product rename is a separate change and should land
first. Paths below use the current checkout; the rename does not change their
locations.

## Decision before implementation

Keep Skra as a documentation application with a single FastAPI API and React
client. Do not start a rewrite or extract services to pursue IT Glue or Hudu
parity. Fix the observable authorization and indexing contracts first, then
reduce deployment and client duplication. The Docs-to-Bifrost boundary in
`docs/plans/2026-04-24-docs-to-bifrost-sync-boundary.md` still applies:
Bifrost runs connectors; Skra owns documentation mapping and reconciliation.

## 1. Define organization access before changing auth

`api/src/core/auth.py` had contradictory comments about organization scope,
which this PR corrects. `get_execution_context()` returns `org_id=None` for
every user. The historical V1 plan deliberately chose global roles. That
contract is recorded in `docs/architecture/001-organization-access.md`.
Verify how each router authorizes records, and keep the global view and
persisted `currentOrg` in
`client/src/stores/organization.store.ts` consistent with it. Do not recreate
membership tables without a new tenant design.

Acceptance: tests cover a contributor's access to two organizations, disabled
organizations, global list/search endpoints, and API keys. A user cannot read
or mutate a record above the permissions of their global role. Issue #73
tracks this matrix. Rollback: revert individual route changes while preserving
the existing role checks.

## 2. Make session and API-key authorization consistent

`api/src/core/auth.py` builds JWT principals from claims, while API-key
authentication loads the user from PostgreSQL and checks `is_active`. Audit
what happens when a user's role changes, account is disabled, or MFA is
required. Keep OIDC as an option and retain the existing authentication code
unless this audit demonstrates a concrete need to replace it.

Acceptance: integration tests cover account disablement and role changes for
both JWT and API keys, login MFA, and OIDC callbacks. Choose a revocation
mechanism and token lifetime from those requirements; a Valkey denylist is a
candidate, not yet a decision. Rollback: a versioned token policy with the
previous lifetime available during rollout.

## 3. Repair the existing indexing queue

`api/src/services/indexing_queue.py` uses arq and creates a pool for each
enqueue. Its remove job omits `org_id`; index jobs include it. The worker is
`api/src/worker.py`, and `api/src/services/reindex_state.py` expires progress
after 24 hours. Trace delete/disable behavior and search fallback before
changing queue infrastructure. RabbitMQ is not part of this observed path.

Acceptance: indexing and removal have explicit organization identity and
idempotent retries; a deletion cannot leave a searchable record; a failed
enqueue is visible to operators; reindex history remains inspectable for the
agreed retention period. Use a shared, closed pool and test worker behavior
with a real queue. Rollback: pause indexing and rebuild the index from source
records after correcting the job contract.

## 4. Simplify deployment after the data path is proven

`docker-compose.test.yml` uses Redis while the development overlay uses
Valkey. Confirm which production deployment targets are maintained before
removing any files. Keep backup and restore working across the rename; a new
Compose project name can otherwise create empty volumes that look like data
loss.

Acceptance: fresh install, upgrade with existing volumes, backup/restore,
worker startup, and TLS smoke checks pass on each supported target. Test and
development use the same queue implementation. Rollback: retain previous
overlays and volume mapping until the migration rehearsal passes.

## 5. Consolidate frontend data access incrementally

`client/src/lib/api-client.ts` retains Axios beside the generated `$api`
client. The persisted organization store also affects query scope. Migrate
one entity at a time to shared query keys and one API client, then remove the
old path when no callers remain. Confirm that `client/package.json` type
generation targets the intended API origin in local and Docker workflows.

Acceptance: switching organizations and global view cannot show cached data
from another scope. Mutations invalidate the matching lists and details.
Column preferences have one source of truth. Run the client typecheck and
browser tests for each migrated entity. Rollback: revert the individual hook
migration without changing server contracts.

## First tranche

1. Land the product rename with its data migration notes and full available
   checks. Record Docker checks that cannot run locally.
2. Open one architecture decision issue for organization access, with the
   role/organization/API-key test matrix as its acceptance criteria.
3. Fix the indexing remove-job scope as the first contained code change after
   that decision. Keep the other phases as separate, reviewable changes.

This plan is based on code inspection and the September 18 Muse review.
Specific risk claims are hypotheses until the acceptance tests reproduce
them. The historical `PLAN.md` and older roadmap are not implementation
evidence for current behavior.
