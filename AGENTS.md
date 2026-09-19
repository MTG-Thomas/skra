# Skra — Agent Context

Open-source MSP documentation platform. FOSS alternative to IT Glue / Hudu.
Managed services providers use it to document client environments (passwords, configs, locations, documents, custom assets).

## Stack

| Layer | Tech |
|---|---|
| API | FastAPI + async SQLAlchemy + PostgreSQL (pgvector) |
| Queue | RabbitMQ (search indexing, exports) |
| Cache | Redis (WebSocket pub/sub, caching) |
| Storage | S3 / MinIO (attachments, embedded images, exports) |
| Frontend | Vite + React + TypeScript + shadcn/ui + TailwindCSS |
| Auth | JWT sessions + WebAuthn passkeys + MFA + OIDC/OAuth SSO |
| Search | pgvector (semantic) + PostgreSQL ILIKE (text) + OpenAI embeddings |

## Directory Layout

```text
skra/
├── api/
│   ├── src/
│   │   ├── core/          # config.py, database.py, auth.py, pubsub.py, security.py
│   │   ├── models/
│   │   │   ├── orm/       # SQLAlchemy models
│   │   │   └── contracts/ # Pydantic request/response schemas
│   │   ├── repositories/  # data access layer (org-scoped by default)
│   │   ├── services/      # business logic (encryption, embeddings, file storage, etc.)
│   │   └── routers/       # FastAPI route handlers
│   ├── alembic/           # DB migrations
│   └── tests/
│       ├── unit/
│       └── integration/
├── client/
│   └── src/
│       ├── components/    # shared UI components (shadcn + custom)
│       ├── hooks/         # React Query hooks per entity
│       ├── pages/         # route-level page components
│       ├── services/      # API client, websocket service
│       └── stores/        # Zustand (auth store)
├── tools/
│   └── itglue-migrate/    # CLI tool for migrating from IT Glue
├── docs/
│   └── plans/             # design docs and implementation plans (historical)
├── docker-compose.yml
├── docker-compose.dev.yml
└── PLAN.md                # full implementation history (Phases 1–22 complete)
```

## Running Locally

```bash
# Start full dev stack (always use both files)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# Rebuild after code changes outside of hot-reload volumes
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d

# Follow logs
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f api

# Run tests
./test.sh

# Run a specific test
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm api pytest tests/integration/test_auth.py -v
```

**Ports:** Frontend → http://localhost:8080 | Postgres → localhost:5433 | Garage S3 → localhost:3900 | Garage admin → localhost:3903 | Valkey → localhost:6379

### First-time bootstrap

1. Copy `.env.example` to `.env` and fill in required vars — dev defaults are already committed to `.env`, do not commit production secrets
2. `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d`
3. The `init` container runs Alembic migrations automatically on every startup
4. The `garage-init` container configures Garage (layout, bucket, S3 key) — runs once and exits
5. Register the first user at http://localhost:8080 — first user is automatically assigned `owner` role

### Garage (S3 storage) notes

- Config: `config/garage.toml` — contains a dev `admin_token` and `rpc_secret`; replace both in production
- Init script: `scripts/garage-init.sh` — uses the Garage admin HTTP API (port 3903) via `alpine:3` with `wget`
- Garage image is scratch-based (no shell) — healthcheck uses `/garage status` (RPC), admin API calls go through the init container
- `GARAGE_ADMIN_TOKEN` must match `admin_token` in `config/garage.toml`
- Layout API (v1.3.1) requires `tags: []` in the role assignment body — omitting it causes a 400

### WSL2 gotcha

If you see `error getting credentials - err: fork/exec /usr/bin/docker-credential-desktop.exe`, clear the credential store:

```bash
echo '{}' > ~/.docker/config.json
```

Then retry. Docker Desktop WSL2 integration sets `credsStore: desktop.exe` which doesn't work from inside WSL.

Bind mount restarts also fail in WSL2 — always use full `down` + `up` rather than `restart` for containers with file mounts.

## Key Conventions

### API

- All data endpoints are **org-scoped**: `/api/organizations/{org_id}/passwords`, etc.
- Global (cross-org) variants live under `/api/global/*` and include `organization_name` in responses.
- List endpoints return `{items: [...], total: int, limit: int, offset: int}` with `search`, `sort_by`, `sort_dir`, `limit`, `offset` query params.
- Role enforcement via `require_role(min_role: UserRole)` dependency. Roles: `owner > administrator > contributor > reader`.
- Secrets (passwords, TOTP, OAuth keys, API keys) are encrypted with Fernet before storage. Never expose `*_encrypted` fields in public contracts.
- Types (ConfigurationType, ConfigurationStatus, CustomAssetType) are **global** (not per-org). Read: any authenticated user. Write: administrators+.

### Models

- ORM models in `api/src/models/orm/`, Pydantic contracts in `api/src/models/contracts/`.
- Pydantic convention: `*Create`, `*Update`, `*Public` — Public never exposes encrypted fields.
- Migrations live in `api/alembic/versions/`, named `YYYYMMDD_NNNNNN_description.py`.

### Frontend

- TanStack Query for all server state. Hooks live in `client/src/hooks/use{Entity}.ts`.
- Zustand auth store: `client/src/stores/authStore.ts` — exposes `isAdmin()`, `isOwner()`.
- `usePermissions()` hook for `canEdit`, `canAccessSettings`, `canManageOwners`.
- DataTable component in `client/src/components/ui/data-table.tsx` — supports sorting, pagination, column visibility, column pinning, filter popovers.
- Column preferences persisted per-user via `GET/PUT /api/preferences/{entity_type}`.
- WebSocket service in `client/src/services/websocket.ts` — used for streaming AI responses and reindex/export progress.

### Custom Assets

- Schema defined via `CustomAssetType.fields` (JSONB array of `FieldDefinition`).
- Field types: `text`, `textbox`, `number`, `date`, `checkbox`, `select`, `header`, `password`.
- Password-type fields are encrypted with `_encrypted` suffix in the values JSONB.
- Reveal endpoint: `GET /api/organizations/{org_id}/custom-asset-types/{type_id}/assets/{id}/reveal`.

## Open Work

See GitHub Issues on this repo. Key areas:
- **Phase 23**: OTP/TOTP support for passwords and custom assets
- **Polish**: Table height, Show Disabled UX, input contrast on grey cards, notes HTML in tables
- **Testing**: E2E suite, cross-browser, mobile responsiveness
- **API docs**: Document endpoints for migration script authors

## Agent Workflow

This repo uses multi-agent development with OpenCode and Kilo. See:
- [`docs/AGENTS.md`](docs/AGENTS.md) — Full workflow documentation
- [`.github/ISSUE_TEMPLATE/agent_task.md`](.github/ISSUE_TEMPLATE/agent_task.md) — Issue template
- `scripts/agent.sh` — Helper script for issue management

**Quick start for agents:**
```bash
# See available work
./scripts/agent.sh next

# Claim an issue
./scripts/agent.sh claim 12

# Mark as done
./scripts/agent.sh done 12
```

## Reference

- `upstream`: `jackmusick/bifrost-docs` (FOSS origin)
- `origin`: `MTG-Thomas/skra` (our fork, renamed from `bifrost-docs`)
- Design docs and implementation notes: `docs/plans/`

## GitHub Tokens

- **General API / issues / PRs:** `github/token` (fine-grained PAT via `pass`)
- **Projects v2 (kanban board):** `bifrost/workspace-github-pat` (classic PAT via `pass`) — required because fine-grained tokens cannot access the Projects v2 GraphQL API
  ```bash
  GH_TOKEN=$(pass show bifrost/workspace-github-pat) gh project ...
  ```
