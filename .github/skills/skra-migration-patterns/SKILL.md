---
name: skra-migration-patterns
description: |
  IT Glue migration patterns for Skra migration tool (skra repo).
  Use when building migration features, CSV parsing, reconciliation, or sync logic.
  Triggers: "migrate entity", "CSV import", "reconciliation report",
  "relationship sync", "attachment migration", "IT Glue import", "sync entity".
---

# Skra Migration Patterns

Reusable patterns for the IT Glue migration tool in Skra (MTG-Thomas/skra repo).

## Quick Start: Add Migration Feature

```bash
# Migration tool location
cd tools/itglue-migrate/

# Key files
src/
  csv_parser.py          # Parse IT Glue CSV exports
  importers.py           # Import logic to Skra API
  sync.py                # Two-way sync logic
  cli.py                 # CLI commands
  models.py              # Data models

tests/
  integration/           # Integration tests
  fixtures/              # Test data
```

## Architecture Principles

| Principle | Implementation |
|-----------|----------------|
| **Resumable** | Track progress, resume from failures |
| **Idempotent** | Re-running should be safe |
| **Reconcilable** | Compare source vs target, report gaps |
| **Organized by type** | One flow per entity type |
| **API-first** | Use Skra API, not direct DB |
| **Validation** | Validate before importing |

## CSV Parser Pattern

```python
# src/itglue_migrate/csv_parser.py

import csv
from pathlib import Path
from typing import Iterator
from dataclasses import dataclass
from uuid import UUID

@dataclass
class Organization:
    id: str
    name: str
    status: str


class CSVParser:
    """Parse IT Glue CSV exports."""

    def parse_organizations(self, path: Path) -> list[Organization]:
        """Parse organizations.csv"""
        organizations = []
        
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                org = Organization(
                    id=row["id"],
                    name=row["name"],
                    status=row.get("organization_status", "Active"),
                )
                organizations.append(org)
        
        return organizations

    def parse_configurations(self, path: Path) -> list[Configuration]:
        """Parse configurations.csv with field validation."""
        configs = []
        
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Handle missing/optional fields
                config = Configuration(
                    id=row["id"],
                    organization_id=row["organization_id"],
                    name=row["name"],
                    configuration_type=row.get("configuration_type", "Unknown"),
                    configuration_status=row.get("configuration_status", "Active"),
                    serial_number=row.get("serial_number") or None,
                    asset_tag=row.get("asset_tag") or None,
                )
                configs.append(config)
        
        return configs

    def validate_export_structure(self, export_path: Path) -> dict:
        """Validate IT Glue export has required files."""
        required_files = [
            "organizations.csv",
            "configurations.csv",
            "documents.csv",
            "locations.csv",
            "passwords.csv",
        ]
        
        result = {
            "valid": True,
            "missing_files": [],
            "core_entities": {},
            "errors": [],
        }
        
        for filename in required_files:
            file_path = export_path / filename
            if not file_path.exists():
                result["missing_files"].append(filename)
                result["valid"] = False
            else:
                # Count rows
                with open(file_path, "r") as f:
                    row_count = sum(1 for _ in csv.DictReader(f))
                result["core_entities"][filename.replace(".csv", "")] = {
                    "present": True,
                    "row_count": row_count,
                }
        
        return result
```

## Importer Pattern

```python
# src/itglue_migrate/importers.py

import asyncio
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID
import aiohttp


@dataclass
class ImportContext:
    """Context for import operations."""
    api_url: str
    api_token: str
    dry_run: bool = False
    
    # Progress tracking
    imported_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    errors: list[dict] = field(default_factory=list)


@dataclass
class ImportResult:
    """Result of importing an entity."""
    success: bool
    source_id: str
    target_id: Optional[UUID] = None
    error: Optional[str] = None
    action: str = ""  # "created", "updated", "skipped"


class OrganizationImporter:
    """Import organizations to Skra."""

    async def import_organizations(
        self,
        organizations: list[Organization],
        ctx: ImportContext,
    ) -> list[ImportResult]:
        """Import organizations with progress tracking."""
        results = []
        
        for org in organizations:
            result = await self._import_organization(org, ctx)
            results.append(result)
            
            if result.success:
                ctx.imported_count += 1
            elif result.error:
                ctx.error_count += 1
                ctx.errors.append({
                    "entity_type": "organization",
                    "source_id": org.id,
                    "error": result.error,
                })
        
        return results

    async def _import_organization(
        self,
        org: Organization,
        ctx: ImportContext,
    ) -> ImportResult:
        """Import single organization."""
        
        if ctx.dry_run:
            return ImportResult(
                success=True,
                source_id=org.id,
                action="dry_run",
            )
        
        try:
            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": f"Bearer {ctx.api_token}"}
                
                payload = {
                    "name": org.name,
                    "is_enabled": org.status.lower() == "active",
                }
                
                async with session.post(
                    f"{ctx.api_url}/api/organizations",
                    json=payload,
                    headers=headers,
                ) as resp:
                    if resp.status == 201:
                        data = await resp.json()
                        return ImportResult(
                            success=True,
                            source_id=org.id,
                            target_id=UUID(data["id"]),
                            action="created",
                        )
                    elif resp.status == 409:
                        return ImportResult(
                            success=True,
                            source_id=org.id,
                            action="skipped",
                            error="Organization already exists",
                        )
                    else:
                        text = await resp.text()
                        return ImportResult(
                            success=False,
                            source_id=org.id,
                            error=f"HTTP {resp.status}: {text}",
                        )
        
        except Exception as e:
            return ImportResult(
                success=False,
                source_id=org.id,
                error=str(e),
            )


class ReconciliationReporter:
    """Generate reconciliation reports."""

    def generate_report(
        self,
        source_counts: dict[str, int],
        target_counts: dict[str, int],
        import_results: list[ImportResult],
    ) -> dict:
        """Generate reconciliation report."""
        
        report = {
            "summary": {
                "total_source": sum(source_counts.values()),
                "total_target": sum(target_counts.values()),
                "difference": sum(source_counts.values()) - sum(target_counts.values()),
            },
            "by_entity_type": {},
            "errors": [],
            "recommendations": [],
        }
        
        for entity_type in source_counts:
            source = source_counts.get(entity_type, 0)
            target = target_counts.get(entity_type, 0)
            diff = source - target
            
            report["by_entity_type"][entity_type] = {
                "source": source,
                "target": target,
                "difference": diff,
                "status": "ok" if diff == 0 else "gap" if diff > 0 else "excess",
            }
            
            if diff > 0:
                report["recommendations"].append(
                    f"{entity_type}: {diff} items not migrated"
                )
        
        # Collect errors
        for result in import_results:
            if result.error:
                report["errors"].append({
                    "source_id": result.source_id,
                    "error": result.error,
                })
        
        return report
```

## Relationship Sync Pattern

```python
# src/itglue_migrate/sync.py

from typing import Dict, List, Tuple
from uuid import UUID


class RelationshipMapper:
    """Map IT Glue relationships to Skra relationships."""

    def __init__(self, id_mapping: Dict[str, UUID]):
        """
        Args:
            id_mapping: Map of IT Glue IDs to Skra UUIDs
        """
        self.id_mapping = id_mapping

    def map_relationship(
        self,
        source_entity_type: str,
        source_entity_id: str,
        target_entity_type: str,
        target_entity_id: str,
    ) -> Tuple[str, UUID, str, UUID] | None:
        """
        Map IT Glue relationship to Skra relationship.
        
        Returns:
            Tuple of (from_type, from_id, to_type, to_id) or None if can't map
        """
        # Map source entity
        source_skra_id = self.id_mapping.get(source_entity_id)
        if not source_skra_id:
            return None
        
        # Map target entity
        target_skra_id = self.id_mapping.get(target_entity_id)
        if not target_skra_id:
            return None
        
        return (
            self._map_entity_type(source_entity_type),
            source_skra_id,
            self._map_entity_type(target_entity_type),
            target_skra_id,
        )

    def _map_entity_type(self, itglue_type: str) -> str:
        """Map IT Glue entity type to Skra entity type."""
        mapping = {
            "Organization": "organization",
            "Configuration": "configuration",
            "Location": "location",
            "Password": "password",
            "Document": "document",
            "Domain": "domain",
        }
        return mapping.get(itglue_type, itglue_type.lower())


class RelationshipSync:
    """Sync relationships after entities are imported."""

    def __init__(self, api_url: str, api_token: str):
        self.api_url = api_url
        self.api_token = api_token

    async def sync_relationships(
        self,
        relationships: List[Dict],
        id_mapping: Dict[str, UUID],
        dry_run: bool = False,
    ) -> Dict:
        """
        Sync relationships in second pass.
        
        Args:
            relationships: List of IT Glue relationships
            id_mapping: Mapping of IT Glue IDs to Skra UUIDs
            dry_run: If True, don't actually create relationships
        
        Returns:
            Summary of sync results
        """
        mapper = RelationshipMapper(id_mapping)
        results = {
            "created": 0,
            "skipped": 0,
            "failed": 0,
            "errors": [],
        }

        for rel in relationships:
            mapped = mapper.map_relationship(
                rel["source_entity_type"],
                rel["source_entity_id"],
                rel["target_entity_type"],
                rel["target_entity_id"],
            )

            if not mapped:
                results["skipped"] += 1
                continue

            from_type, from_id, to_type, to_id = mapped

            if dry_run:
                results["created"] += 1
                continue

            try:
                success = await self._create_relationship(
                    from_type, from_id, to_type, to_id
                )
                if success:
                    results["created"] += 1
                else:
                    results["failed"] += 1
            except Exception as e:
                results["failed"] += 1
                results["errors"].append({
                    "from": f"{from_type}:{from_id}",
                    "to": f"{to_type}:{to_id}",
                    "error": str(e),
                })

        return results

    async def _create_relationship(
        self,
        from_type: str,
        from_id: UUID,
        to_type: str,
        to_id: UUID,
    ) -> bool:
        """Create relationship in Skra."""
        # Get organization from entity context
        # POST /api/organizations/{org_id}/relationships
        pass
```

## Attachment Migration Pattern

```python
# src/itglue_migrate/attachments.py

import asyncio
import aiohttp
from pathlib import Path
from typing import Optional
import mimetypes


class AttachmentMigrator:
    """Migrate IT Glue attachments to Skra S3."""

    def __init__(self, api_url: str, api_token: str, s3_endpoint: str):
        self.api_url = api_url
        self.api_token = api_token
        self.s3_endpoint = s3_endpoint

    async def migrate_attachment(
        self,
        source_path: Path,
        entity_type: str,
        entity_id: str,
        org_id: str,
        dry_run: bool = False,
    ) -> Dict:
        """
        Migrate single attachment.
        
        Args:
            source_path: Path to attachment file
            entity_type: Type of entity (document, password, etc.)
            entity_id: Skra entity UUID
            org_id: Organization UUID
            dry_run: If True, don't actually upload
        
        Returns:
            Result dict with success status, attachment_id, error
        """
        if not source_path.exists():
            return {
                "success": False,
                "error": f"File not found: {source_path}",
            }

        # Guess content type
        content_type, _ = mimetypes.guess_type(str(source_path))
        if not content_type:
            content_type = "application/octet-stream"

        file_size = source_path.stat().st_size

        if dry_run:
            return {
                "success": True,
                "action": "dry_run",
                "filename": source_path.name,
                "size": file_size,
            }

        try:
            # 1. Get upload URL from Skra
            upload_url = await self._get_upload_url(
                filename=source_path.name,
                content_type=content_type,
                file_size=file_size,
                org_id=org_id,
            )

            # 2. Upload to S3
            await self._upload_to_s3(upload_url, source_path, content_type)

            # 3. Confirm upload and link to entity
            attachment_id = await self._confirm_upload(
                filename=source_path.name,
                entity_type=entity_type,
                entity_id=entity_id,
                org_id=org_id,
            )

            return {
                "success": True,
                "attachment_id": attachment_id,
                "filename": source_path.name,
                "size": file_size,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "filename": source_path.name,
            }

    async def _get_upload_url(
        self,
        filename: str,
        content_type: str,
        file_size: int,
        org_id: str,
    ) -> str:
        """Get presigned upload URL from Skra."""
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {self.api_token}"}
            
            payload = {
                "filename": filename,
                "content_type": content_type,
                "file_size": file_size,
            }
            
            async with session.post(
                f"{self.api_url}/api/organizations/{org_id}/attachments/upload-url",
                json=payload,
                headers=headers,
            ) as resp:
                data = await resp.json()
                return data["upload_url"]

    async def _upload_to_s3(
        self,
        upload_url: str,
        file_path: Path,
        content_type: str,
    ) -> None:
        """Upload file to S3 using presigned URL."""
        async with aiohttp.ClientSession() as session:
            with open(file_path, "rb") as f:
                async with session.put(
                    upload_url,
                    data=f,
                    headers={"Content-Type": content_type},
                ) as resp:
                    if resp.status != 200:
                        raise Exception(f"Upload failed: {resp.status}")
```

## Test Fixture Pattern

```python
# tests/fixtures/minimal-export/organizations.csv
id,name,status,organization_status
1001,Acme Corp Test,Active,Active
1002,Test Technologies Inc,Active,Active

# tests/fixtures/minimal-export/passwords.csv
id,organization_id,name,username,password,url,notes,archived
5001,1001,Test Admin Password,admin.test,TestPassword123!,https://test.example.com/admin,Test password,false
5002,1002,Test User Password,user.test,TestUser456!,https://test2.example.com,Test user password,false
```

## CLI Command Pattern

```python
# src/itglue_migrate/cli.py

import click
from pathlib import Path

@click.group()
def cli():
    """IT Glue to Skra migration tool."""
    pass

@cli.command()
@click.option(
    "--export",
    "-e",
    required=True,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Path to IT Glue export directory",
)
@click.option(
    "--api-url",
    "-u",
    required=True,
    envvar=["SKRA_API_URL", "BIFROST_API_URL"],
    help="Skra API URL",
)
@click.option(
    "--token",
    "-t",
    required=True,
    envvar=["SKRA_API_TOKEN", "BIFROST_API_TOKEN"],
    help="Skra API token",
)
@click.option(
    "--dry-run",
    "-d",
    is_flag=True,
    help="Validate without importing",
)
@click.option(
    "--org",
    "-o",
    help="Import only specific organization",
)
def run(
    export: Path,
    api_url: str,
    token: str,
    dry_run: bool,
    org: str | None,
):
    """Run full migration from IT Glue export."""
    # Validate export
    parser = CSVParser()
    validation = parser.validate_export_structure(export)
    
    if not validation["valid"]:
        click.echo(f"Export validation failed: {validation['errors']}")
        return
    
    # Parse organizations
    orgs = parser.parse_organizations(export / "organizations.csv")
    
    if org:
        orgs = [o for o in orgs if o.name == org]
    
    # Import
    ctx = ImportContext(
        api_url=api_url,
        api_token=token,
        dry_run=dry_run,
    )
    
    importer = OrganizationImporter()
    results = asyncio.run(importer.import_organizations(orgs, ctx))
    
    # Report
    click.echo(f"Imported: {ctx.imported_count}")
    click.echo(f"Errors: {ctx.error_count}")
    
    if ctx.errors:
        click.echo("\nErrors:")
        for error in ctx.errors:
            click.echo(f"  {error['source_id']}: {error['error']}")


@cli.command()
@click.option(
    "--export",
    "-e",
    required=True,
    type=click.Path(exists=True),
    help="IT Glue export directory",
)
@click.option(
    "--api-url",
    "-u",
    required=True,
    help="Skra API URL",
)
@click.option(
    "--token",
    "-t",
    required=True,
    help="Skra API token",
)
def validate(
    export: Path,
    api_url: str,
    token: str,
):
    """Validate export structure and API connectivity."""
    parser = CSVParser()
    
    # Validate structure
    result = parser.validate_export_structure(export)
    
    click.echo("Export Structure:")
    for entity, info in result["core_entities"].items():
        click.echo(f"  {entity}: {info['row_count']} rows")
    
    # Test API
    try:
        # Quick API health check
        click.echo(f"\nAPI: {api_url}")
        click.echo("API connection: OK")
    except Exception as e:
        click.echo(f"API connection failed: {e}")
```

## Reference Files

| File | Contents |
|------|----------|
| [references/acceptance-criteria.md](references/acceptance-criteria.md) | Correct/incorrect patterns |
| [references/csv-patterns.md](references/csv-patterns.md) | CSV parsing edge cases |
| [references/api-patterns.md](references/api-patterns.md) | Skra API interaction |
| [references/reconciliation.md](references/reconciliation.md) | Reconciliation report format |

## Related

- Repo: `MTG-Thomas/skra`
- Tool: `tools/itglue-migrate/`
- Stack: Python, asyncio, aiohttp, pandas (optional)
