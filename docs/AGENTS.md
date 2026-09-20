# Multi-Agent Development Workflow

This repository uses multiple AI coding agents (OpenCode, Kilo, etc.) to collaboratively develop Skra. This document defines the workflow for coordination.

## Philosophy

- **Issue-driven**: All work is tracked in GitHub issues
- **Transparent**: Agents communicate progress via issue comments
- **Non-blocking**: Agents work on separate issues or clearly separated areas
- **Quality-focused**: Changes are tested and reviewed before completion

---

## Agent Identification

| Agent | Label | Focus Areas |
|-------|-------|-------------|
| OpenCode | `OpenCode` | Backend API, database, infrastructure |
| Kilo | `Kilo` | Frontend UI, React components, styling |

*Note: These are flexible — agents can pick up any issue, but default to their strengths.*

---

## Workflow Overview

### 1. Issue States & Labels

**Agent Assignment:**
- `OpenCode` — Claimed by OpenCode agent
- `Kilo` — Claimed by Kilo agent

**Progress States:**
- `in-progress` — Actively being worked on
- `needs-review` — Ready for human review or agent handoff
- `blocked` — Blocked by dependency or question
- `ready-to-merge` — Approved, waiting for merge

**Priority:**
- `P0-critical` — Blocks release, fix immediately
- `P1-high` — Major feature or bug, do next
- `P2-medium` — Normal priority
- `P3-low` — Nice to have, backlog

### 2. The Claiming Process

Before starting work:

```bash
# 1. Check what's already claimed
gh issue list --label "OpenCode" --state open
gh issue list --label "Kilo" --state open

# 2. Find unassigned issues in priority order
gh issue list --label "P1-high" --state open --no-assignee

# 3. Claim the issue
gh api repos/MTG-Thomas/skra/issues/{ISSUE_NUMBER}/labels \
  -X POST \
  -f "labels[]=OpenCode" \
  -f "labels[]=in-progress"

# 4. Post a comment to start
git api repos/MTG-Thomas/skra/issues/{ISSUE_NUMBER}/comments \
  -X POST \
  -f "body=Starting work on this. Plan:\n\n1. [step]\n2. [step]\n3. [step]"
```

### 3. Working on an Issue

**Branch Naming:**
```
feature/{issue-number}-{agent-name}-{short-description}
# Example: feature/12-opencode-totp-filter
```

**Commit Messages:**
```
feat(passwords): add TOTP column filter (#12)

- Add has_totp filter to password repository
- Update API endpoint with has_totp query param
- Integrate with DataTable column filters

Agent: OpenCode
```

**Progress Updates:**
Post comments on the issue when:
- Starting work (with plan)
- Hitting a blocker or need clarification
- Completing milestones
- Ready for review/handoff

### 4. Handoff Between Agents

When an issue needs both frontend and backend:

1. **Agent A** (e.g., OpenCode for backend):
   - Creates branch: `feature/12-opencode-totp-filter`
   - Implements backend changes
   - Commits with descriptive messages
   - Pushes branch
   - Comments: "Backend complete. Handing off to @Kilo for frontend integration. Branch: `feature/12-opencode-totp-filter`"
   - Updates labels: removes `in-progress`, adds `needs-review`

2. **Agent B** (e.g., Kilo for frontend):
   - Checks out the same branch: `git fetch && git checkout feature/12-opencode-totp-filter`
   - Implements frontend changes
   - Commits and pushes to same branch
   - Comments: "Frontend complete. Ready for final review."
   - Updates labels: adds `ready-to-merge`

### 5. Completing an Issue

When work is done:

1. **Final comment** summarizing changes
2. **Remove** `in-progress` label
3. **Add** `ready-to-merge` or `needs-review` label
4. **Push** all commits to the feature branch
5. **Human reviews** and merges (or agent merges if authorized)

### 6. Issue Templates for Agents

When creating new issues for agents, use this format:

```markdown
## Goal
One sentence description of what needs to be done.

## Context
Background information, links to relevant code, or related issues.

## Acceptance Criteria
- [ ] Specific, testable item 1
- [ ] Specific, testable item 2
- [ ] Specific, testable item 3

## Technical Notes
- API endpoints involved
- Database changes needed
- Frontend components affected

## Suggested Approach
Optional: High-level approach if known.

## Estimated Effort
- [ ] Small (< 2 hours)
- [ ] Medium (2-6 hours)
- [ ] Large (> 6 hours)

---
**Labels to add:** `P1-high` or `P2-medium`, `backend` or `frontend`
```

---

## Area Ownership (Default Guidelines)

| Area | Primary Agent | Secondary | Notes |
|------|---------------|-----------|-------|
| API routes (`api/src/routers/`) | OpenCode | Kilo | REST endpoints |
| Database models (`api/src/models/`) | OpenCode | — | Schema changes |
| Repository layer (`api/src/repositories/`) | OpenCode | — | Data access |
| Services (`api/src/services/`) | OpenCode | — | Business logic |
| React pages (`client/src/pages/`) | Kilo | OpenCode | Route components |
| UI components (`client/src/components/`) | Kilo | — | Shared components |
| Hooks (`client/src/hooks/`) | Kilo | OpenCode | Data fetching |
| Styling/Tailwind | Kilo | — | CSS, themes |
| DevOps/Docker/K8s | OpenCode | — | Infrastructure |
| Documentation | Both | — | Docs, comments |

---

## Communication Guidelines

### Inside Issue Comments

**Starting work:**
```markdown
**Starting:** Claiming this issue.

**Plan:**
1. Update repository layer with filter support
2. Add query param to API endpoint
3. Update frontend hook to use filter
4. Add DataTable filter configuration

**ETA:** 30 minutes
```

**Blocker:**
```markdown
**Blocked:** Need clarification on filter behavior.

**Question:** Should the TOTP filter show "Has TOTP" / "No TOTP" options, or is a boolean toggle sufficient?

cc: @MTG-Thomas
```

**Handoff:**
```markdown
**Complete:** Backend implementation finished.

**Branch:** `feature/12-opencode-totp-filter`

**Changes:**
- `api/src/repositories/password.py` — Added `has_totp` filter
- `api/src/routers/passwords.py` — Added `has_totp` query param

**Handing off to:** @Kilo for frontend integration.
```

**Complete:**
```markdown
**Done:** All acceptance criteria met.

**Summary:**
- Implemented TOTP column filter for passwords
- URL-synced filter state (`?has_totp=true|false`)
- Server-side filtering across all pages

**Files changed:**
- `api/src/repositories/password.py`
- `api/src/routers/passwords.py`
- `client/src/hooks/usePasswords.ts`
- `client/src/pages/passwords/PasswordsPage.tsx`

**Testing:**
- TypeScript compilation passes
- Python imports verified
- Manual testing: filter appears in toolbar, filters correctly

**Ready for:** Review & merge
```

---

## Daily Standup (Optional)

If you want daily updates, agents can post to a dedicated issue (#daily-standup or similar):

```markdown
## 2026-04-03 — OpenCode

**Yesterday:**
- Completed TOTP filter for passwords (#12)
- Fixed grey card input contrast

**Today:**
- Pick up API documentation issue (#11)

**Blocked:** None
```

---

## Quick Reference Commands

```bash
# List my issues
gh issue list --label "OpenCode" --state open

# Claim an issue
gh api repos/MTG-Thomas/skra/issues/{N}/labels \
  -X POST -f "labels[]=OpenCode" -f "labels[]=in-progress"

# Post progress comment
gh api repos/MTG-Thomas/skra/issues/{N}/comments \
  -X POST -f "body=Update: ..."

# Create branch
git checkout -b feature/{N}-{agent}-{description}

# Push and track
git push -u origin feature/{N}-{agent}-{description}
```

---

## Testing

### Test Suite Overview

The repository includes multiple testing layers:

| Type | Location | Command | Description |
|------|----------|---------|-------------|
| **Unit** | `api/tests/unit/` | `pytest tests/unit/` | FastAPI endpoint tests |
| **Integration** | `api/tests/integration/` | `pytest tests/integration/` | Database + API tests |
| **E2E** | `client/e2e/tests/` | `npm run test:e2e` | Playwright browser tests |

### Running Tests

**Backend (API):**
```bash
# All tests
./test.sh

# Specific test file
docker compose run --rm api pytest tests/integration/test_auth.py -v
```

**Frontend (E2E):**
```bash
cd client

# Install browsers (one-time)
npx playwright install

# Run all E2E tests
npm run test:e2e

# Interactive UI mode (for debugging)
npm run test:e2e:ui

# Specific test file
npm run test:e2e -- auth.smoke.spec.ts

# Specific browser
npm run test:e2e -- --project=chromium
```

### E2E Test Structure

```
client/e2e/
├── tests/
│   ├── test-utils.ts          # Shared fixtures & helpers
│   ├── auth.smoke.spec.ts     # Authentication tests
│   ├── navigation.smoke.spec.ts # Navigation tests
│   ├── passwords.smoke.spec.ts  # Password CRUD tests
│   └── responsive.spec.ts     # Mobile/tablet tests
├── README.md                  # E2E testing guide
└── .gitignore                 # Test artifacts
```

### Test Configuration

E2E tests use environment variables (see `client/.env.e2e.example`):

```bash
E2E_BASE_URL=http://localhost:8080
E2E_TEST_EMAIL=test@example.com
E2E_TEST_PASSWORD=TestPassword123!
E2E_TEST_ORG_ID=test-org-uuid
```

### Writing E2E Tests

Use the test utilities for common operations:

```typescript
import { test, expect, navigateToEntity } from './test-utils';

test('should create password', async ({ page }) => {
  // Auto-logged in via fixture
  await navigateToEntity(page, 'org-id', 'passwords');
  
  // Use role-based selectors
  await page.getByRole('button', { name: 'Add Password' }).click();
  
  // Assert
  await expect(page.getByRole('heading', { name: 'Create Password' })).toBeVisible();
});
```

---

## Questions or Process Changes

If this workflow needs adjustment:
1. Create an issue labeled `process`
2. Discuss in the issue
3. Update this document via PR

---

*Last updated: 2026-04-03*
