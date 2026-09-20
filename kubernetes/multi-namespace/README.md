# Multi-Namespace Deployment Architecture

This directory contains Kubernetes manifests for running **Bifrost** (integration platform) and **Skra** (documentation platform) in separate namespaces within the same cluster.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                         Kubernetes Cluster                   │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Namespace: bifrost-platform                        │   │
│  │  (Shared infrastructure)                              │   │
│  │                                                      │   │
│  │  • Ingress Controller (nginx/traefik)                │   │
│  │  • cert-manager                                      │   │
│  │  • External Secrets Operator                         │   │
│  │  • Prometheus/Grafana (optional)                    │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─────────────────────────┐  ┌─────────────────────────┐  │
│  │ Namespace: bifrost      │  │ Namespace: skra │  │
│  │                          │  │                          │  │
│  │ • API Deployment         │  │ • API Deployment         │  │
│  │ • Worker Deployment      │  │ • Worker Deployment      │  │
│  │ • Client Deployment      │  │ • Client Deployment      │  │
│  │ • PostgreSQL             │  │ • PostgreSQL             │  │
│  │ • Redis                  │  │ • Redis                  │  │
│  │ • RabbitMQ               │  │ • RabbitMQ               │  │
│  │ • ConfigMaps/Secrets     │  │ • ConfigMaps/Secrets     │  │
│  └─────────────────────────┘  └─────────────────────────┘  │
│                                                              │
│  Network Policies restrict cross-namespace traffic           │
└─────────────────────────────────────────────────────────────┘
```

## Design Principles

1. **Namespace Isolation**: Each application runs in its own namespace with independent lifecycle
2. **Shared Platform**: Infrastructure components (ingress, certs, observability) run in a shared namespace
3. **Separate Data Planes**: Each app has its own databases, caches, and queues
4. **API-Level Integration**: Cross-app communication happens via stable HTTP APIs, not internal service mesh tricks
5. **Upstream Compatible**: No coupling that would prevent independent updates or upstream reconciliation

## Directory Structure

```
kubernetes/
├── multi-namespace/
│   ├── README.md                          # This file
│   ├── namespaces/                        # Namespace definitions
│   │   ├── bifrost-platform.yaml
│   │   ├── bifrost.yaml
│   │   └── skra.yaml
│   ├── platform/                          # Shared infrastructure
│   │   ├── ingress-controller/
│   │   ├── cert-manager/
│   │   └── network-policies/
│   ├── bifrost/                           # Bifrost app (reference only)
│   │   ├── kustomization.yaml
│   │   ├── namespace.yaml
│   │   ├── api/
│   │   ├── worker/
│   │   ├── client/
│   │   ├── postgres/
│   │   ├── redis/
│   │   └── rabbitmq/
│   ├── skra/                      # Skra app
│   │   ├── kustomization.yaml
│   │   ├── namespace.yaml
│   │   ├── api/
│   │   ├── worker/
│   │   ├── client/
│   │   ├── postgres/
│   │   ├── redis/
│   │   └── rabbitmq/
│   └── overlays/                          # Environment overlays
│       ├── development/
│       ├── staging/
│       └── production/
```

## Quick Start

### 1. Create Namespaces

```bash
kubectl apply -f multi-namespace/namespaces/
```

### 2. Deploy Platform Infrastructure

```bash
# Deploy shared ingress controller and cert-manager
kubectl apply -f multi-namespace/platform/
```

### 3. Deploy Applications (Independent Order)

```bash
# Deploy Skra
kubectl apply -k multi-namespace/skra/

# Deploy Bifrost (separate, can be done in any order)
kubectl apply -k multi-namespace/bifrost/
```

## Cross-Namespace Communication

### DNS Resolution

Services in different namespaces are accessible via:
```
<service>.<namespace>.svc.cluster.local
```

Example:
- Bifrost API from Docs: `bifrost-api.bifrost.svc.cluster.local:8000`
- Skra API from Bifrost: `skra-api.skra.svc.cluster.local:8000`

### Network Policies

By default, pods can communicate across namespaces. Network policies are included to:

1. **Deny all cross-namespace traffic by default**
2. **Allow specific egress from Skra to Bifrost API** (for integration features)
3. **Allow ingress controller to reach both apps**
4. **Block everything else**

See `multi-namespace/platform/network-policies/` for definitions.

## Data Isolation

### Recommended: Separate Instances

Each namespace should have its own:
- PostgreSQL database (or separate logical databases)
- Redis instance (or separate logical DBs)
- RabbitMQ VHost or separate instance
- S3 bucket prefix or separate buckets

### Resource Quotas

Each namespace has resource quotas to prevent one app from starving the other:

```yaml
# skra namespace
spec:
  hard:
    requests.cpu: "4"
    requests.memory: 8Gi
    limits.cpu: "8"
    limits.memory: 16Gi
    persistentvolumeclaims: "10"
```

## Secrets Management

### Option 1: External Secrets Operator (Recommended)

Both namespaces reference secrets from a central vault (Azure Key Vault, AWS Secrets Manager, HashiCorp Vault):

```yaml
# skra namespace
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: skra-secrets
  namespace: skra
spec:
  secretStoreRef:
    name: azure-keyvault-backend
    kind: ClusterSecretStore  # Shared across namespaces
  target:
    name: skra-secrets
  data:
    - secretKey: DATABASE_URL
      remoteRef:
        key: skra-db-url
```

### Option 2: Namespace-Scoped Secrets

Each namespace manages its own secrets independently.

## Ingress Configuration

### Shared Ingress Controller

Both apps share the ingress controller in `bifrost-platform`:

```yaml
# bifrost ingress
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: bifrost
  namespace: bifrost
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  ingressClassName: nginx
  rules:
    - host: bifrost.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: bifrost-client
                port:
                  number: 80
  tls:
    - hosts:
        - bifrost.example.com
      secretName: bifrost-tls

# skra ingress  
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: skra
  namespace: skra
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  ingressClassName: nginx
  rules:
    - host: dev.docs.midtowntg.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: skra-client
                port:
                  number: 80
  tls:
    - hosts:
        - dev.docs.midtowntg.com
      secretName: skra-tls
```

## Monitoring and Observability

### Shared Prometheus/Grafana

Running in `bifrost-platform` namespace, scraping both apps:

```yaml
# ServiceMonitor for bifrost
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: bifrost-metrics
  namespace: bifrost-platform
spec:
  selector:
    matchLabels:
      app.kubernetes.io/part-of: bifrost
  namespaceSelector:
    matchNames:
      - bifrost
  endpoints:
    - port: metrics
      path: /metrics

# ServiceMonitor for skra
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: skra-metrics
  namespace: bifrost-platform
spec:
  selector:
    matchLabels:
      app.kubernetes.io/part-of: skra
  namespaceSelector:
    matchNames:
      - skra
  endpoints:
    - port: metrics
      path: /metrics
```

## Backup Strategy

Each namespace has independent backup Jobs/CronJobs:

```yaml
# skra backup
apiVersion: batch/v1
kind: CronJob
metadata:
  name: skra-backup
  namespace: skra
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: backup
              image: postgres:15-alpine
              command:
                - pg_dump
                - -h
                - skra-postgres
                - -U
                - skra
                - skra
          restartPolicy: OnFailure
```

## Troubleshooting

### Check Cross-Namespace Connectivity

```bash
# From a pod in skra namespace, test Bifrost API
kubectl run debug -n skra --rm -it --image=curlimages/curl -- /bin/sh
curl http://bifrost-api.bifrost.svc.cluster.local:8000/health
```

### Verify Network Policies

```bash
# Check if traffic is being blocked
kubectl describe networkpolicy -n skra
kubectl describe networkpolicy -n bifrost
```

### Resource Usage Per Namespace

```bash
kubectl top pods -n bifrost
kubectl top pods -n skra
kubectl describe resourcequota -n bifrost
kubectl describe resourcequota -n skra
```

## Migration Path from Single Namespace

If currently running both apps in one namespace:

1. **Create new namespaces**
2. **Deploy fresh databases** in each namespace (don't share)
3. **Migrate data** using application-level export/import or database migration tools
4. **Update ingress** to point to correct namespace services
5. **Update DNS** if changing hostnames
6. **Remove old deployments** from shared namespace
7. **Apply network policies** once stable

## References

- Parent epic: #19 (Bifrost-native sync architecture)
- Constraint: MTG-Thomas/bifrost#108 (zero platform changes requirement)
- Roadmap: docs/ROADMAP.md
