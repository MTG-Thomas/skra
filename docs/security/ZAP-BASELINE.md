# OWASP ZAP Baseline Scanning

Skra uses a sanctioned OWASP ZAP baseline workflow for passive DAST coverage of the Azure + Neon proof deployment.

## Scope

The workflow is intentionally limited to known Midtown-owned proof endpoints:

- Frontend: `https://azure-docs.midtowntg.com`
- API: `https://ca-skra-api-neon-dev.icymoss-8e8097f1.eastus.azurecontainerapps.io`

The workflow does not accept arbitrary URLs. Add new targets in code review so scan scope stays explicit.

## What It Runs

The workflow uses `zaproxy/action-baseline` with the stable ZAP container. This runs the ZAP spider briefly and waits for passive scanning to complete. It is intended for CI and staging-style systems because it does not run active attack payloads.

Current settings:

- manual `workflow_dispatch` target selection: `all`, `frontend`, or `api`;
- weekly scheduled scan on Monday morning UTC;
- passive baseline only;
- no GitHub issue auto-writing;
- reports uploaded as workflow artifacts;
- workflow failure for unaccepted findings after the baseline rules file is applied.

Accepted findings live in `.zap/baseline-rules.tsv`. Each accepted rule must include a short reason in code review.

## Operating Notes

- Treat this as perimeter and unauthenticated coverage first. The Entra-protected frontend and API auth boundary are part of what we want to inspect.
- Do not enable active scans against the proof environment until we have a seeded throwaway organization, a low-privilege test user, and a cleanup/reset path.
- Do not scan customer production domains or third-party systems from this workflow.
- Do not put bearer tokens, cookies, passwords, or TOTP secrets into workflow logs.
- Review reports after each run and convert real findings into tracked remediation work.

## Next Hardening Steps

1. Review the first baseline artifacts and classify findings into true positives, accepted proof limits, and false positives.
2. Add a small ZAP rules file only after triage, keeping each ignore documented.
3. Add authenticated coverage with a disposable user and seeded proof data.
4. Consider a separate active-scan workflow gated by an environment approval and pointed only at resettable test data.

## Authenticated API Coverage

Authenticated API coverage is handled separately by `.github/workflows/zap-authenticated-api.yml`. That workflow scans the proof API OpenAPI document with a low-privilege API token from the `azure-neon-proof` GitHub environment.

