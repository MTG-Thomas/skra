# Backup and Restore Guide

This guide covers automated backup procedures and disaster recovery for Skra.

## Overview

Skra uses a multi-layered backup strategy:

1. **Database Backups** - PostgreSQL dumps (automated daily/weekly)
2. **Attachment Backups** - S3 object replication for attachments
3. **Configuration Backups** - Environment configs and secrets

## Quick Reference

| Backup Type | Frequency | Retention | Storage |
|-------------|-----------|-----------|---------|
| Database - Daily | Daily at 2:00 AM | 7 days | S3 (skra/backups/daily/) |
| Database - Weekly | Sundays at 3:00 AM | 4 weeks | S3 (skra/backups/weekly/) |
| Attachments | On-demand / Sync | All versions | S3 (skra-backup/attachments/) |
| Manual Full | As needed | Custom | S3 + Local |

## Docker Compose Deployment

### Automated Backups

The production Docker Compose includes a backup service:

```yaml
# docker-compose.prod.yml
backup:
  image: ghcr.io/mtg-thomas/skra-api:latest
  command: |
    sh -c "
      echo '0 2 * * * /app/scripts/backup.sh --daily' | crontab - &&
      echo '0 3 * * 0 /app/scripts/backup.sh --weekly' | crontab - &&
      crond -f
    "
```

### Manual Backup

```bash
# Full backup
docker compose -f docker-compose.prod.yml exec backup /app/scripts/backup.sh

# Daily backup with rotation
docker compose -f docker-compose.prod.yml exec backup /app/scripts/backup.sh --daily

# Weekly backup with rotation
docker compose -f docker-compose.prod.yml exec backup /app/scripts/backup.sh --weekly
```

### Verify a Backup

```bash
# Verify latest daily backup
./scripts/verify-backup.sh --latest --daily

# Verify specific backup with full restore test
./scripts/verify-backup.sh s3://skra/backups/daily/2026-04-06/skra_daily_20260406_120000.sql.gz --full
```

### Restore from Backup

⚠️ **WARNING: This will overwrite your current database!**

```bash
# 1. Stop the application
docker compose -f docker-compose.prod.yml stop api client worker

# 2. Restore from backup
docker compose -f docker-compose.prod.yml exec backup /app/scripts/backup.sh \
    --restore s3://skra/backups/daily/2026-04-06/skra_daily_20260406_120000.sql.gz

# 3. Restart the application
docker compose -f docker-compose.prod.yml up -d api client worker

# 4. Verify restoration
curl http://localhost/api/health
```

### Backup Attachments

```bash
# Full attachments backup
./scripts/backup-attachments.sh

# Sync only changes
./scripts/backup-attachments.sh --sync

# Verify attachment backup
./scripts/backup-attachments.sh --verify
```

## Kubernetes Deployment

### Automated Backups (CronJobs)

```bash
# Apply backup CronJobs
kubectl apply -f kubernetes/cronjobs/backup-cronjob.yaml

# View scheduled backups
kubectl get cronjobs -n skra

# View backup job history
kubectl get jobs -n skra | grep backup

# Check latest backup job logs
kubectl logs -n skra -l job-name=skra-backup-daily-xxx
```

### Manual Backup (One-off Job)

```bash
# Create manual backup job
kubectl create job -n skra manual-backup-$(date +%s) \
    --from=cronjob/skra-backup-daily

# Check job status
kubectl wait -n skra --for=condition=complete job/manual-backup-xxx

# Get backup location from logs
kubectl logs -n skra job/manual-backup-xxx
```

### Restore in Kubernetes

⚠️ **WARNING: This will overwrite your current database!**

```bash
# 1. Get the backup file from S3
kubectl run -n skra pg-restore --rm -it --image=postgres:15-alpine -- \
    sh -c '
    aws s3 cp s3://skra/backups/daily/2026-04-06/skra_daily_20260406_120000.sql.gz /tmp/backup.sql.gz
    gunzip -c /tmp/backup.sql.gz | pg_restore \
        -h postgres.skra.svc.cluster.local \
        -U skra \
        -d skra \
        --clean \
        --if-exists
    '

# 2. Verify restoration
kubectl exec -n skra deployment/skra-api -- \
    curl -s http://localhost:8000/health
```

## Backup Verification

### Why Verify?

Backups are only useful if they can be restored. Regular verification catches:
- Corrupt backup files
- Incompatible PostgreSQL versions
- Missing data or schema issues

### Automated Verification

The daily backup job includes basic verification (gzip integrity check). For full verification:

```bash
# Automated full verification (restores to temp database)
./scripts/verify-backup.sh --latest --daily --full
```

#### Scheduled verification (CI)

The `Backup Verification` workflow (`.github/workflows/backup-verification.yml`)
runs weekly (Sundays 04:00 UTC, plus manual `workflow_dispatch` runs). It
provisions an ephemeral Postgres service container, seeds probe data, takes a
real backup with `scripts/backup.sh` (`SKIP_S3_UPLOAD=true`, so no S3 bucket
or credentials are needed), and test-restores it with
`scripts/verify-backup.sh --full`. A restore failure fails the workflow
loudly (red check plus GitHub's scheduled-workflow failure notification), and
the offending backup file is kept as a 7-day artifact for diagnosis.

Scope note: the scheduled run exercises the backup/restore *tooling* against
a throwaway database. Verifying an actual production S3 backup still requires
human-provisioned S3 access — run `./scripts/verify-backup.sh --latest
--daily --full` with `SKRA_S3_ENDPOINT` / AWS credentials pointed at the
production bucket (see Manual Verification Steps below).

### Manual Verification Steps

1. **Check backup exists:**
   ```bash
   aws s3 ls s3://skra/backups/daily/2026-04-06/ \
       --endpoint-url http://localhost:3900
   ```

2. **Verify gzip integrity:**
   ```bash
   aws s3 cp s3://skra/backups/daily/... /tmp/backup.sql.gz
   gzip -t /tmp/backup.sql.gz && echo "Valid"
   ```

3. **Check backup contents:**
   ```bash
   gunzip -c /tmp/backup.sql.gz | pg_restore --list | head -20
   ```

## Disaster Recovery Scenarios

### Scenario 1: Database Corruption

**Symptoms:** Data inconsistency, query errors, application crashes

**Recovery:**
```bash
# 1. Identify last good backup
aws s3 ls s3://skra/backups/daily/ --recursive | sort -r | head -5

# 2. Stop application
docker compose stop api client worker

# 3. Restore from backup
./scripts/backup.sh --restore s3://skra/backups/daily/.../backup.sql.gz

# 4. Start application
docker compose up -d

# 5. Verify
curl http://localhost/api/health
```

### Scenario 2: Complete Data Loss

**Symptoms:** Database completely lost, hardware failure

**Recovery:**
```bash
# 1. Set up new environment
# (Follow deployment guide for fresh install)

# 2. Restore database from latest weekly backup
./scripts/backup.sh --restore s3://skra/backups/weekly/.../backup.sql.gz

# 3. Restore attachments if needed
./scripts/backup-attachments.sh --sync

# 4. Verify all data present
# Check entity counts match expected
```

### Scenario 3: Accidental Data Deletion

**Symptoms:** User deleted organization/document by mistake

**Recovery:**
```bash
# Point-in-time recovery options:
# 1. If caught quickly, restore from daily backup to temp database
# 2. Extract specific entity from backup
# 3. Insert back into production database

# Restore to temporary database
./scripts/backup.sh --restore s3://.../backup.sql.gz
# (Modify restore script to use temp database name)

# Export specific data and re-import
```

### Scenario 4: Migration Rollback

See `tools/itglue-migrate/docs/cutover-runbook.md` for detailed rollback procedures.

## Backup Storage Best Practices

### S3 Configuration

```bash
# Enable versioning on backup bucket
aws s3api put-bucket-versioning \
    --bucket skra-backup \
    --versioning-configuration Status=Enabled

# Enable lifecycle policy (transition to cheaper storage)
aws s3api put-bucket-lifecycle-configuration \
    --bucket skra-backup \
    --lifecycle-configuration file://lifecycle-policy.json
```

### Cross-Region Replication

For disaster recovery, replicate backups to a second region:

```bash
# Set up cross-region replication
aws s3api put-bucket-replication \
    --bucket skra \
    --replication-configuration file://replication-config.json
```

### Encryption

All backups should be encrypted:

```bash
# Server-side encryption (S3)
aws s3 cp backup.sql.gz s3://bucket/ --sse AES256

# Client-side encryption (gpg)
gpg --cipher-algo AES256 --compress-algo 1 --symmetric --output backup.sql.gz.gpg backup.sql.gz
```

## Monitoring and Alerts

### Check Backup Status

```bash
# Check if daily backup completed today
aws s3 ls s3://skra/backups/daily/$(date +%Y-%m-%d)/ --endpoint-url ...

# Check backup size (alert if < expected)
aws s3api head-object \
    --bucket skra \
    --key backups/daily/.../backup.sql.gz
```

### Prometheus Metrics

If monitoring is enabled:

```
# Track backup job success
backup_job_last_success_timestamp

# Track backup size
backup_size_bytes

# Track time since last backup
time() - backup_job_last_success_timestamp
```

## Testing Your Recovery Plan

**Quarterly DR Drill:**

1. Schedule maintenance window
2. Document current state (entity counts)
3. Restore from backup to isolated environment
4. Verify all data present
5. Test application functionality
6. Document any issues
7. Improve procedures based on findings

## Emergency Contacts

| Role | Contact | Responsibility |
|------|---------|--------------|
| Database Admin | _____________ | Restore procedures |
| S3/Storage Admin | _____________ | Bucket access, replication |
| On-call Engineer | _____________ | Initial response |
| Migration Lead | _____________ | Migration rollback decisions |

## Related Documentation

- `docs/deployment/TLS-DEPLOYMENT.md` - TLS configuration
- `docs/INFRASTRUCTURE_ASSESSMENT.md` - Production readiness
- `tools/itglue-migrate/docs/cutover-runbook.md` - Migration rollback
