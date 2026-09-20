# Reverse Proxy & TLS Deployment Guide

This directory contains production-ready configurations for deploying Skra with reverse proxy and TLS termination.

## Quick Start

### Option 1: Docker Compose with Nginx (Recommended for single-node)

```bash
# 1. Copy and customize the configuration
cp config/nginx.production.conf config/nginx.conf
cp .env.example .env
# Edit .env with your domain and secrets

# 2. Start with production configuration
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.tls.yml up -d

# 3. Obtain TLS certificates
./scripts/setup-letsencrypt.sh

# 4. Reload nginx
docker compose exec nginx nginx -s reload
```

### Option 2: Kubernetes with cert-manager (Recommended for clusters)

```bash
# 1. Install cert-manager in your cluster
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.0/cert-manager.yaml

# 2. Apply the ClusterIssuer
kubectl apply -f kubernetes/cert-manager/cluster-issuer.yaml

# 3. Deploy with TLS ingress
kubectl apply -k kubernetes/overlays/production/
```

## Directory Structure

```
config/
├── nginx.conf                    # Base nginx config (development)
├── nginx.production.conf         # Production nginx with TLS
└── nginx/snippets/               # Reusable nginx snippets
    ├── security-headers.conf
    ├── ssl-params.conf
    └── gzip.conf

scripts/
├── setup-letsencrypt.sh          # Let's Encrypt certificate setup
├── renew-certs.sh                # Certificate renewal
└── tls-health-check.sh           # TLS configuration verification

kubernetes/
├── cert-manager/
│   ├── cluster-issuer.yaml       # Let's Encrypt ClusterIssuer
│   └── certificate.yaml          # Certificate resource
└── base/
    └── ingress-tls.yaml          # TLS-enabled ingress
```

## Configuration Options

### TLS Certificate Sources

| Method | Use Case | Configuration |
|--------|----------|---------------|
| Let's Encrypt (ACME) | Public domains | `docker-compose.tls.yml` or cert-manager |
| Custom certificates | Private/internal domains | Mount certs to `./certs/` |
| Cloud provider LB | AWS/GCP/Azure | Use their certificate management |
| External TLS proxy | Advanced setups | Terminate at edge proxy |

### Security Headers

All configurations include:
- HSTS (HTTP Strict Transport Security)
- X-Frame-Options: DENY
- X-Content-Type-Options: nosniff
- X-XSS-Protection
- Referrer-Policy
- Content-Security-Policy (configurable)

## Health Checks

Verify your TLS setup:

```bash
# Check certificate validity
curl -vI https://docs.example.com 2>&1 | grep -E "(SSL|TLS|certificate)"

# Test SSL Labs rating (external)
# https://www.ssllabs.com/ssltest/analyze.html?d=docs.example.com

# Run local health check
./scripts/tls-health-check.sh docs.example.com
```

## Troubleshooting

See [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) for common issues.

## References

- [Nginx SSL Best Practices](https://nginx.org/en/docs/http/ngx_http_ssl_module.html)
- [Let's Encrypt Documentation](https://letsencrypt.org/docs/)
- [cert-manager Documentation](https://cert-manager.io/docs/)
