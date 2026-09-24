# Midtown Migration Cutover Runbook

> **For:** Midtown migration from IT Glue to Skra  
> **When:** Production cutover day  
> **Owner:** Migration operator (you!)  

This runbook provides step-by-step procedures for executing the Midtown migration cutover from IT Glue to Skra. Follow this guide to ensure a safe, reversible migration with minimal downtime.

---

## 📋 Quick Reference

| Item | Value |
|------|-------|
| **Source** | IT Glue export (178 orgs, ~25K entities) |
| **Target** | Skra production instance |
| **Estimated Cutover Time** | 4-8 hours |
| **Rollback Window** | 24 hours (keep IT Glue access) |
| **Support Channel** | #migration-support (Slack) |
| **Escalation** | @migration-lead |

---

## Phase 0: Pre-Cutover (T-7 Days to T-1 Day)

### 0.1 Environment Preparation Checklist

- [ ] Skra production deployment verified healthy
- [ ] `curl $SKRA_API_URL/api/health` returns 200
- [ ] Database backups scheduled and tested
- [ ] Migration operator has admin access to both IT Glue and Skra
- [ ] API token generated with `owner` role in Skra
- [ ] IT Glue export downloaded and validated (less than 7 days old)
- [ ] Export size verified: ~2.1GB, ~2,100 attachments expected
- [ ] `itglue-migrate` CLI installed: `pip install -e tools/itglue-migrate`

### 0.2 Rehearsal Completion

- [ ] **Mandatory:** Full rehearsal completed using seeded fixture
  ```bash
  cd tools/itglue-migrate
  pytest tests/integration/test_migration_smoke.py -v
  ```
- [ ] **Mandatory:** Single org pilot migration completed successfully
  ```bash
  python -m itglue_migrate.cli run \
      --export /path/to/export \
      --org "Acme Corp" \
      --api-url $SKRA_API_URL \
      --token $SKRA_TOKEN \
      --dry-run
  ```
- [ ] Pilot org verified in Skra UI
- [ ] Entity counts match: Orgs=1, Configs=N, Passwords=N, etc.
- [ ] No critical errors in logs

### 0.3 Communication Plan

- [ ] Cutover date announced to Midtown staff (T-3 days minimum)
- [ ] IT Glue "read-only" notice scheduled for cutover day
- [ ] Skra training session completed for key users
- [ ] Support contact list distributed

---

## Phase 1: Pre-Flight (Cutover Day, T-2 Hours)

### 1.1 Final Health Checks

```bash
# Test Skra API connectivity
curl -H "Authorization: Bearer $SKRA_TOKEN" \
    $SKRA_API_URL/api/health

# Expected: {"status": "healthy", "database": "connected"}
```

- [ ] API responding < 500ms
- [ ] Database connection healthy
- [ ] S3/MinIO storage accessible
- [ ] Redis/Valkey responsive

### 1.2 Backup Verification

- [ ] Skra database backup completed
  ```bash
  # Verify backup exists
  ls -la /backups/skra-$(date +%Y%m%d)*
  ```
- [ ] Backup restoration tested in staging environment
- [ ] Rollback plan documented (see Phase 5)

### 1.3 Export Validation

```bash
cd tools/itglue-migrate

# Validate export structure
python -m itglue_migrate.cli validate \
    --export /path/to/itglue-export
```

- [ ] Export structure validation passes
- [ ] All expected CSV files present
- [ ] Attachments directory accessible
- [ ] File permissions correct (readable)

### 1.4 Resource Check

- [ ] Disk space: > 50GB free on target system
- [ ] Network: Stable connection to Skra
- [ ] Time: 4-8 hour window available
- [ ] Coffee: ☕ Fully stocked

---

## Phase 2: Migration Execution (Cutover Day, T-0)

### 2.1 Generate Migration Plan

```bash
cd tools/itglue-migrate

# Generate the migration plan
python -m itglue_migrate.cli preview \
    --export /path/to/itglue-export \
    --api-url $SKRA_API_URL \
    --token $SKRA_TOKEN \
    --output /tmp/midtown-migration-plan.json
```

- [ ] Plan file generated successfully
- [ ] Review summary output:
  - Organizations: 178
  - Configurations: ~6,191
  - Documents: ~1,328
  - Locations: ~589
  - Passwords: ~10,218
  - Custom Assets: ~7,500
  - Attachments: ~2,100

### 2.2 Review Plan File

```bash
# Quick sanity check
jq '.summary' /tmp/midtown-migration-plan.json
```

**Decision Point:** ⚠️

- [ ] **YES** - Counts match expected? → Continue to 2.3
- [ ] **NO** - Counts off by > 10%? → Stop and investigate

### 2.3 Execute Migration (First Pass)

```bash
# First pass: Core entities (no attachments)
python -m itglue_migrate.cli run \
    --export /path/to/itglue-export \
    --plan /tmp/midtown-migration-plan.json \
    --api-url $SKRA_API_URL \
    --token $SKRA_TOKEN \
    --skip-attachments \
    --output /tmp/migration-results-core.json
```

**Monitor progress:**
- Watch for ERROR messages in output
- Note any "skipped" or "failed" counts
- Expected: ~30-60 minutes for core entities

- [ ] Core entity migration completed
- [ ] Error count < 1% of total entities
- [ ] No critical (blocking) errors

### 2.4 Execute Attachment Migration

```bash
# Second pass: Attachments only
python -m itglue_migrate.cli run \
    --export /path/to/itglue-export \
    --plan /tmp/midtown-migration-plan.json \
    --api-url $SKRA_API_URL \
    --token $SKRA_TOKEN \
    --only-attachments \
    --output /tmp/migration-results-attachments.json
```

- [ ] Attachment migration completed
- [ ] ~2,100 attachments processed
- [ ] Failed attachments logged for review

### 2.5 Execute Relationship Sync (Second Pass)

Relationships sync last, after all entities exist. The sync is stateless:
it re-reads what already migrated from the API on every run, so re-running
is safe — already-created links are detected and skipped, never recreated.

```bash
# Dry run first: review the relationship plan without creating links
python -m itglue_migrate.cli sync \
    --export-path /path/to/itglue-export \
    --api-url $SKRA_API_URL \
    --token $SKRA_TOKEN \
    --org "Company Name" \
    --dry-run

# Live run with a reconciliation report for the audit trail
python -m itglue_migrate.cli sync \
    --export-path /path/to/itglue-export \
    --api-url $SKRA_API_URL \
    --token $SKRA_TOKEN \
    --org "Company Name" \
    --reconciliation-output /tmp/relationship-sync-results.json
```

**Reading the "Relationship detail" breakdown:**

| Bucket | Meaning | Resume action |
|--------|---------|---------------|
| `created` | Links created this run | None |
| `duplicate` | Link already existed (pre-run or earlier in this run) | None — safe to ignore |
| `missing_source` / `missing_target` | Referenced entity has no migrated UUID | Sync the named entity first (the audit `reason` gives the IT Glue ID), then re-run |
| `transient_error` | Retryable API failure (timeout, 429, 5xx) | Simply re-run |
| `failed` | Hard failure (e.g. 400) | Inspect `errors`, fix, re-run |

Each skipped link carries an actionable `reason` in the reconciliation JSON
(`organizations[].relationship_audit[].reason`). The command exits nonzero
when `failed` is nonzero; `duplicate` and resolved-missing links never fail
the run on a later pass once their cause is fixed.

- [ ] Relationship sync completed (exit 0, or only expected missing refs)
- [ ] `missing_*` reasons reviewed; source entities queued if needed
- [ ] Reconciliation JSON archived for the cutover record

---

## Phase 3: Validation (T+2 Hours)

### 3.1 Automated Verification

```bash
# Run validation script (read-only: GETs the migrated records and compares
# them against the export; exits nonzero when failures are found)
cd tools/itglue-migrate
python -m itglue_migrate.cli verify \
    --export-path /path/to/itglue-export \
    --api-url $SKRA_API_URL \
    --token $SKRA_API_TOKEN \
    --all \
    --output /tmp/migration-validation-report.json
```

`--api-url`/`--token` can be omitted when `SKRA_API_URL`/`SKRA_API_TOKEN`
are exported. Use `--org <name>` instead of `--all` to validate a single
organization, and add `--check-urls` to also probe migrated download/image
URLs for reachability.

### 3.2 Entity Count Verification

| Entity Type | IT Glue Source | Skra Target | Match |
|-------------|----------------|----------------|-------|
| Organizations | 178 | ___ | [ ] |
| Configurations | ~6,191 | ___ | [ ] |
| Documents | ~1,328 | ___ | [ ] |
| Locations | ~589 | ___ | [ ] |
| Passwords | ~10,218 | ___ | [ ] |
| Custom Assets | ~7,500 | ___ | [ ] |
| Attachments | ~2,100 | ___ | [ ] |

**Decision Point:** ⚠️

- [ ] **YES** - All counts within 5%? → Continue to 3.3
- [ ] **NO** - Significant discrepancies? → Review logs before proceeding

### 3.3 Spot Check Critical Data

**Sample 5 random organizations and verify:**
- [ ] Organization name matches
- [ ] At least one password visible
- [ ] At least one configuration exists
- [ ] Documents render correctly (no broken images)

**Sample 10 random passwords and verify:**
- [ ] Password decrypts successfully (reveal works)
- [ ] Username field populated
- [ ] URL field populated (if applicable)

**Sample 5 random documents and verify:**
- [ ] Document opens without errors
- [ ] Images load correctly
- [ ] Formatting preserved

### 3.4 Integration Features Check

- [ ] Search returns results for common queries
- [ ] Global view shows all organizations
- [ ] Recent/Frequent access tracking works
- [ ] Audit logs recording access

---

## Phase 4: Cutover Signoff (T+4 Hours)

### 4.1 Go/No-Go Decision

**Check all gates:**

| Gate | Status |
|------|--------|
| Entity counts match (±5%) | [ ] PASS / [ ] FAIL |
| No critical errors in logs | [ ] PASS / [ ] FAIL |
| Spot checks successful (90%+) | [ ] PASS / [ ] FAIL |
| Search/indexing functional | [ ] PASS / [ ] FAIL |
| Staff can log in and access data | [ ] PASS / [ ] FAIL |

**Decision:**

- [ ] **GO** - All gates pass → Continue to 4.2
- [ ] **NO-GO** - Any gate fails → Execute rollback (Phase 5)

### 4.2 Enable Skra for Staff

- [ ] Remove "maintenance mode" if enabled
- [ ] Announce cutover complete to staff
- [ ] Provide Skra login URL
- [ ] Share quick-start guide
- [ ] Open support channel for questions

### 4.3 IT Glue Read-Only Transition

- [ ] Set IT Glue to read-only for Midtown data
- [ ] Post notice directing staff to Skra
- [ ] Retain IT Glue access for 24 hours (rollback window)

### 4.4 Post-Cutover Monitoring

**First 24 hours:**
- [ ] Monitor error rates every 2 hours
- [ ] Check API response times
- [ ] Watch for authentication issues
- [ ] Monitor storage usage growth

**First week:**
- [ ] Daily standup to review issues
- [ ] Track user feedback
- [ ] Document workarounds for any gaps

---

## Phase 5: Rollback (If Needed)

**⚠️ Execute this section only if Go/No-Go decision is NO-GO**

### 5.1 Rollback Triggers

**Immediate rollback required if:**
- [ ] > 10% of entities failed to migrate
- [ ] Password decryption failing systemically
- [ ] Search/indexing completely broken
- [ ] Users cannot authenticate
- [ ] Data corruption detected

**Consider rollback if:**
- [ ] 5-10% entity count discrepancy
- [ ] Key workflows not functional
- [ ] Staff unable to perform daily tasks

### 5.2 Rollback Procedure

**Step 1: Stop Migration (if still running)**
```bash
# Kill any running migration processes
pkill -f "itglue-migrate"
```

**Step 2: Restore Database (if needed)**
```bash
# Restore from pre-migration backup
# (Work with your DBA or use documented restore procedure)
pg_restore --clean --if-exists \
    --dbname=skra \
    /backups/skra-pre-migration.dump
```

**Step 3: Re-enable IT Glue Write Access**
- [ ] Remove read-only restrictions in IT Glue
- [ ] Notify staff to continue using IT Glue
- [ ] Pause Skra rollout

**Step 4: Post-Rollback Analysis**
- [ ] Document what failed
- [ ] Preserve migration logs for analysis
- [ ] Schedule post-mortem within 48 hours
- [ ] Plan remediation and re-cutover

### 5.3 Partial Rollback Option

If only some organizations failed:
- [ ] Wipe affected organizations from Skra
- [ ] Re-run migration for those orgs only
- [ ] Validate before declaring success

---

## Phase 6: Post-Cutover (T+1 Day to T+7 Days)

### 6.1 Final IT Glue Cleanup

**After 7 days of stable operation:**
- [ ] Confirm no staff requesting IT Glue access
- [ ] Export final IT Glue backup (for records)
- [ ] Cancel IT Glue subscription (if applicable)
- [ ] Update documentation to remove IT Glue references

### 6.2 Documentation Updates

- [ ] Update internal wiki with Skra procedures
- [ ] Archive IT Glue procedures (mark deprecated)
- [ ] Document any workarounds discovered

### 6.3 Success Metrics

Track these for 30 days post-cutover:
- [ ] Daily active users in Skra
- [ ] Search query success rate
- [ ] Average page load time
- [ ] Support ticket volume (should decrease over time)

---

## 📞 Emergency Contacts

| Role | Contact | Phone/Slack |
|------|---------|-------------|
| Migration Lead | _____________ | @migration-lead |
| Skra Admin | _____________ | @skra-admin |
| Database Admin | _____________ | @dba-oncall |
| IT Glue Admin | _____________ | @itglue-admin |
| Midtown IT Lead | _____________ | @midtown-it |

---

## 🔗 Related Documentation

- `migration-features.md` - Migration tool features
- `rehearsal-guide.md` - Using the test fixture
- `MIGRATION_TOOL.md` - Full migration architecture
- `docs/ROADMAP.md` - Project roadmap
- `docs/INFRASTRUCTURE_ASSESSMENT.md` - Production readiness

---

## 📝 Change Log

| Date | Version | Changes |
|------|---------|---------|
| 2026-04-06 | 1.0 | Initial runbook for Midtown cutover |

---

**END OF RUNBOOK**

**Remember:** When in doubt, roll back. Data integrity is more important than meeting a deadline.
