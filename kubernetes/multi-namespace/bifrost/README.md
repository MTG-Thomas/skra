# README for bifrost namespace

This directory contains namespace-scoped resources for the Bifrost integration platform.

## Important Note

The actual application manifests for Bifrost should be sourced from:
https://github.com/MTG-Thomas/bifrost

## Deployment Options

### Option 1: GitOps (Recommended)

Use ArgoCD or Flux to deploy Bifrost manifests directly from the `MTG-Thomas/bifrost` repo into this namespace:

```yaml
# ArgoCD Application example
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: bifrost
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/MTG-Thomas/bifrost.git
    targetRevision: main
    path: k8s/overlays/production
  destination:
    server: https://kubernetes.default.svc
    namespace: bifrost
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

### Option 2: Manual Import

Clone the bifrost repo separately and apply manifests:

```bash
git clone https://github.com/MTG-Thomas/bifrost.git /tmp/bifrost
kubectl apply -k /tmp/bifrost/k8s/overlays/production/ -n bifrost
```

## Cross-Namespace Communication

Bifrost API is reachable from `skra` namespace at:
```
bifrost-api.bifrost.svc.cluster.local:8000
```

See `../skra/external-service-bifrost.yaml` for the ExternalName service that simplifies this.
