# Skra

MSP documentation application: FastAPI/async SQLAlchemy/PostgreSQL backend in `api/`, React/Vite UI in `client/`, IT Glue migration tooling in `tools/itglue-migrate/`. For local startup read [local setup](docs/agent-guidance.md#running-locally); API/contracts/migrations use [API and model conventions](docs/agent-guidance.md#key-conventions); UI uses [frontend conventions](docs/agent-guidance.md#frontend); storage uses [Garage notes](docs/agent-guidance.md#garage-s3-storage-notes). Load applicable sections only; planning context is in `docs/plans/`. This fork's origin is `MTG-Thomas/skra`; preserve upstream ancestry and conventions.

## Verification and local setup

Backend: `./test.sh` runs the isolated `docker-compose.test.yml` stack; `./test.sh tests/unit/ -v` narrows it. The runner exports logs to `/tmp/skra` and tears down its test volumes, so avoid sharing its project/test environment with other work.

In `client/`: `npm ci`, `npm run lint`, `npm test`, `npm run build`. Follow the relevant Playwright configuration for `npm run test:e2e` when changing user flows. For development use both compose files: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`. Bootstrap applies migrations and initializes storage; use a disposable local environment. Never blindly overwrite Docker credential configuration to work around WSL problems.

## Invariants

Data endpoints remain org-scoped; cross-org variants are explicit `/api/global/*` endpoints. Enforce `owner > administrator > contributor > reader` server-side; global type writes require administrators. Preserve list pagination/search/sort contracts.

Encrypt passwords/TOTP/OAuth/API secrets before storage. Public schemas never expose `*_encrypted` fields. Password custom fields retain their encryption/reveal boundary. Preserve `*Create`, `*Update`, `*Public` contracts and dated Alembic migrations.

Use TanStack Query for server state, existing auth/permission hooks for UI gating, and established DataTable/WebSocket conventions. Database/storage/authentication changes need corresponding integration evidence; local UI permission checks are insufficient.

Documentation work follows [docs/AGENTS.md](docs/AGENTS.md). Track existing issue context when applicable; use isolated branches/worktrees and request-authorized communication rather than named-agent labels or shared-branch handoffs. Obtain GitHub authentication through the available approved environment; never read or print pass-store token contents. Test logs and migration inputs can contain customer data and need careful handling.
