# Security Operations Runbook

## ZAP Baseline

The unauthenticated baseline workflow is `.github/workflows/zap-baseline.yml`.

Approved targets are hardcoded:

- `https://azure-docs.midtowntg.com`
- `https://ca-skra-api-neon-dev.icymoss-8e8097f1.eastus.azurecontainerapps.io`

Run it manually from GitHub Actions with target `all`, `frontend`, or `api`. Reports are uploaded as workflow artifacts. Do not add arbitrary scan URLs.

Accepted baseline warnings are documented in `.zap/baseline-rules.tsv`. The initial accepted API finding is `10049 Non-Storable Content`, because API responses deliberately send `no-store` cache controls.

## Authenticated API Scan

The authenticated API workflow is `.github/workflows/zap-authenticated-api.yml`.

It scans the proof API OpenAPI document with an `Authorization: Bearer` header injected by ZAP replacer configuration. The token comes from the `azure-neon-proof` GitHub environment secret:

`SKRA_ZAP_API_TOKEN`

The token should belong to a dedicated low-privilege Skra scan identity, preferably `READER`, and should only have access to proof data.

Never print tokens, cookies, TOTP seeds, or API keys in workflow logs.

## Finding Triage

- High-risk or exploitable findings block proof promotion.
- New medium-risk findings require review before promotion.
- Accepted warnings must be documented in `.zap/*.tsv` with a reason.
- Informational findings may remain as artifacts if they are understood and documented.
- Suspected false positives should be linked to a concrete route/header/body example.

## Dependency and Secret Guardrails

CI security checks should keep this policy:

- Gitleaks blocks PRs for committed secrets.
- Semgrep/Gitleaks-style code findings should be low-noise and blocking.
- `pip-audit` and `npm audit` block high/critical dependency issues when they are actionable.
- Trivy uploads SARIF for repo/image visibility and gates fixed high/critical image vulnerabilities.

## Deployment Identity

Azure proof deployment uses Entra workload identity federation for GitHub Actions. Do not add an Azure client secret.

The federated credential must match:

`repo:MTG-Thomas/skra:environment:azure-neon-proof`

Manual ACA patching is only a fallback while the federated credential is missing.

## Out of Scope Until Resettable Test Data Exists

- Active ZAP scans.
- Destructive API fuzzing.
- Scanning customer production domains.
- Scanning third-party systems.
