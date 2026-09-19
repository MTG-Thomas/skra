# TLS Troubleshooting Guide

## Common TLS/HTTPS Issues

### Certificate Not Valid

**Symptom:** Browser shows "Your connection is not private" / NET::ERR_CERT_INVALID

**Diagnosis:**
```bash
# Check certificate details
openssl x509 -in certs/fullchain.pem -text -noout | grep -A2 "Validity"

# Check if certificate matches domain
openssl x509 -in certs/fullchain.pem -noout -subject
```

**Solutions:**
1. **Certificate expired:**
   ```bash
   ./scripts/renew-certs.sh
   docker compose exec nginx nginx -s reload
   ```

2. **Wrong domain:**
   - Verify certificate was issued for correct domain
   - Re-run setup: `./scripts/setup-letsencrypt.sh docs.example.com`

3. **Self-signed certificate:**
   - For production, use Let's Encrypt or proper CA
   - For testing, add `--insecure` to curl or accept in browser

### HTTPS Redirect Loop

**Symptom:** Browser redirects infinitely between HTTP and HTTPS

**Diagnosis:**
```bash
curl -I -L http://docs.example.com 2>&1 | grep -E "(HTTP|Location)"
```

**Solutions:**
1. Check `X-Forwarded-Proto` header is being passed:
   ```nginx
   proxy_set_header X-Forwarded-Proto $scheme;
   ```

2. If behind another proxy (Cloudflare, AWS ALB), use:
   ```nginx
   map $http_x_forwarded_proto $forwarded_proto {
       default $http_x_forwarded_proto;
       ''      $scheme;
   }
   ```

### Mixed Content Warnings

**Symptom:** Browser shows "Mixed content" warnings, some resources not loading

**Diagnosis:**
- Open browser DevTools → Console
- Look for "Mixed Content: The page at 'https://...' was loaded over HTTPS, but requested an insecure resource"

**Solutions:**
1. **Application configuration:**
   - Set `SKRA_WEBAUTHN_ORIGIN` to HTTPS URL
   - Ensure API returns HTTPS URLs in responses

2. **Content-Security-Policy:**
   ```nginx
   add_header Content-Security-Policy "upgrade-insecure-requests" always;
   ```

### Certificate Renewal Failing

**Symptom:** Auto-renewal not working, certificates expiring

**Diagnosis:**
```bash
# Check renewal logs
tail -f /var/log/letsencrypt-renewal.log

# Test renewal manually
certbot renew --dry-run
```

**Solutions:**
1. **Nginx not serving .well-known:**
   - Verify nginx config has:
     ```nginx
     location /.well-known/acme-challenge/ {
         root /var/www/certbot;
     }
     ```

2. **Cron job not running:**
   ```bash
   crontab -l | grep renew-certs
   # Should show: 0 3 * * 0 /path/to/renew-certs.sh
   ```

3. **Rate limiting:**
   - Let's Encrypt has rate limits: https://letsencrypt.org/docs/rate-limits/
   - Use staging server for testing: `--staging` flag

### TLS Handshake Failures

**Symptom:** curl/requests fail with "SSL handshake failed"

**Diagnosis:**
```bash
# Test with verbose output
curl -vI https://docs.example.com 2>&1 | grep -E "(SSL|TLS|handshake)"

# Check supported protocols
nmap --script ssl-enum-ciphers -p 443 docs.example.com
```

**Solutions:**
1. **Old TLS version:**
   - Update nginx config to allow TLS 1.2+
   - Disable SSLv3, TLS 1.0, TLS 1.1

2. **Cipher suite mismatch:**
   - Use Mozilla's recommended cipher suites:
     ```nginx
     ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384;
     ```

### OCSP Stapling Errors

**Symptom:** SSL Labs shows OCSP stapling as "No"

**Diagnosis:**
```bash
openssl s_client -connect docs.example.com:443 -status 2>&1 | grep -A5 "OCSP response"
```

**Solutions:**
1. **Enable stapling in nginx:**
   ```nginx
   ssl_stapling on;
   ssl_stapling_verify on;
   ssl_trusted_certificate /path/to/chain.pem;
   ```

2. **Verify chain is complete:**
   - Must include intermediate certificates
   - Usually in `fullchain.pem` from Let's Encrypt

### Kubernetes cert-manager Issues

**Symptom:** Certificate not being created or renewed

**Diagnosis:**
```bash
# Check Certificate status
kubectl describe certificate skra-tls -n skra

# Check CertificateRequest
kubectl get certificaterequests -n skra

# Check Challenge
kubectl get challenges -n skra
kubectl describe challenge <challenge-name> -n skra
```

**Common Solutions:**
1. **ClusterIssuer not found:**
   ```bash
   kubectl get clusterissuers
   kubectl apply -f kubernetes/cert-manager/cluster-issuer.yaml
   ```

2. **HTTP challenge failing:**
   - Check ingress controller is running
   - Verify nginx is serving `.well-known/acme-challenge/`
   - Check for network policies blocking ingress

3. **Secret already exists:**
   ```bash
   kubectl delete secret skra-tls -n skra
   # cert-manager will recreate it
   ```

## Testing Commands

### Basic Connectivity
```bash
# Test HTTP
curl -I http://docs.example.com

# Test HTTPS
curl -I https://docs.example.com

# Test with certificate verification
curl --cacert certs/chain.pem -I https://docs.example.com
```

### Certificate Information
```bash
# View certificate details
openssl x509 -in certs/fullchain.pem -text -noout

# Check certificate chain
openssl crl2pkcs7 -nocrl -certfile certs/fullchain.pem | openssl pkcs7 -print_certs -noout

# Verify certificate against CA
openssl verify -CAfile certs/chain.pem certs/fullchain.pem

# Check expiration date
openssl x509 -in certs/fullchain.pem -noout -enddate
```

### SSL/TLS Testing
```bash
# Test SSL Labs (external)
# Visit: https://www.ssllabs.com/ssltest/analyze.html?d=docs.example.com

# Test with nmap
nmap --script ssl-cert,ssl-enum-ciphers -p 443 docs.example.com

# Test specific TLS version
curl --tlsv1.3 -I https://docs.example.com
curl --tlsv1.2 -I https://docs.example.com
```

## Emergency Procedures

### Certificate Expired and Site Down

1. **Quick fix with self-signed certificate:**
   ```bash
   openssl req -x509 -nodes -days 1 -newkey rsa:2048 \
     -keyout certs/privkey.pem -out certs/fullchain.pem \
     -subj "/CN=docs.example.com"
   docker compose exec nginx nginx -s reload
   ```

2. **Restore from backup:**
   ```bash
   cp /backups/certs-backup/*.pem certs/
   docker compose exec nginx nginx -s reload
   ```

3. **Emergency Let's Encrypt:**
   ```bash
   certbot certonly --standalone -d docs.example.com --force-renewal
   cp /etc/letsencrypt/live/docs.example.com/*.pem certs/
   docker compose exec nginx nginx -s reload
   ```

### Completely Disable TLS (Emergency Only)

```bash
# Use non-TLS nginx config
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d nginx

# Remove 443 port binding temporarily
```

⚠️ **Warning:** Only do this temporarily! Always restore TLS ASAP.
