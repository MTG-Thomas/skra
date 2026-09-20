# Infrastructure & Hardening Assessment

> Assessment Date: 2026-04-06
> Target: Get Skra production-ready before adding new features

---

## ✅ What's Already in Place

### Security (Good Foundation)
- ✅ **Password Hashing**: bcrypt via pwdlib (modern passlib replacement)
- ✅ **Encryption at Rest**: Fernet encryption for passwords, TOTP secrets, API keys
- ✅ **JWT Tokens**: HS256 with configurable expiration
- ✅ **CORS**: Configurable origin whitelist
- ✅ **Non-root Docker containers**: Running as UID 1000
- ✅ **Health checks**: On all containers
- ✅ **SQL Injection Protection**: SQLAlchemy ORM (parameterized queries)
- ✅ **Input Validation**: Pydantic models throughout

### Container Orchestration
- ✅ **Docker Compose**: Dev and production configs
- ✅ **Kubernetes**: Basic manifests (deployments, services, configmaps, secrets)
- ✅ **Init containers**: For database migrations
- ✅ **Resource limits**: CPU/memory defined in K8s
- ✅ **Probes**: Liveness and readiness probes configured

### Data Storage
- ✅ **PostgreSQL**: Primary database with pgvector for semantic search
- ✅ **Redis/Valkey**: Caching, pub/sub, job queue
- ✅ **S3-compatible storage**: Garage (replaces MinIO, MPL-2.0 license)
- ✅ **Connection pooling**: PgBouncer for production

### Authentication & Authorization
- ✅ **Multi-factor auth**: TOTP support
- ✅ **Passkeys/WebAuthn**: Modern passwordless auth
- ✅ **OAuth/OIDC**: Provider support
- ✅ **Role-based access**: owner/admin/contributor/reader
- ✅ **API Keys**: For service accounts

---

## 🔴 Critical Gaps (Fix First)

### 1. **No CI/CD Pipeline**
**Risk**: Manual deployments are error-prone, no automated testing
**Fix Needed**:
- GitHub Actions workflow for build, test, deploy
- Automated testing on PRs
- Docker image builds and pushes
- Deployment to staging/production

### 2. **No Rate Limiting**
**Risk**: API vulnerable to brute force, DDoS
**Fix Needed**:
- Add slowapi or fastapi-limiter
- Configure per-endpoint limits (auth: strict, API: moderate)
- Redis-backed rate limit storage

### 3. **No Database Backups**
**Risk**: Data loss on corruption/deletion
**Fix Needed**:
- Automated pg_dump backups
- S3 backup storage
- Point-in-time recovery setup
- Backup verification/testing

### 4. **Missing Security Headers**
**Risk**: XSS, clickjacking, MIME sniffing attacks
**Fix Needed**:
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- Content-Security-Policy
- Strict-Transport-Security (HSTS)
- Referrer-Policy

### 5. **No Reverse Proxy/Ingress**
**Risk**: Direct API exposure, no TLS termination, no load balancing
**Fix Needed**:
- Nginx/Traefik/Caddy configuration
- TLS certificate management (Let's Encrypt)
- Request buffering, gzip compression
- DDoS protection

---

## 🟡 Important Improvements

### 6. **Logging & Monitoring**
**Current**: Basic console logging
**Improvements**:
- Structured logging (JSON format)
- Centralized log aggregation (Loki/ELK)
- Application metrics (Prometheus)
- Dashboards (Grafana)
- Alerting for errors/high latency

### 7. **Secrets Management**
**Current**: Environment variables only
**Improvements**:
- Support for external secret stores (Vault, AWS Secrets Manager)
- Secret rotation procedures
- Development vs production separation

### 8. **Input Validation & Sanitization**
**Review Needed**:
- HTML sanitization for rich text (documents)
- File upload validation (size, type, malware scanning)
- SQL injection audit (raw queries)
- XSS prevention in API responses

### 9. **API Hardening**
**Missing**:
- Request size limits
- Timeout configurations
- Pagination limits enforcement
- API versioning strategy

### 10. **Test Coverage**
**Current**: Basic pytest setup
**Gaps**:
- E2E tests with Playwright (just added, need more)
- Load testing (k6/Locust)
- Security testing (OWASP ZAP)
- Dependency vulnerability scanning (Snyk/Trivy)

---

## 🟢 Nice to Have

### 11. **Documentation**
- Production deployment runbook
- Incident response procedures
- Disaster recovery plan
- Security audit report

### 12. **Performance**
- CDN for static assets
- Database query optimization review
- Caching strategy (Redis usage)
- Connection pool tuning

### 13. **Compliance**
- GDPR data handling audit
- Data retention policies
- Audit log completeness review

---

## 📋 Recommended Priority Order

### Phase 1: Security Hardening (Do Now)
1. Add security headers middleware
2. Implement rate limiting
3. Set up reverse proxy with TLS
4. Review input validation/sanitization

### Phase 2: Reliability (Next)
5. Create CI/CD pipeline
6. Add database backup automation
7. Improve logging and monitoring
8. Add comprehensive testing

### Phase 3: Production Readiness (Later)
9. Secrets management improvements
10. Performance optimization
11. Documentation and runbooks
12. Compliance audit

---

## 🚀 Quick Wins (Can Do Today)

1. **Add security headers middleware** (~1 hour)
2. **Create GitHub Actions workflow** (~2 hours)
3. **Set up rate limiting** (~2 hours)
4. **Create backup script** (~1 hour)
5. **Add nginx reverse proxy config** (~2 hours)

---

## 📊 Current Status Summary

| Category | Status | Score |
|----------|--------|-------|
| Authentication | Strong | 9/10 |
| Encryption | Strong | 9/10 |
| Container Security | Good | 8/10 |
| Kubernetes Config | Basic | 6/10 |
| CI/CD | Missing | 0/10 |
| Rate Limiting | Missing | 0/10 |
| Backups | Missing | 0/10 |
| Monitoring | Minimal | 3/10 |
| **Overall** | **Needs Work** | **5/10** |

---

## Next Steps

**Pick one of these to start:**
1. "Add security headers" - Quick win, improves security posture immediately
2. "Set up GitHub Actions" - Foundation for all other improvements
3. "Add rate limiting" - Critical for production API protection
4. "Create backup solution" - Essential for data safety

Which would you like me to tackle first?

---

## ✅ Completed: Rate Limiting (2026-04-06)

**Implemented:** Redis-backed rate limiting using slowapi

### Configuration

| Endpoint Category | Limits | Purpose |
|-------------------|--------|---------|
| AUTH_STRICT | 5/min, 20/hr | Registration, password reset |
| AUTH_LOGIN | 10/min, 50/hr | Login attempts |
| PASSKEY | 10/min, 30/hr | WebAuthn operations |
| API_GENERAL | 100/min, 1000/hr | Standard API calls |
| HEALTH | 1000/min | Health check endpoints |

### Protected Endpoints
- All `/auth/*` endpoints (login, register, refresh, etc.)
- All `/auth/passkeys/*` endpoints
- `/health` endpoint

### How It Works
- Rate limits stored in Redis (shared across API instances)
- Keys based on client IP address
- Different limits per endpoint category
- Returns 429 Too Many Requests when limit exceeded

### Development vs Production
- **Development**: Rate limiting disabled if slowapi not installed
- **Production**: Active when CI builds images with slowapi

### Future Improvements
- [ ] Add per-user rate limits (in addition to per-IP)
- [ ] Add API key-specific limits
- [ ] Add endpoint for checking current rate limit status
- [ ] Add rate limit headers to responses (X-RateLimit-*)

---

## ✅ Completed: Security Headers (2026-04-06)

**Implemented:** OWASP recommended security headers middleware

### Headers Added

| Header | Value | Protection |
|--------|-------|------------|
| X-Content-Type-Options | nosniff | MIME sniffing |
| X-Frame-Options | DENY | Clickjacking |
| X-XSS-Protection | 1; mode=block | XSS (legacy) |
| Content-Security-Policy | See below | XSS, injection |
| Referrer-Policy | strict-origin-when-cross-origin | Privacy |
| Permissions-Policy | Feature restrictions | Permission abuse |
| Strict-Transport-Security | max-age=31536000 (prod) | SSL downgrade |

### Development vs Production CSP

**Development:**
```
default-src 'self';
script-src 'self' 'unsafe-inline' 'unsafe-eval';
style-src 'self' 'unsafe-inline';
img-src 'self' data: blob: https:;
font-src 'self' data:;
connect-src 'self' ws: wss:;
media-src 'self';
object-src 'none';
frame-ancestors 'none'
```

**Production:**
```
default-src 'self';
script-src 'self';
style-src 'self' 'unsafe-inline';
img-src 'self' data: blob:;
font-src 'self';
connect-src 'self';
media-src 'self';
object-src 'none';
frame-ancestors 'none';
base-uri 'self';
form-action 'self'
```

### Middleware
- All responses include security headers automatically
- Applied via `SecurityHeadersMiddleware` in FastAPI
