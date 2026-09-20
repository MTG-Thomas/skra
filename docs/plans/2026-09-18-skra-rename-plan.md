## Goal

Rename the fork and product from `bifrost-docs` / Bifrost Docs to `skra` / Skra (Old Norse *skrá*, "record, chronicle"), removing the collision with Bifrost Integrations and the `bifrost-api` lineage, with zero data loss and a clean rollback at each step.

## Success Criteria

- GitHub fork lives at `MTG-Thomas/skra`; old URL redirects.
- No `bifrost` reference (any case) remains in code, compose, k8s, CI, client branding, env prefix, images, or live docs — except git history, `docs/plans/*` history, `PLAN.md` history, and the one-release env compat shim.
- `skra` reserved/published on PyPI, npm, and GHCR (`ghcr.io/mtg-thomas/skra-api`, `skra-client`).
- `./test.sh` green, dev stack boots from scratch on new names, register → login → password reveal smoke passes.
- Existing installs have a documented data path (DB, S3 bucket) with backup-first rollback.

## Context And Current Facts

- Remotes: `origin` = `MTG-Thomas/bifrost-docs`, `upstream` = `jackmusick/bifrost-docs`; tree clean; `gh` available.
- Blast radius: 196 files reference `bifrost` (case-insensitive). Heaviest: `kubernetes/` (43), `api/` (37), `tools/` (28), `docs/` (26), `.github/` (16), `client/` (12), `scripts/` (9).
- Python import root is `src.*` (`api/src/main.py`), so renaming the PyPI distribution in `api/pyproject.toml` requires zero import changes. Literal `bifrost_docs` occurs in only 5 files (`api/src/config.py`, `routers/monitoring.py`, `routers/websocket.py`, `core/auth.py`, `core/security.py`).
- Settings: `api/src/config.py:25` uses `env_prefix="BIFROST_DOCS_"`. TOTP issuer default is `BifrostDocs` (display-only in otpauth URIs; changing it does not invalidate existing seeds). WebAuthn RP *name* is display-only; RP *ID* is hostname-based and unchanged.
- Images: dev compose uses `jackmusick/bifrost-docs-api`; prod uses `ghcr.io/mtg-thomas/bifrost-docs-api` and `-client`. DB user/name `bifrost_docs`, S3 bucket default `bifrost-docs`, compose project/volumes prefixed `bifrost-docs`/`bifrost_docs`.
- Migrator `tools/itglue-migrate` is its own `itglue_migrate` package; its `bifrost` hits are defaults/URLs, not imports.
- Name screening done this run: `skra` returns 404 on PyPI and Not Found on npm, with no official Docker Hub collision (see Sources).
- The rearchitecture workflow (org-scope → auth → queue → deploy → frontend) runs in parallel; this rename is mechanical and lands first so rearch phases build on final names.

## Constraints And Non-goals

- Git history, `docs/plans/*`, and `PLAN.md` historical references are frozen and stay as-is.
- Local workspace dir (`/root/bifrost-docs`) and GHCR org (`mtg-thomas`) do not change.
- No behavior, schema, or API changes — pure rename plus a thin env compat shim.
- No pushes, publishes, or repo renames without the approval gate below; each mutating unit states its rollback first.

## Key Decisions

- New identifiers: `skra` (code, DNS-safe, buckets, DB), display `Skra`, env prefix `SKRA_`. Rejected keeping `BIFROST_DOCS_` (defeats the rename) and `SKRA_DOCS_` (redundant; the product *is* the docs).
- One-release compat shim in `config.py` (read `BIFROST_DOCS_*` only when the `SKRA_*` counterpart is unset, log a deprecation warning), removed in the following release. Rejected hard cut (breaks existing operator `.env` files silently) and permanent dual support (forever-debt).
- Existing data stays in place: DB/S3/bucket contents are migrated by copy-then-verify, never rename-in-place without a backup. Fresh installs default to `skra` names.
- Dev image namespace aligns to `ghcr.io/mtg-thomas/skra-api` (matches prod; drops the stale `jackmusick` reference).

## Recommended Approach

Fork rename and name reservation first (external, redirect-safe), then code identifiers, then compose/env, then k8s/CI, then repo meta and migrator defaults, then data-path docs, then full validation. Mechanical, bottom-up, each unit independently revertible.

## Work Plan

- U1 Fork + reservations: rename fork `MTG-Thomas/bifrost-docs` → `MTG-Thomas/skra` (GitHub redirects old URL); update `origin` remote; screen USPTO TESS/EUIPO for `Skra` (software); reserve `skra` on PyPI/npm (placeholder or first publish); confirm Docker Hub/GHCR namespace. Rollback: GitHub rename is reversible within days; old URL redirects either way.
- U2 Code identifiers: `api/pyproject.toml` name/description → `skra`; `env_prefix="SKRA_"` + compat shim + warning; TOTP issuer → `Skra`; WebAuthn RP name → `Skra`; FastAPI title/branding strings; client `index.html` title, `Logo.tsx`, Setup/Dashboard copy. Rollback: `git revert` per commit.
- U3 Compose + env: project/container/volume names, DB defaults → `skra`, S3 bucket default → `skra`, image refs (dev + prod) → `ghcr.io/mtg-thomas/skra-api|client`, `.env.example` full `BIFROST_DOCS_` → `SKRA_` rewrite with mapping comment, `config/` hit verified. Validate with `docker compose config`. Rollback: revert + old `.env` still works via shim.
- U4 k8s + CI: namespace dir `multi-namespace/bifrost-docs` → `skra`, kustomizations, deployment image refs, ingress/TLS host verification, `.github/workflows/*` image refs, `sonar-project.properties`. Rollback: revert; old images remain pullable until cleanup.
- U5 Repo meta + migrator: `AGENTS.md`, `CLAUDE.md`, README/TODO references; `tools/itglue-migrate` defaults/URLs/package metadata verified and updated. Rollback: revert.
- U6 Data-path migration doc: Postgres (`ALTER DATABASE … RENAME` or dump/restore; backup first), S3 bucket mirror-then-verify (`mc mirror`), volume rename procedure. Rollback: point env back at old DB/bucket; nothing deleted until verified.
- U7 Validation: `./test.sh` full green; fresh `up --build -d`; register → login → password create/reveal; search/indexing smoke with AI unconfigured; `grep -ri bifrost` audit vs allowlist (history + shim + this plan).

## Validation Plan

- `grep -rli bifrost` (excluding `.git`, history docs, shim) returns empty — the primary evidence gate.
- `./test.sh` passes; `docker compose config` renders new names; fresh boot + user smoke passes; TOTP setup shows `Skra` issuer.
- Highest-risk step: U6 data copy on a real install — validated on a disposable compose stack with a database backup restored, never on the live volume first.

## Risks / Rollback

- Missed reference breaks boot: caught by `config` render + fresh-boot smoke; rollback per unit via revert.
- External publishes (GHCR tags, PyPI/npm) are hard to unpublish: mitigate by building locally first, pushing new names only, leaving old tags until U7 passes.
- Operator `.env` drift: shim + mapping comment cover it; removal tracked as follow-up issue, not silent.
- Sequencing with rearchitecture: rename merges first; rearch branches rebase onto it.

## Open Questions

None — repo discovery answered the material questions; remaining choices are recorded above as decisions with stated assumptions.

## Sources

- https://pypi.org/pypi/skra/json
- https://registry.npmjs.org/skra
- https://hub.docker.com/v2/search/repositories/?query=skra&page_size=1
- https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository
