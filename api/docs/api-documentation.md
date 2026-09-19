# Skra API Documentation

## Overview

This document describes the Skra API endpoints, with a focus on the `is_enabled` field and `show_disabled` parameter functionality.

## `is_enabled` Field

### Description

The `is_enabled` field is a boolean field that indicates whether an entity is active/enabled or disabled. When `is_enabled=False`, the entity is considered disabled and is excluded from default API responses.

### Entities with `is_enabled`

The following entities support the `is_enabled` field:

- Organizations
- Locations
- Configurations
- Custom Assets
- Documents
- Passwords

### Default Behavior

- **Creating entities**: If `is_enabled` is not specified during creation, it defaults to `True` (enabled)
- **Listing entities**: By default, only enabled entities (`is_enabled=True`) are returned
- **Updating entities**: The `is_enabled` field can be updated via PATCH/PUT requests

## `show_disabled` Query Parameter

### Description

The `show_disabled` query parameter controls whether disabled entities are included in list and search responses.

### Behavior

- **`show_disabled=false` (default)**: Only returns enabled entities (`is_enabled=True`)
- **`show_disabled=true`**: Returns all entities regardless of `is_enabled` status

### Supported Endpoints

The `show_disabled` parameter is supported on the following list endpoints:

#### Organizations
```
GET /api/organizations?show_disabled=true
```

#### Locations
```
GET /api/organizations/{org_id}/locations?show_disabled=true
```

#### Configurations
```
GET /api/organizations/{org_id}/configurations?show_disabled=true
```

#### Custom Assets
```
GET /api/organizations/{org_id}/custom-assets?show_disabled=true
```

#### Documents
```
GET /api/organizations/{org_id}/documents?show_disabled=true
```

#### Passwords
```
GET /api/organizations/{org_id}/passwords?show_disabled=true
```

### Search Endpoint

The search endpoint also supports the `show_disabled` parameter:

```
GET /api/organizations/{org_id}/search?q={query}&show_disabled=true
```

When `show_disabled=true`, search results include disabled entities across all types (configurations, custom assets, documents, passwords, locations).

## Examples

### List only enabled configurations (default)
```http
GET /api/organizations/{org_id}/configurations
```
```http
GET /api/organizations/{org_id}/configurations?show_disabled=false
```

### List all configurations including disabled
```http
GET /api/organizations/{org_id}/configurations?show_disabled=true
```

### Search across all entities (enabled only)
```http
GET /api/organizations/{org_id}/search?q=server
```

### Search across all entities including disabled
```http
GET /api/organizations/{org_id}/search?q=server&show_disabled=true
```

### Create a disabled configuration
```http
POST /api/organizations/{org_id}/configurations
Content-Type: application/json

{
  "name": "Old Server",
  "configuration_type_id": "...",
  "is_enabled": false
}
```

### Disable an existing configuration
```http
PATCH /api/organizations/{org_id}/configurations/{config_id}
Content-Type: application/json

{
  "is_enabled": false
}
```

## Migration from IT Glue

When importing data from IT Glue, the following mappings are used:

### Configurations & Custom Assets
- IT Glue `archived` field → `is_enabled`
  - `archived="Yes"` → `is_enabled=False`
  - `archived="No"` or missing → `is_enabled=True`

### Organizations
- IT Glue `organization_status` field → `is_enabled`
  - `organization_status="Active"` → `is_enabled=True`
  - Any other status → `is_enabled=False`

## Implementation Details

### Backend (Python/FastAPI)

- **Field Definition**: `is_enabled` is defined as a nullable boolean column in database models
- **Repository Layer**: Repository methods support an optional `is_enabled` filter parameter
- **Router Layer**: Endpoints extract `show_disabled` from query params and convert to appropriate filter

### Frontend (TypeScript/React)

- **Type Definitions**: All entity types include `is_enabled?: boolean` field
- **API Client**: API calls support `show_disabled` parameter for list/search operations
- **UI Components**: Components show disabled entities with visual indicators when `show_disabled=true`

## Database Schema

### Example: Configurations Table

```sql
CREATE TABLE configurations (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    name VARCHAR(255) NOT NULL,
    configuration_type_id UUID,
    is_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- ... other fields
);
```

### Indexing

For optimal performance, indexes should be created on the `is_enabled` field:

```sql
CREATE INDEX idx_configurations_is_enabled ON configurations(is_enabled);
CREATE INDEX idx_configurations_org_enabled ON configurations(organization_id, is_enabled);
```

## Security Considerations

- **Row-Level Security (RLS)**: The `is_enabled` filter is applied AFTER RLS policies, ensuring users can only see entities they have access to
- **No Data Loss**: Disabling an entity does not delete it; all data is preserved
- **Audit Trail**: Changes to `is_enabled` are tracked in audit logs

## Future Enhancements

Potential future features:

1. **Bulk Toggle Endpoints**: Enable/disable multiple entities at once
   - `POST /api/organizations/{org_id}/configurations/bulk-enable`
   - `POST /api/organizations/{org_id}/configurations/bulk-disable`

2. **Scheduled Disable**: Configure entities to automatically disable at a future date

3. **Disable Reason**: Add a optional text field to document why an entity was disabled

4. **Soft Delete**: Use `is_enabled=False` as a soft delete mechanism with retention policies

## Related Documentation

- [IT Glue Migration Guide](../plans/MIGRATION_TOOL.md)
- [Database Schema](../database/README.md)
- [API Authentication](../docs/authentication.md)

---

# Migration Author's Guide

> **For IT Glue Migration and External Integration Authors**

This section provides practical guidance for writing migration scripts and external tools.

## Quick Start

### Interactive API Documentation

FastAPI automatically generates interactive docs at these endpoints:

- **Swagger UI:** `GET /docs` — Interactive testing interface
- **OpenAPI JSON:** `GET /openapi.json` — Machine-readable spec
- **ReDoc:** `GET /redoc` — Alternative documentation UI

Visit `/docs` in your browser to explore and test endpoints interactively.

### Authentication for Scripts

Use API keys for migration scripts:

1. **Create an API key** via the web UI (Settings → API Keys)
2. **Include in requests** via the `X-API-Key` header:

```bash
curl -H "X-API-Key: your-api-key-here" \
  https://api.example.com/api/organizations/{org_id}/passwords
```

## Pagination Pattern

All list endpoints use consistent pagination:

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | 100 | Results per page (max 1000) |
| `offset` | integer | 0 | Skip this many results |
| `search` | string | - | Text search filter |
| `sort_by` | string | varies | Sort column |
| `sort_dir` | `asc`/`desc` | `asc` | Sort direction |

### Response Format

```json
{
  "items": [...],
  "total": 256,
  "limit": 100,
  "offset": 0
}
```

### Python: Iterate All Pages

```python
def get_all_items(org_id, endpoint):
    items = []
    offset = 0
    limit = 100
    
    while True:
        response = requests.get(
            f"{BASE_URL}/api/organizations/{org_id}/{endpoint}",
            headers={"X-API-Key": API_KEY},
            params={"limit": limit, "offset": offset}
        )
        data = response.json()
        items.extend(data["items"])
        
        if len(data["items"]) < limit:
            break
        offset += limit
    
    return items
```

## Entity Patterns

### Passwords

**Write-only fields:** `password` and `totp_secret` are never returned in responses.

**Reveal endpoint:**
```bash
GET /api/organizations/{org_id}/passwords/{id}/reveal
```

**Check for TOTP:**
```json
{
  "name": "Example",
  "has_totp": true  // Indicates TOTP is configured
}
```

### Configurations

**Column filters:** Support `type_id` and `status_id` filters:
```bash
GET /api/organizations/{org_id}/configurations?type_id=...&status_id=...
```

**Global types/statuses:**
```bash
GET /api/configuration-types      # Shared across orgs
GET /api/configuration-statuses   # Shared across orgs
```

### Custom Assets

**Dynamic values:** Values are keyed by field key:
```json
{
  "name": "Asset Name",
  "values": {
    "serial_number": "ABC123",
    "purchase_date": "2024-01-15"
  }
}
```

**Encrypted fields:** Password and TOTP fields are automatically encrypted.

**Reveal secrets:**
```bash
GET /api/organizations/{org_id}/custom-asset-types/{type_id}/assets/{id}/reveal
```

### Documents

**Content format:** HTML stored in `content` field.

**Image uploads:**
```bash
POST /api/organizations/{org_id}/documents/{id}/attachments
Content-Type: multipart/form-data
```

### Locations

**Structured address:**
```json
{
  "name": "Main Office",
  "address_1": "123 Main St",
  "address_2": "Suite 100",
  "city": "New York",
  "region": "NY",
  "postal_code": "10001",
  "country": "US"
}
```

### Relationships

Link any two entities:
```json
{
  "source_type": "password",
  "source_id": "uuid-1",
  "target_type": "configuration",
  "target_id": "uuid-2",
  "relation_type": "belongs_to"
}
```

Relation types: `belongs_to`, `connected_to`, `depends_on`, `runs_on`, `installed_on`, `located_at`, `manages`, `parent_of`, `related_to`.

## Migration Patterns

### Store External IDs

Preserve original IDs in metadata:
```json
{
  "name": "Imported Item",
  "metadata": {
    "external_id": "12345",
    "source_system": "itglue",
    "imported_at": "2024-01-15T10:30:00Z"
  }
}
```

### Bulk Import

Use parallel requests for speed:
```python
from concurrent.futures import ThreadPoolExecutor

def create_password(data):
    response = requests.post(
        f"{BASE_URL}/api/organizations/{org_id}/passwords",
        headers={"X-API-Key": API_KEY},
        json=data
    )
    response.raise_for_status()
    return response.json()

with ThreadPoolExecutor(max_workers=5) as executor:
    results = list(executor.map(create_password, passwords_to_import))
```

### Disable Search Indexing During Import

For large imports:
1. Disable indexing in Settings
2. Run bulk import
3. Re-enable indexing

## Migration-Specific API Endpoints

### Bulk Operations

Enable/disable multiple entities:
```bash
POST /api/organizations/{org_id}/{entity}/batch-toggle
{
  "ids": ["uuid-1", "uuid-2"],
  "is_enabled": false
}
```

Supported entities: passwords, configurations, locations, custom-assets, documents

### Global View

Search across all organizations (cross-org access):
```bash
GET /api/global/{entity}?search=...
```

Entities: configurations, passwords, documents, locations

## Error Handling

### HTTP Status Codes

| Code | Meaning | Action |
|------|---------|--------|
| 200 | Success | Continue |
| 201 | Created | Entity created successfully |
| 400 | Bad Request | Check request format |
| 401 | Unauthorized | Check API key |
| 403 | Forbidden | Insufficient permissions |
| 404 | Not Found | Entity doesn't exist |
| 422 | Validation Error | Check field constraints |
| 500 | Server Error | Retry with backoff |

### Validation Errors

```json
{
  "detail": [
    {
      "loc": ["body", "name"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

## API Quick Reference

| Entity | Base Path | Contracts |
|--------|-----------|-----------|
| Passwords | `/api/organizations/{org_id}/passwords` | `password.py` |
| Configurations | `/api/organizations/{org_id}/configurations` | `configuration.py` |
| Locations | `/api/organizations/{org_id}/locations` | `location.py` |
| Documents | `/api/organizations/{org_id}/documents` | `document.py` |
| Custom Assets | `/api/organizations/{org_id}/custom-asset-types/{type_id}/assets` | `custom_asset.py` |
| Relationships | `/api/organizations/{org_id}/relationships` | `relationship.py` |

## Example Migration Script

See `tools/itglue-migrate/` for production migration code. Key patterns:

1. **Batch operations** with retry logic
2. **Progress tracking** with resume capability
3. **Error handling** with detailed logging
4. **Rate limiting** with concurrency control

---

*Last updated: 2026-04-03*
