# Hello Kilo! 👋

Welcome to the Skra multi-agent workflow. This guide will get you started.

## Quick Start

### 1. See What's Available

```bash
./scripts/agent.sh next
```

This shows unclaimed high and medium priority issues.

### 2. Claim an Issue

```bash
./scripts/agent.sh claim 14 Kilo
```

This adds the `Kilo` and `in-progress` labels to issue #14.

### 3. Post Progress

Post comments on the issue as you work:

```markdown
**Starting:** Claiming this issue.

**Plan:**
1. Build TOTP display component
2. Add to Password detail page
3. Add to Custom Asset fields

**ETA:** 45 minutes
```

### 4. Mark Done

```bash
./scripts/agent.sh done 14
```

This adds `ready-to-merge` label and posts a completion comment.

---

## Your Default Areas

| Area | Path | Notes |
|------|------|-------|
| React Pages | `client/src/pages/**/*.tsx` | Route components |
| UI Components | `client/src/components/**/*.tsx` | Shared components |
| Hooks | `client/src/hooks/*.ts` | Data fetching |
| Styling | `client/src/components/ui/*.tsx` | shadcn/ui base |

## Frontend Stack

- **Build:** Vite + React + TypeScript
- **Styling:** TailwindCSS + shadcn/ui
- **State:** TanStack Query (server), Zustand (client)
- **Forms:** React Hook Form + Zod

## Testing Your Changes

```bash
# Start the dev stack
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# Type check
docker compose run --rm client npm run tsc

# Frontend at http://localhost:8080
```

---

## Workflow Patterns

### Frontend-Only Changes

```bash
# Claim issue
./scripts/agent.sh claim 15 Kilo

# Work on feature branch
git checkout -b feature/15-kilo-dark-mode

# Make changes, commit, push
git add .
git commit -m "feat(ui): add dark mode toggle (#15)"
git push -u origin feature/15-kilo-dark-mode

# Post progress comments on issue
./scripts/agent.sh progress 15

# When done
./scripts/agent.sh done 15
```

### Handoff from OpenCode

When OpenCode finishes backend work:

1. **Check issue comments** for branch name (e.g., `feature/12-opencode-totp-filter`)
2. **Check out the same branch:**
   ```bash
   git fetch
   git checkout feature/12-opencode-totp-filter
   ```
3. **Add frontend commits** to same branch
4. **Push** — commits go to the same PR/branch
5. **Post comment:** "Frontend complete, ready for review"

---

## Communication Examples

**Starting work:**
```markdown
**Starting:** Issue #15 - Dark mode toggle.

**Approach:** Add theme provider, toggle in settings, persist to localStorage.

**Files to touch:**
- `client/src/components/ui/theme-provider.tsx` (new)
- `client/src/pages/settings/SettingsPage.tsx`

**ETA:** 1 hour
```

**Blocked:**
```markdown
**Blocked:** Need decision on theme storage.

**Question:** Should theme preference be per-user (saved to API) or per-device (localStorage)?

cc: @MTG-Thomas
```

**Handoff:**
```markdown
**Complete:** Frontend implementation done.

**Branch:** `feature/12-opencode-totp-filter`

**Changes:**
- Added `TOTPDisplay` component
- Integrated into Password detail page

**Handing off to:** @OpenCode for backend integration (or ready to merge if backend is done).
```

---

## Available Issues for You

Based on the current backlog, these are frontend-focused:

- **#14** Phase 23: TOTP frontend — TOTPDisplay component, Password UI, Custom Asset UI
- **#10** Testing: E2E tests — Playwright setup, test writing
- Any polish items marked `frontend` label

---

## Coordination with OpenCode

**OpenCode's areas:** API routes, database models, repositories, services, DevOps
**Your areas:** React pages, components, hooks, styling, UI/UX

**When working on the same issue:**
- OpenCode typically does backend first
- You do frontend second
- Same branch, sequential commits
- Communicate via issue comments

---

## Resources

- **Full workflow:** `docs/AGENTS.md`
- **API client:** `client/src/lib/api-client.ts`
- **UI components:** `client/src/components/ui/`
- **Hooks:** `client/src/hooks/`

---

## First Task Suggestion

Pick up **#14** (TOTP frontend) — the backend is already done by OpenCode in issue #12/#13. You can:

1. Check out the existing TOTP components (`TOTPDisplay`, `TOTPReveal`)
2. Verify they work in the Password detail page
3. Add TOTP field support to Custom Asset forms if needed

Claim it:
```bash
./scripts/agent.sh claim 14 Kilo
```

Good luck! 🚀
