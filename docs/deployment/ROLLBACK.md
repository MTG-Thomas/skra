# Test VM Rollback

Use this runbook to redeploy a previous known-good `skra` build to the test VM.

## Find a Candidate Commit

Use the last successful CI/CD pair from GitHub Actions:

```powershell
gh run list --repo MTG-Thomas/skra --workflow "CD - Deploy Test VM" --branch main --limit 10
```

Pick the commit SHA associated with the last healthy deployment.

## Redeploy by Commit

Run the existing CD workflow manually with the selected commit SHA:

```powershell
gh workflow run cd.yml --repo MTG-Thomas/skra --ref main -f ref=<commit-sha>
```

The workflow resolves the short SHA, pulls the pinned GHCR images, deploys over NetBird, and verifies:

```text
https://dev.docs.midtowntg.com/health
```

## Verify

Watch the deployment:

```powershell
gh run list --repo MTG-Thomas/skra --workflow "CD - Deploy Test VM" --limit 3
gh run watch <run-id> --repo MTG-Thomas/skra --exit-status
```

If rollback fails, inspect the deploy job logs first. The deploy script preserves the VM `.env` and Garage config and only changes the checked-out repo revision plus pinned image tags.
