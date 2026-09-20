# Azure + Neon Proof Deployment

This runbook stands up Skra with Azure hosting the app/platform services and Neon hosting Postgres.

## Architecture

- Azure Resource Group: `rg-skra-neon-dev`
- Azure Container Apps: FastAPI API from the pinned GHCR image
- Azure Container Apps Job: one-shot `scripts.init_container` migrations/default setup
- Azure Storage:
  - Static website hosting for the React build
  - Private `attachments` container for attachment/export blobs
  - Private `backups` container for DB exports
- Azure Key Vault: proof secrets copied at deployment time
- Log Analytics + Application Insights: API logs and basic telemetry
- Neon Free: Postgres with `pgvector`

The first proof intentionally defers Redis-backed ARQ workers and WebSocket fanout. Text search and core CRUD flows can be validated first; semantic indexing can be enabled after the core Azure/Neon path is healthy.

## Prerequisites

- Azure CLI authenticated to the Azure Sponsorship subscription.
- Neon project created with a database/user for Skra.
- Neon direct/sync connection string: `postgresql://...`
- Neon async connection string: `postgresql+asyncpg://...`
- PostgreSQL client tools available locally if restoring a dump from this workstation.
- Latest CI image available in GHCR, for example `ghcr.io/mtg-thomas/skra-api:<short-sha>`.

Enable pgvector in Neon:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

## Export The Current Dev VM Database

```powershell
.\scripts\export-dev-vm-db.ps1
```

The script writes a custom-format dump and row-count stats under:

```text
.migration-runs/azure-neon-proof/<timestamp>/
```

The current dev VM DB was measured at about 15 MB, so it fits comfortably in Neon Free.

## Restore Into Neon

```powershell
.\scripts\restore-neon-db.ps1 `
  -DumpPath ".migration-runs\azure-neon-proof\<timestamp>\skra-dev.dump" `
  -DatabaseUrlSync "postgresql://USER:PASSWORD@HOST/DB?sslmode=verify-full"
```

After restore, run the same smoke SQL against Neon:

```sql
SELECT pg_size_pretty(pg_database_size(current_database())) AS database_size;
SELECT 'organizations' AS table_name, COUNT(*) AS row_count FROM organizations
UNION ALL SELECT 'documents', COUNT(*) FROM documents
UNION ALL SELECT 'attachments', COUNT(*) FROM attachments
UNION ALL SELECT 'passwords', COUNT(*) FROM passwords
UNION ALL SELECT 'relationships', COUNT(*) FROM relationships
UNION ALL SELECT 'embedding_index', COUNT(*) FROM embedding_index
ORDER BY table_name;
```

## Deploy Azure Proof Resources

```powershell
.\scripts\deploy-azure-neon-proof.ps1 `
  -SubscriptionName "Azure Sponsorship" `
  -ResourceGroupName "rg-skra-neon-dev" `
  -Location "eastus" `
  -EnvironmentName "neon-dev" `
  -ApiImage "ghcr.io/mtg-thomas/skra-api:<short-sha>" `
  -DatabaseUrl "postgresql+asyncpg://USER:PASSWORD@HOST/DB?sslmode=verify-full" `
  -DatabaseUrlSync "postgresql://USER:PASSWORD@HOST/DB?sslmode=verify-full"
```

The script:

- creates/updates the Azure resource group;
- deploys `infra/azure-neon/main.bicep`;
- runs the Container Apps migration/init job;
- builds the frontend with `VITE_API_URL` set to the API URL;
- uploads `client/dist` to Azure Storage static website hosting;
- updates API CORS and WebAuthn origin to the static website URL.

## Runtime Configuration

The API uses:

- `SKRA_STORAGE_BACKEND=azure_blob`
- `SKRA_AZURE_STORAGE_ACCOUNT_URL=<storage blob endpoint>`
- `SKRA_AZURE_STORAGE_ACCOUNT_KEY=<generated account key>`
- `SKRA_AZURE_BLOB_CONTAINER=attachments`

The attachment table and API contracts still use the existing `s3_key` field name. Treat it as an object key, not as proof the backing store is S3.

## GitHub Actions Proof Deploy

Manual `CI - Test & Build` workflow runs build and push the GHCR images, deploy the proof Static Web Apps frontend, and update the Azure Container Apps API to the same short-SHA image tag.

The API deploy uses GitHub Actions OIDC instead of a stored Azure client secret. The Entra app registration must have a federated credential with:

```json
{
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:MTG-Thomas/skra:environment:azure-neon-proof",
  "audiences": ["api://AzureADTokenExchange"]
}
```

The app also needs permission to update:

```text
/subscriptions/a1d63b24-1202-4bfa-9086-cf32d1d352fc/resourceGroups/rg-skra-neon-dev/providers/Microsoft.App/containerApps/ca-skra-api-neon-dev
```

## Validation

Check API health:

```powershell
Invoke-RestMethod "https://<api-fqdn>/health"
```

Then validate from the browser:

- login/setup works;
- organizations load;
- documents load;
- passwords/configurations pages load;
- attachment upload/download works against Azure Blob;
- text search works.

Optional semantic search validation:

- configure an embeddings API key;
- run reindex;
- verify `embedding_index` row count and size remain below the expected proof envelope.

## Known Proof Limits

- The ARQ worker and Redis pub/sub path are not converted in this first slice.
- WebSocket/reindex progress may need a later Azure Web PubSub or polling pass.
- Neon Free is appropriate for proof/staging, not production cutover.
- The API uses an Azure Storage account key for SAS generation in this proof. Managed identity/user delegation SAS can replace this later.
