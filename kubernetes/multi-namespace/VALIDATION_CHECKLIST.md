# Multi-Namespace Deployment Validation Checklist

## Pre-Deployment

- [ ] Kubernetes cluster version 1.25+ (or compatible with manifests)
- [ ] kubectl configured and authenticated to target cluster
- [ ] cert-manager installed in cluster (for TLS)
- [ ] Ingress controller installed (nginx or traefik)
- [ ] External Secrets Operator or secret management solution ready
- [ ] DNS configured for domains (dev.docs.midtowntg.com, bifrost.example.com)

## Namespace Creation

- [ ] Run: `kubectl apply -f namespaces/`
- [ ] Verify: `kubectl get namespaces --show-labels`
- [ ] Confirm all three namespaces exist with correct labels:
  - bifrost
  - skra
  - bifrost-platform

## Platform Infrastructure

- [ ] cert-manager ClusterIssuer configured (letsencrypt-staging or prod)
- [ ] Ingress controller running in bifrost-platform namespace
- [ ] External Secrets Operator configured with ClusterSecretStore

## Network Policies

- [ ] Run: `kubectl apply -k platform/network-policies/`
- [ ] Verify default deny policies exist:
  ```bash
  kubectl get networkpolicy -n bifrost
  kubectl get networkpolicy -n skra
  ```
- [ ] Test cross-namespace connectivity (should fail without explicit allow)

## Skra Deployment

- [ ] Secrets created in skra namespace:
  - skra-secrets (database credentials, encryption keys)
- [ ] ConfigMap created: skra-config
- [ ] Deployments running: api, client, worker
- [ ] Services created and endpoints populated
- [ ] Ingress configured with TLS
- [ ] ResourceQuota not exceeded

## Bifrost Deployment

- [ ] Deploy Bifrost from MTG-Thomas/bifrost repo into bifrost namespace
- [ ] Verify Bifrost pods are running
- [ ] Verify Bifrost API service has endpoints

## Cross-Namespace Integration

- [ ] ExternalName service exists in skra pointing to bifrost-api
- [ ] NetworkPolicy allows-docs-to-bifrost-api is applied in bifrost namespace
- [ ] Test connectivity:
  ```bash
  kubectl run debug -n skra --rm -it --image=curlimages/curl -- \
    curl http://external-bifrost-api.skra.svc.cluster.local:8000/health
  ```

## Smoke Tests

### Skra

- [ ] https://dev.docs.midtowntg.com loads without certificate errors
- [ ] API health endpoint responds: https://dev.docs.midtowntg.com/api/health
- [ ] Can authenticate and view organization list
- [ ] Can navigate to passwords/configurations/documents

### Bifrost (if deployed)

- [ ] https://bifrost.example.com loads
- [ ] API health endpoint responds

### Integration

- [ ] Skra can query Bifrost API (check integration features)
- [ ] No 403/connection errors in logs from cross-namespace calls

## Monitoring & Observability

- [ ] Prometheus scraping both namespaces
- [ ] Grafana dashboards accessible
- [ ] Application logs flowing to centralized logging
- [ ] Alert rules configured for critical failures

## Backup Verification

- [ ] CronJob for skra backup exists
- [ ] Backup can be run manually and produces valid output
- [ ] Restore procedure tested in non-production environment

## Security

- [ ] No pods running as root (check security contexts)
- [ ] Network policies active and blocking unintended traffic
- [ ] Secrets mounted as files or environment variables (not in configmaps)
- [ ] TLS certificates valid and auto-renewing
- [ ] CORS origins properly restricted in production

## Performance

- [ ] API response times < 500ms for common operations
- [ ] Database connections stable (no connection pool exhaustion)
- [ ] Redis/Valkey memory usage healthy
- [ ] Worker queue depth not growing unbounded

## Rollback Plan

- [ ] Previous deployment manifests saved
- [ ] Database backup taken before deployment
- [ ] Rollback procedure documented and tested
- [ ] Rollback can be executed within 15 minutes if needed

## Sign-Off

- [ ] Deployment validated by: _____________
- [ ] Date: _____________
- [ ] Environment: _____________ (development/staging/production)
- [ ] Known issues documented: _____________
