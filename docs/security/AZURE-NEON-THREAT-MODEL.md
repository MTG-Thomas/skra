# Azure + Neon Proof Threat Model

## Summary

This document captures the security model for the Skra Azure + Neon proof deployment. It is proof/staging infrastructure, not a production cutover target.

## Architecture

- Azure Static Web Apps serves the React client at `https://azure-docs.midtowntg.com`.
- Entra sign-in is the outer access gate for the Static Web App and is restricted to the Midtown tenant.
- Azure Container Apps runs the FastAPI API container.
- Skra application auth still enforces JWT, cookie, API-key, role, and object-level authorization behind the Entra gate.
- Neon hosts Postgres with application metadata, passwords, documents, search index records, and entity state.
- Azure Blob Storage stores attachment/export binary content; binary data should not be stored in Neon.
- GHCR stores API/client images built by GitHub Actions.
- GitHub Actions deploys the proof API to Azure Container Apps with Entra workload identity federation, not an Azure client secret.

## Assets

- Documentation content, including imported ITGlue records.
- Password records, TOTP seeds, custom asset secrets, and attachment metadata.
- Attachment and export binaries in Azure Blob Storage.
- App JWTs, refresh cookies, API keys, and scan tokens.
- Neon connection strings, Azure Storage credentials, OpenAI keys, and deployment credentials.
- GHCR image provenance and SBOM metadata.

## Trust Boundaries

- Browser to Azure Static Web Apps: Entra controls access to the frontend host.
- Browser to Azure Container Apps API: CORS and app auth control access to API behavior.
- API to Neon: database credentials and TLS protect storage-plane access.
- API to Azure Blob: storage credentials and SAS URLs protect attachment access.
- GitHub Actions to Azure: OIDC federated credential scopes deployment to the approved environment.
- GitHub Actions to GHCR: GitHub token pushes and reads proof images.

## Primary Risks

- Broken object-level authorization across organizations or entity types.
- Attachment metadata or SAS URL leakage that permits cross-org file access.
- Secrets committed to git, printed in workflow logs, or exposed through crash output.
- Long-lived deployment credentials replacing OIDC.
- Unreviewed image or dependency vulnerabilities in the API/client containers.
- Over-broad DAST scanning against customer or third-party targets.
- Backup/restore gaps for Neon data or Azure Blob attachments.

## Current Controls

- The frontend is tenant-gated by Entra before users reach the React app.
- The API still requires Skra auth for protected endpoints.
- Security headers include HSTS, CSP, X-Frame-Options, X-Content-Type-Options, no-store cache controls, and CORP.
- ZAP baseline scanning is explicitly scoped to Midtown-owned proof endpoints.
- Authenticated ZAP API scanning uses a low-privilege proof API key from the `azure-neon-proof` GitHub environment.
- Trivy scans repository and image surfaces.
- Python/npm dependency audits and Gitleaks provide additional CI guardrails.

## Proof-Only Gaps

- Active ZAP scans are intentionally disabled until a resettable throwaway organization exists.
- The scan account must remain low privilege and tied only to proof data.
- Neon and Blob restore drills still need operator evidence before production use.
- Azure deployment OIDC requires the Entra federated credential to be present before CI can deploy without local patching.
