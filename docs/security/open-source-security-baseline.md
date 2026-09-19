# Skra Open-Source Security Baseline

This baseline is intentionally tuned to Skra: a FastAPI API, Vite/React
client, Docker/Compose runtime, Kubernetes manifests, Azure Bicep, and migration
tooling that may handle customer documentation exports and vendor API tokens.

## Local Commands

Run the fast local checks before security-sensitive changes:

```bash
python -m pip install semgrep==1.161.0 pip-audit
semgrep scan --config .semgrep/skra.yml --exclude client/src/lib/v1.d.ts --exclude client/playwright-report --exclude client/test-results --severity ERROR --error
python -m pip install ./api
pip-audit --strict
npm --prefix client audit --audit-level=high --omit=dev
osv-scanner scan --recursive .
gitleaks protect --staged --redact
trivy config --severity HIGH,CRITICAL .
```

Dependency checks are advisory in the PR workflow until the current lockfile
findings are remediated. Promote them to blocking by removing
`continue-on-error` from the dependency job once that baseline is clean.
The PR Gitleaks job scans the checked-out tree, not full Git history, because
the existing history currently contains findings that need separate cleanup.

Keep personal pre-commit hooks local to `.git/hooks` and helper excludes in
`.git/info/exclude`. Shared security policy lives in the tracked workflow and
config files.

## Threats Covered First

- Tenant or organization scope mistakes in API routers and repositories.
- Secret, token, password, and OAuth credential logging.
- Unsafe subprocess usage in migration and maintenance tooling.
- Raw HTML rendering in the React client.
- Dependency, container, Kubernetes, Bicep, and committed-secret exposure.

## CI Layers

- `security-pr.yml`: fast PR checks for Semgrep, Gitleaks, dependency advisories,
  OSV-Scanner, and Trivy config/filesystem scanning. Semgrep and Gitleaks block
  PRs; dependency and Trivy hardening findings initially report until the
  existing baseline is remediated.
- `codeql.yml`: deeper Python and JavaScript/TypeScript CodeQL analysis on PRs,
  weekly schedule, and manual dispatch.
Runtime ZAP/Schemathesis is intentionally deferred until the repo has a stable
scan-user bootstrap and disposable authenticated test stack.

## Validation Probes

Use temporary scratch branches to confirm detectors still fire:

- Hardcode a fake live-looking key and confirm Gitleaks/Trivy block it.
- Add a logger call containing `refresh_token` and confirm Semgrep blocks it.
- Create an ad hoc superuser access token outside auth/security and confirm
  Semgrep blocks it.
- Add unsafe `dangerouslySetInnerHTML` without DOMPurify and confirm Semgrep or
  CodeQL flags it.
- Add a deliberate API 500 on malformed request data and confirm Schemathesis
  reproduces it in the nightly workflow.
