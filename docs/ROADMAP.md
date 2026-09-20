# Skra Roadmap

> Date: 2026-04-06
> Scope: Product roadmap derived from `PLAN.md`, docs in `docs/plans/`, and the current GitHub remotes.
> Goal: Make Skra the documentation system of record for Midtown, replace IT Glue, reach Hudu-compatible coverage where it strengthens the product, and integrate natively with `MTG-Thomas/bifrost` for shared integration infrastructure.

---

## Strategic Outcomes

1. **Replace IT Glue for Midtown** with a migration path that is boring, repeatable, and verifiable.
2. **Match Hudu where it matters** for MSP documentation workflows without cloning every adjacent module.
3. **Use Bifrost Integrations as the integration control plane** so Docs reuses connector logic, OAuth handling, secrets, and job execution instead of rebuilding them.
4. **Differentiate on AI, structure, and automation** after the operational foundation is solid.

---

## Current State Snapshot

The product is already beyond MVP.

- Core documentation entities, relationships, attachments, vector search, global views, roles/permissions, TOTP, audit logs, recent/frequent access, AI document mutations, and Mermaid-based diagram support are present in the repo.
- The IT Glue migration tool is implemented but still has hardening, parity, and verification work remaining.
- `PLAN.md` shows the original implementation phases completed through Phase 23, but several integration tests, migration validation tasks, and polish items remain unchecked.
- The GitHub remotes currently do not provide an active issue backlog, so roadmap prioritization should come from repository plans and production goals.

---

## Product Principles

- **Docs first**: Documentation quality and navigability stay primary.
- **Integrations reused, not rewritten**: Bifrost owns connector/runtime complexity; Docs owns mapping, visibility, and reconciliation.
- **Selective parity**: Match IT Glue and Hudu where it reduces operator friction or migration resistance.
- **Operational trust before expansion**: Reliability, testability, auditability, and cutover safety come before broad feature growth.
- **AI with review loops**: AI drafts, cleans, summarizes, and proposes; users approve critical writes.

---

## Roadmap Phases

### Phase 1 - Midtown Cutover Readiness

### Objective

Make Midtown able to migrate from IT Glue and run daily operations in Skra with confidence.

### Priorities

- Finish IT Glue migration parity work in `tools/itglue-migrate/`, including relationship second-pass sync, attachment fidelity, folder/path correctness, and resumable execution.
- Add migration reconciliation reports for entity counts, skipped records, broken references, and attachment/image mismatches.
- Close remaining API and integration test gaps called out in `PLAN.md`, especially auth, org isolation, relationships, attachments, search, and TOTP coverage.
- Productize API documentation for migration-script authors and internal operators.
- Resolve remaining production-readiness work from `docs/INFRASTRUCTURE_ASSESSMENT.md`, especially CI/CD, backups, security headers, ingress/reverse proxy, monitoring, and broader E2E coverage.

### Exit Criteria

- Midtown can run a full migration rehearsal and produce deterministic reconciliation output.
- Midtown staff can perform daily documentation tasks without needing IT Glue for fallback workflows.
- Core smoke tests, migration validations, and deployment checks are automated.

---

### Phase 2 - IT Glue Replacement Completeness

### Objective

Remove the remaining reasons Midtown would keep IT Glue open after cutover.

### Priorities

- Strengthen operational UX around recent/frequent access, better relationship traversal, cleaner dashboards, and less click-heavy navigation.
- Improve history and trust features: richer audit trail surfaces, last-updated visibility, and easier change review on sensitive records.
- Tighten mobile/tablet behavior and cross-browser support for technician use in the field.
- Improve import/export and verification workflows so data can move safely both during migration and in ongoing operations.
- Fill documentation gaps for admin setup, migration runbooks, and recovery procedures.

### Exit Criteria

- Midtown can disable routine IT Glue access for normal operations.
- Support and admin workflows have documented runbooks.
- Daily-use friction is low enough that parity concerns become edge cases instead of blockers.

---

### Phase 3 - Hudu-Compatible Coverage

### Objective

Reach Hudu-compatible feature coverage for documentation-centric MSP workflows while staying opinionated about scope.

### Priorities

- Expand technician quality-of-life features such as favorites/pins, richer quick navigation, better homepage widgets, and cleaner cross-entity linking.
- Strengthen asset-template and flexible-asset workflows so common MSP documentation patterns feel as efficient as Hudu.
- Deepen diagrams/DCIM capabilities already planned in `docs/DCIM_DIAGRAMMING_PLAN.md` for racks, topology, cabling, and infrastructure views.
- Improve embedded credential, related-item, and linked-document workflows on asset detail screens.
- Add coexistence/migration helpers that reduce switching cost for teams familiar with Hudu patterns.

### Guardrails

- Do not chase parity for modules that are weakly related to documentation or better served by Bifrost Integrations.
- Prefer feature sets that improve technician speed, auditability, and documentation density.

### Exit Criteria

- A Hudu-familiar MSP can adopt Skra without major documentation workflow regressions.
- The parity story is strong enough for demos, pilots, and side-by-side comparisons.

---

### Phase 4 - Native Bifrost Integration Platform

### Objective

Make Skra the documentation destination for data gathered and normalized by `MTG-Thomas/bifrost`.

### Priorities

- Define a shared organization/tenant model between Docs and Bifrost.
- Define a stable sync contract: source system identity, external IDs, conflict rules, field ownership, sync direction, and event semantics.
- Reuse Bifrost for OAuth token lifecycle, connector execution, secrets storage, scheduling, retries, and monitoring.
- Add Docs-side sync status, provenance, and reconciliation UX so users can see where a record came from and when it last synced.
- Start with the highest-value MSP sources already implied by repo plans and likely Bifrost usage: NinjaOne, Meraki, Halo/PSA-adjacent systems, Microsoft ecosystem data, and distributor/vendor data where useful.

### Example Split of Responsibilities

- **Bifrost Integrations**: connector code, auth flows, secret management, polling/webhooks, normalized integration outputs.
- **Skra**: schema mapping, entity matching, relationship creation, user review, surfacing sync state, and documentation-aware enrichment.

### Exit Criteria

- At least one end-to-end integration path lands in Docs through Bifrost without duplicate connector logic.
- Sync health, provenance, and conflict handling are visible in-product.

---

### Phase 5 - AI and Automation Differentiation

### Objective

Use AI and automation to make documentation easier to maintain than in IT Glue or Hudu.

### Priorities

- Extend AI document mutation workflows into guided runbook drafting, stale-document detection, clean-up suggestions, and structured diff previews.
- Combine live integration context from Bifrost with stored documentation for better answers, summaries, and change proposals.
- Auto-generate and refresh diagrams from synced infrastructure state.
- Draft documentation from discovered devices, asset metadata, and change events, with approval gates for writeback.
- Add operational copilots for migration reconciliation, sync drift review, and environment summarization.

### Exit Criteria

- AI materially reduces documentation maintenance time while preserving human review on important changes.
- Docs becomes easier to keep current than incumbent platforms.

---

## Cross-Cutting Workstreams

These should run alongside the phases rather than waiting for a single milestone.

### Reliability and Security

- CI/CD, backups, ingress, monitoring, structured logging, request limits, and security hardening.

### Testing and Verification

- Full backend integration coverage for core entities.
- E2E coverage for high-value technician workflows.
- Migration validation suites and seeded demo environments.

### Documentation and Enablement

- Admin runbooks, migration runbooks, connector setup guides, and contributor-facing API docs.

### Data Governance

- Audit completeness, provenance labeling, sync ownership rules, retention policies, and safe recovery procedures.

---

## Suggested GitHub Epic Structure

1. **Midtown cutover and migration confidence**
2. **Production hardening and operational readiness**
3. **IT Glue replacement UX and workflow closure**
4. **Hudu-compatible documentation workflows**
5. **Bifrost native sync architecture**
6. **First-party integration connectors through Bifrost**
7. **AI-assisted documentation maintenance**
8. **Diagramming and DCIM expansion**

---

## What Not to Do Yet

- Rebuild integration runtime features already better owned by `MTG-Thomas/bifrost`.
- Pursue broad connector expansion before Midtown migration and production readiness are stable.
- Chase Hudu parity in areas that do not improve documentation quality, technician speed, or migration viability.

---

## Immediate Next Steps

1. Turn this roadmap into GitHub epics and milestone labels in `MTG-Thomas/skra`.
2. Create a parallel architecture epic in `MTG-Thomas/bifrost` for the Docs integration contract.
3. Sequence the first implementation tranche around Midtown migration hardening, test closure, and production readiness.
4. Use the resulting epics as the planning source of truth instead of continuing to rely only on historical implementation plans.
