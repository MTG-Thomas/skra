# Troubleshooting Multi-Namespace Deployment

## Verify Namespaces

```bash
kubectl get namespaces --show-labels
```

Expected output:
```
NAME                STATUS   AGE   LABELS
bifrost             Active   10m   app.kubernetes.io/name=bifrost,app.kubernetes.io/part-of=bifrost
skra        Active   10m   app.kubernetes.io/name=skra,app.kubernetes.io/part-of=skra
bifrost-platform    Active   10m   app.kubernetes.io/name=bifrost-platform,purpose=shared-infrastructure
```

## Check Cross-Namespace Connectivity

### From skra to bifrost API:

```bash
# Run a debug pod in skra namespace
kubectl run debug -n skra --rm -it --image=curlimages/curl -- /bin/sh

# Test connectivity
curl -v http://bifrost-api.bifrost.svc.cluster.local:8000/health

# Or use the external service shortcut
curl -v http://external-bifrost-api.skra.svc.cluster.local:8000/health
```

### If connectivity fails:

1. Check network policies:
```bash
kubectl get networkpolicy -n bifrost
kubectl get networkpolicy -n skra
describe networkpolicy allow-docs-to-bifrost-api -n bifrost
```

2. Verify DNS resolution:
```bash
nslookup bifrost-api.bifrost.svc.cluster.local
```

3. Check if pods are running:
```bash
kubectl get pods -n bifrost
kubectl get pods -n skra
```

## Check Ingress

```bash
# List all ingress resources
kubectl get ingress --all-namespaces

# Describe specific ingress
kubectl describe ingress -n skra skra

# Check ingress controller logs
kubectl logs -n bifrost-platform -l app.kubernetes.io/name=ingress-nginx
```

## Verify Resource Quotas

```bash
# Check quota usage
kubectl describe resourcequota -n bifrost
kubectl describe resourcequota -n skra

# Check resource usage
kubectl top pods -n bifrost
kubectl top pods -n skra
```

## Network Policy Debugging

```bash
# List all policies
kubectl get networkpolicy --all-namespaces

# Test if default deny is working (should fail)
kubectl run test-deny -n skra --rm -it --image=curlimages/curl -- \
  curl --connect-timeout 5 http://bifrost-client.bifrost.svc.cluster.local:80

# Test allowed path (should work)
kubectl run test-allow -n skra --rm -it --image=curlimages/curl -- \
  curl --connect-timeout 5 http://bifrost-api.bifrost.svc.cluster.local:8000/health
```

## Common Issues

### Issue: Ingress returns 502

**Cause**: Pods not ready or service selector mismatch

**Fix**:
```bash
kubectl get pods -n skra
kubectl get svc -n skra skra-api
kubectl describe svc -n skra skra-api
```

### Issue: Cross-namespace calls timeout

**Cause**: Network policy blocking, DNS resolution failing, or pods not running

**Fix**:
1. Verify network policies allow the traffic
2. Check CoreDNS is working: `kubectl get pods -n kube-system -l k8s-app=kube-dns`
3. Verify target pod is running: `kubectl get pods -n bifrost -l app.kubernetes.io/component=api`

### Issue: ResourceQuota exceeded

**Cause**: Too many pods or excessive resource requests

**Fix**:
```bash
# Check current usage
kubectl describe resourcequota -n skra

# Adjust quota or reduce replicas
kubectl edit resourcequota skra-quota -n skra
```

## Reset / Clean Up

```bash
# Delete everything (DANGER: destroys all data in these namespaces)
kubectl delete namespace bifrost skra bifrost-platform

# Or delete just the apps, keeping namespaces
kubectl delete deployment,service,configmap,secret --all -n skra
kubectl delete deployment,service,configmap,secret --all -n bifrost
```

## Useful One-Liners

```bash
# Watch all pods across namespaces
watch kubectl get pods --all-namespaces -l 'app.kubernetes.io/part-of in (bifrost, skra)'

# Check service endpoints
kubectl get endpoints -n bifrost bifrost-api
kubectl get endpoints -n skra skra-api

# View network policy logs (if using Calico)
kubectl logs -n kube-system -l k8s-app=calico-node
```
