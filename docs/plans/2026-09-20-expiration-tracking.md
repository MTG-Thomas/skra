# Expiration Tracking (issue #40, parent #18 Hudu parity)

## Problem

MSPs track warranties, SSL certificates, contracts, and licenses as custom
assets with date fields. Nothing surfaces when those dates approach, so
renewals lapse. Hudu shows expiration badges and reminders; Bifrost has no
equivalent.

## Design decisions

- **Reuse the M1 `expiration_alert` flag** on date-type `FieldDefinition`
  entries instead of adding a separate `expiration_date` field type. One
  date+flag design covers warranties, SSL certs, and contracts without a
  new field widget, and stays consistent with existing custom assets.
- **Alert windows 30/14/7/1 days** (`ALERT_WINDOWS` in
  `api/src/services/expiration.py`), plus expired items (`window_days 0`).
  The 30-day horizon is the default query; escalation to a nearer window
  re-alerts, repeats do not.
- **Daily check via the existing arq scheduler** (`check_expirations_task`,
  cron 6am in `api/src/worker.py`), same pattern as the audit-log cleanup
  job. No new queue infrastructure.
- **Dedupe in Postgres** (`expiration_alert_sightings`, unique on
  org/asset/field/window) with `ON CONFLICT DO NOTHING`, so worker
  restarts and retries never double-alert.
- **Email is opt-in and off by default.** No existing SMTP/notification
  plumbing was found in the API (only Redis pubsub for websockets), so per
  the acceptance criteria the notifier stays disabled unless `smtp_*`
  settings are configured. No silent new dependency.
- **Read-only surfacing, no view audit.** The upcoming endpoint logs no
  audit entries (dashboard polling would drown access history).
- **Frontend follows existing patterns**: React Query hook, shadcn
  `Card`/`Badge`, widget on the org home page (the org-scoped dashboard),
  badge on the custom-asset detail page. Frontend OpenAPI types
  (`v1.d.ts`) are generated from a live server, so the new endpoint types
  are hand-written in `useExpirations.ts` until the next
  `generate:types` run.

## Coordination with #117

#117 owns the custom-asset type editor (contracts/UI). This issue does not
touch the type editor: the badge/widget read the org-level upcoming
endpoint and match on `asset_id`. Shared files are limited to additive
reads of custom-asset contracts. Rebase after #117 merges.

## Files

- API: `services/expiration.py`, `services/expiration_alerts.py`,
  `repositories/expiration_alert.py`, `models/orm/expiration_alert.py`,
  `models/contracts/expiration.py`, `routers/organizations.py`
  (`GET /{org_id}/expirations/upcoming`), `worker.py`, migration
  `20260920_100000`.
- Client: `hooks/useExpirations.ts`,
  `components/UpcomingExpirationsWidget.tsx`, badge in
  `CustomAssetDetailPage.tsx`, widget in `OrgHomePage.tsx`,
  `e2e/tests/expiration-alerts.spec.ts` (requires seeded stack; proof
  deferred to VM101 after the #117 lease).
