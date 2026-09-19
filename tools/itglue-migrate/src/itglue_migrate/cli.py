"""CLI module for IT Glue to BifrostDocs migration tool.

This module provides the command-line interface using Typer with two main commands:
- preview: Scan export and generate a migration plan file
- run: Execute migration using a plan file
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TextColumn
from rich.table import Table

from itglue_migrate.api_client import APIError, BifrostDocsClient
from itglue_migrate.attachments import AttachmentScanner, validate_attachments
from itglue_migrate.csv_parser import CSVParser, CSVParserError, slugify_to_display_name
from itglue_migrate.document_processor import DocumentProcessor
from itglue_migrate.field_inference import FieldInferrer, column_name_to_key
from itglue_migrate.importers import map_archived_to_is_enabled
from itglue_migrate.org_matcher import OrgMatcher
from itglue_migrate.password_field_mapper import PasswordFieldMap, build_password_field_map
from itglue_migrate.progress import Phase, create_progress_reporter
from itglue_migrate.reconciliation import (
    OrganizationReconciliation,
    ReconciliationReport,
    apply_result_counts,
    build_plan_counts,
)
from itglue_migrate.state import MigrationState, MigrationStateError
from itglue_migrate.state_fetcher import ExistingState, StateFetcher
from itglue_migrate.sync_differ import EntityPlan, SyncDiffer, SyncPlan
from itglue_migrate.sync_executor import SyncExecutor, SyncResult
from itglue_migrate.verification import (
    BROKEN_EMBEDDED_IMAGE,
    MISSING_UPLOAD,
    MigratedAttachment,
    collect_embedded_image_references,
    extract_markdown_image_urls,
    reconcile_migrated_attachments,
    verify_embedded_images,
    verify_migrated_document_images,
)
from itglue_migrate.warnings import ParsedData, Warning, WarningDetector, summarize

# Create Typer app
app = typer.Typer(
    name="itglue-migrate",
    help="IT Glue to BifrostDocs Migration Tool",
    no_args_is_help=True,
)

# Rich console for output
console = Console()
error_console = Console(stderr=True)

# Plan file version for compatibility checking
PLAN_VERSION = 1

# Logger for this module
logger = logging.getLogger(__name__)


def _validate_export_path(export_path: Path) -> dict[str, Any]:
    """Validate the export path exists and has expected structure.

    Args:
        export_path: Path to the IT Glue export directory.

    Returns:
        Validation result from CSVParser.

    Raises:
        typer.Exit: If validation fails critically.
    """
    if not export_path.exists():
        error_console.print(f"[red]Error:[/red] Export path does not exist: {export_path}")
        raise typer.Exit(1)

    if not export_path.is_dir():
        error_console.print(f"[red]Error:[/red] Export path is not a directory: {export_path}")
        raise typer.Exit(1)

    parser = CSVParser()
    try:
        validation = parser.validate_export_structure(export_path)
    except CSVParserError as e:
        error_console.print(f"[red]Error:[/red] Failed to validate export: {e}")
        raise typer.Exit(1) from None

    if not validation["valid"]:
        error_console.print("[red]Error:[/red] Invalid export structure")
        for error in validation.get("errors", []):
            error_console.print(f"  - {error}")
        raise typer.Exit(1)

    return validation


async def _fetch_existing_organizations(
    api_url: str,
    token: str,
) -> list[dict[str, Any]]:
    """Fetch existing organizations from the BifrostDocs API.

    Args:
        api_url: Base URL of the BifrostDocs API.
        token: API authentication token.

    Returns:
        List of existing organization dictionaries.

    Raises:
        typer.Exit: If API request fails.
    """
    try:
        async with BifrostDocsClient(base_url=api_url, api_key=token) as client:
            return await client.list_organizations()
    except APIError as e:
        error_console.print(f"[red]Error:[/red] Failed to fetch organizations: {e}")
        raise typer.Exit(1) from None


def _parse_all_csv_files(
    parser: CSVParser,
    export_path: Path,
    validation: dict[str, Any],
    progress: Progress,
    task_id: TaskID,
) -> ParsedData:
    """Parse all CSV files from the export directory.

    Args:
        parser: CSVParser instance.
        export_path: Path to the export directory.
        validation: Validation result with entity info.
        progress: Rich progress instance.
        task_id: Progress task ID.

    Returns:
        ParsedData container with all parsed entities.
    """
    parsed = ParsedData()
    core_entities = validation.get("core_entities", {})
    custom_types = validation.get("custom_asset_types", [])

    # Calculate total files to parse
    total_files = sum(1 for e in core_entities.values() if e.get("present")) + len(custom_types)
    progress.update(task_id, total=total_files)

    # Parse core entities
    if core_entities.get("organizations", {}).get("present"):
        progress.update(task_id, description="Parsing organizations.csv")
        parsed.organizations = parser.parse_organizations(export_path / "organizations.csv")
        progress.advance(task_id)

    if core_entities.get("configurations", {}).get("present"):
        progress.update(task_id, description="Parsing configurations.csv")
        parsed.configurations = parser.parse_configurations(export_path / "configurations.csv")
        progress.advance(task_id)

    if core_entities.get("documents", {}).get("present"):
        progress.update(task_id, description="Parsing documents.csv")
        parsed.documents = parser.parse_documents(export_path / "documents.csv")
        progress.advance(task_id)

    if core_entities.get("locations", {}).get("present"):
        progress.update(task_id, description="Parsing locations.csv")
        parsed.locations = parser.parse_locations(export_path / "locations.csv")
        progress.advance(task_id)

    if core_entities.get("passwords", {}).get("present"):
        progress.update(task_id, description="Parsing passwords.csv")
        parsed.passwords = parser.parse_passwords(export_path / "passwords.csv")
        progress.advance(task_id)

    # Parse custom asset types
    for custom_type in custom_types:
        progress.update(task_id, description=f"Parsing {custom_type}.csv")
        csv_path = export_path / f"{custom_type}.csv"
        field_defs, assets = parser.parse_custom_asset_csv(csv_path, custom_type)
        parsed.custom_assets[custom_type] = assets
        parsed.field_definitions[custom_type] = [fd.to_dict() for fd in field_defs]
        progress.advance(task_id)

    return parsed


def _parse_export_with_progress(
    parser: CSVParser,
    export_path: Path,
    validation: dict[str, Any],
) -> ParsedData:
    """Parse all CSV files while showing a progress spinner."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("Parsing...", total=None)
        return _parse_all_csv_files(parser, export_path, validation, progress, task)


def _filter_org_records(
    parsed: ParsedData,
    org_itglue_id: str,
    org_name: str,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Filter parsed CSV data to one organization (configurations, locations, documents, passwords, custom assets).

    CSV files reference organizations by IT Glue ID or by name.
    """
    # Note: organization_id field contains org NAME from IT Glue CSV
    def matches_org(item: dict[str, Any]) -> bool:
        csv_org = str(item.get("organization_id") or item.get("organization") or "")
        return csv_org == org_itglue_id or csv_org == org_name

    org_configs = [c for c in parsed.configurations if matches_org(c)]
    org_locations = [loc for loc in parsed.locations if matches_org(loc)]
    org_documents = [d for d in parsed.documents if matches_org(d)]
    org_passwords = [p for p in parsed.passwords if matches_org(p)]

    # Flatten custom assets for this org
    org_custom_assets = []
    for type_slug, assets in parsed.custom_assets.items():
        for asset in assets:
            if matches_org(asset):
                asset["_type_slug"] = type_slug
                org_custom_assets.append(asset)

    return org_configs, org_locations, org_documents, org_passwords, org_custom_assets


def _match_organizations(
    parsed_orgs: list[dict[str, Any]],
    existing_orgs: list[dict[str, Any]],
) -> tuple[OrgMatcher, dict[str, Any]]:
    """Match IT Glue organizations to existing organizations.

    Args:
        parsed_orgs: Parsed IT Glue organizations.
        existing_orgs: Existing organizations from API.

    Returns:
        Tuple of (OrgMatcher, mapping dict for plan).
    """
    matcher = OrgMatcher(existing_orgs)

    # Transform parsed orgs to matcher format (needs 'attributes' wrapper)
    for org in parsed_orgs:
        # Create matcher-compatible format
        matcher_org = {
            "id": org.get("id"),
            "attributes": {"name": org.get("name")},
        }
        matcher.match(matcher_org)

    # Build mapping for plan output
    mapping: dict[str, dict[str, Any]] = {}
    for name, result in matcher.get_mapping().items():
        mapping[name] = {
            "status": result.status,
            "uuid": result.uuid,
            "match_type": result.match_type,
        }

    return matcher, mapping


def _infer_custom_asset_schemas(
    parsed: ParsedData,
    password_field_map: PasswordFieldMap | None = None,
) -> dict[str, dict[str, Any]]:
    """Infer schemas for custom asset types.

    Args:
        parsed: ParsedData with custom assets and field definitions.
        password_field_map: Optional map of fields that should be password type
            based on embedded StructuredData::Cell passwords.

    Returns:
        Dict mapping asset type name to schema info.
    """
    inferrer = FieldInferrer()
    schemas: dict[str, dict[str, Any]] = {}

    for asset_type, assets in parsed.custom_assets.items():
        if not assets:
            continue

        # Collect ALL unique field names across ALL assets of this type
        # (not just the first one, since different assets may have different fields)
        all_columns: set[str] = set()
        for asset in assets:
            asset_fields = asset.get("fields", {})
            all_columns.update(asset_fields.keys())

        columns = sorted(all_columns)  # Sort for deterministic ordering

        if not columns:
            continue

        # Build rows for inference
        rows = [asset.get("fields", {}) for asset in assets]

        # Get password fields for this asset type (if any)
        password_fields: set[str] | None = None
        if password_field_map:
            password_fields = password_field_map.get_password_fields_for_type(asset_type)

        # Infer schema
        field_defs = inferrer.infer_schema(
            columns=columns,
            rows=rows,
            skip_columns={"id", "organization", "organization_id", "created_at", "updated_at"},
            password_fields=password_fields,
        )

        # Get sample row
        sample_row = {}
        if assets:
            sample_fields = assets[0].get("fields", {})
            for k, v in sample_fields.items():
                if v is not None:
                    sample_row[k] = v

        schemas[asset_type] = {
            "display_name": slugify_to_display_name(asset_type),
            "fields": field_defs,
            "sample_row": sample_row,
            "count": len(assets),
        }

    return schemas


def _apply_password_field_types(
    field_definitions: dict[str, list[dict[str, Any]]],
    password_field_map: PasswordFieldMap,
) -> None:
    """Update field definitions to mark password fields correctly.

    Modifies field_definitions in place to change the field_type of
    password fields from their inferred type to "password".

    Args:
        field_definitions: Dict mapping asset type slug to list of field dicts.
        password_field_map: Map identifying which fields should be password type.
    """
    for asset_type_slug, fields in field_definitions.items():
        password_fields = password_field_map.get_password_fields_for_type(asset_type_slug)
        if not password_fields:
            continue

        for field_def in fields:
            field_name = field_def.get("name", "")
            if field_name.lower() in password_fields:
                old_type = field_def.get("field_type", "text")
                if old_type != "password":
                    field_def["field_type"] = "password"
                    console.print(
                        f"  [green]✓[/green] {asset_type_slug}.{field_name}: {old_type} → password"
                    )


def _scan_attachments(export_path: Path) -> dict[str, Any]:
    """Scan export directory for attachments.

    Args:
        export_path: Path to the export directory.

    Returns:
        Attachment statistics dict.
    """
    scanner = AttachmentScanner()
    stats = scanner.scan_export(export_path)
    return stats.to_dict()


def _detect_warnings(
    parsed: ParsedData,
) -> list[dict[str, Any]]:
    """Detect warnings in the parsed data.

    Args:
        parsed: ParsedData container.

    Returns:
        List of warning dicts.
    """
    detector = WarningDetector()
    warnings = detector.detect_all(parsed)
    return [w.to_dict() for w in warnings]


def _build_plan(
    export_path: Path,
    api_url: str,
    parsed: ParsedData,
    org_mapping: dict[str, Any],
    matcher_stats: dict[str, int],
    custom_asset_schemas: dict[str, dict[str, Any]],
    attachment_stats: dict[str, Any],
    warnings: list[dict[str, Any]],
    attachment_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the migration plan JSON structure.

    Args:
        export_path: Path to the export directory.
        api_url: BifrostDocs API URL.
        parsed: Parsed export data.
        org_mapping: Organization matching mapping.
        matcher_stats: Organization matcher statistics.
        custom_asset_schemas: Inferred custom asset schemas.
        attachment_stats: Attachment scan statistics.
        warnings: List of detected warnings.
        attachment_validation: Optional attachment validation results.

    Returns:
        Complete plan dictionary.
    """
    # Calculate entity counts
    custom_asset_total = sum(len(assets) for assets in parsed.custom_assets.values())

    # Count disabled items (archived=Yes)
    def count_archived(items: list[dict[str, Any]]) -> int:
        return sum(1 for item in items if str(item.get("archived", "")).lower() == "yes")

    disabled_configs = count_archived(parsed.configurations)
    disabled_docs = count_archived(parsed.documents)
    disabled_passwords = count_archived(parsed.passwords)
    disabled_custom_assets = sum(
        count_archived(assets) for assets in parsed.custom_assets.values()
    )

    # Build plan structure
    plan: dict[str, Any] = {
        "version": PLAN_VERSION,
        "export_path": str(export_path.resolve()),
        "api_url": api_url,
        "scanned_at": datetime.now(UTC).isoformat(),
        "organizations": {
            "total": len(parsed.organizations),
            "matched": matcher_stats["matched_by_itglue_id"] + matcher_stats["matched_by_name"],
            "to_create": matcher_stats["create"],
            "mapping": org_mapping,
        },
        "custom_asset_types": custom_asset_schemas,
        "entity_counts": {
            "configurations": len(parsed.configurations),
            "documents": len(parsed.documents),
            "passwords": len(parsed.passwords),
            "locations": len(parsed.locations),
            "custom_assets": custom_asset_total,
        },
        "disabled_counts": {
            "configurations": disabled_configs,
            "documents": disabled_docs,
            "passwords": disabled_passwords,
            "custom_assets": disabled_custom_assets,
        },
        "attachments": attachment_stats,
        "attachment_validation": attachment_validation,
        "warnings": warnings,
    }

    return plan


def _display_summary(
    plan: dict[str, Any],
    warnings: list[dict[str, Any]],
) -> None:
    """Display a summary of the migration plan to the console.

    Args:
        plan: The generated plan dictionary.
        warnings: List of warning dicts.
    """
    console.print()

    # Organizations summary
    orgs = plan["organizations"]
    org_table = Table(title="Organizations", show_header=True)
    org_table.add_column("Metric", style="cyan")
    org_table.add_column("Count", justify="right")
    org_table.add_row("Total", str(orgs["total"]))
    org_table.add_row("Matched", str(orgs["matched"]))
    org_table.add_row("To Create", str(orgs["to_create"]))
    console.print(org_table)
    console.print()

    # Entity counts with disabled info
    counts = plan["entity_counts"]
    disabled = plan.get("disabled_counts", {})
    entity_table = Table(title="Entity Counts", show_header=True)
    entity_table.add_column("Entity Type", style="cyan")
    entity_table.add_column("Total", justify="right")
    entity_table.add_column("Disabled", justify="right", style="yellow")

    def fmt_disabled(entity: str) -> str:
        d = disabled.get(entity, 0)
        return f"{d:,}" if d > 0 else "-"

    entity_table.add_row("Configurations", f"{counts['configurations']:,}", fmt_disabled("configurations"))
    entity_table.add_row("Documents", f"{counts['documents']:,}", fmt_disabled("documents"))
    entity_table.add_row("Passwords", f"{counts['passwords']:,}", fmt_disabled("passwords"))
    entity_table.add_row("Locations", f"{counts['locations']:,}", "-")  # Locations don't have archived
    entity_table.add_row("Custom Assets", f"{counts['custom_assets']:,}", fmt_disabled("custom_assets"))
    console.print(entity_table)
    console.print()

    # Custom asset types
    custom_types = plan.get("custom_asset_types", {})
    if custom_types:
        custom_table = Table(title="Custom Asset Types", show_header=True)
        custom_table.add_column("Type", style="cyan")
        custom_table.add_column("Count", justify="right")
        custom_table.add_column("Fields", justify="right")
        for type_name, info in sorted(custom_types.items()):
            custom_table.add_row(
                type_name,
                f"{info.get('count', 0):,}",
                str(len(info.get("fields", []))),
            )
        console.print(custom_table)
        console.print()

    # Attachments
    attachments = plan.get("attachments", {})
    if attachments.get("total_files", 0) > 0:
        attach_table = Table(title="Attachments", show_header=True)
        attach_table.add_column("Metric", style="cyan")
        attach_table.add_column("Value", justify="right")
        attach_table.add_row("Total Files", f"{attachments.get('total_files', 0):,}")
        attach_table.add_row("Total Size", attachments.get("formatted_size", "0 B"))
        console.print(attach_table)
        console.print()

    # Warnings summary
    warning_summary = summarize([Warning(**w) for w in warnings])  # type: ignore[arg-type]
    if warning_summary["total"] > 0:
        warn_table = Table(title="Warnings", show_header=True)
        warn_table.add_column("Severity", style="cyan")
        warn_table.add_column("Count", justify="right")
        for severity, count in warning_summary["by_severity"].items():
            style = {"error": "red", "warning": "yellow", "info": "blue"}.get(severity, "")
            warn_table.add_row(f"[{style}]{severity}[/{style}]", str(count))
        console.print(warn_table)

        if warning_summary["has_blockers"]:
            console.print()
            console.print(
                Panel(
                    "[red]Errors detected![/red] Review the plan file for details before proceeding.",
                    title="Warning",
                    border_style="red",
                )
            )


@app.command()
def preview(
    export_path: Annotated[
        Path,
        typer.Option(
            "--export-path",
            "-e",
            help="Path to the IT Glue export directory",
            exists=False,  # We validate manually for better error messages
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ],
    api_url: Annotated[
        str,
        typer.Option(
            "--api-url",
            "-u",
            help="BifrostDocs API URL (e.g., https://api.example.com)",
            envvar="BIFROST_API_URL",
        ),
    ],
    token: Annotated[
        str,
        typer.Option(
            "--token",
            "-t",
            help="BifrostDocs API authentication token",
            envvar="BIFROST_API_TOKEN",
        ),
    ],
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Output path for the migration plan JSON file",
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = Path("plan.json"),
) -> None:
    """Scan IT Glue export and generate a migration plan file.

    This command analyzes the IT Glue export directory, fetches existing
    organizations from the target API, matches organizations, infers custom
    asset type schemas, scans attachments, detects potential issues, and
    generates a comprehensive migration plan JSON file.

    The plan file can be reviewed before running the actual migration.
    """
    console.print(Panel("IT Glue Migration - Preview", style="bold blue"))
    console.print()

    # Step 1: Validate export path
    console.print("[bold]Step 1:[/bold] Validating export path...")
    validation = _validate_export_path(export_path)
    console.print(f"  [green]Export path valid[/green]: {export_path}")
    console.print()

    # Step 2: Fetch existing organizations
    console.print("[bold]Step 2:[/bold] Fetching existing organizations from API...")
    existing_orgs = asyncio.run(_fetch_existing_organizations(api_url, token))
    console.print(f"  [green]Found {len(existing_orgs)} existing organizations[/green]")
    console.print()

    # Step 3: Parse CSV files
    console.print("[bold]Step 3:[/bold] Parsing CSV files...")
    parser = CSVParser()
    parsed = _parse_export_with_progress(parser, export_path, validation)

    console.print(f"  [green]Parsed {len(parsed.organizations)} organizations[/green]")
    console.print()

    # Step 4: Match organizations
    console.print("[bold]Step 4:[/bold] Matching organizations...")
    matcher, org_mapping = _match_organizations(parsed.organizations, existing_orgs)
    stats = matcher.get_stats()
    console.print(
        f"  [green]Matched: {stats['matched_by_itglue_id'] + stats['matched_by_name']}, "
        f"To create: {stats['create']}[/green]"
    )
    console.print()

    # Step 5: Infer custom asset schemas
    console.print("[bold]Step 5:[/bold] Inferring custom asset type schemas...")
    # Build password field map from Cell passwords
    password_field_map = build_password_field_map(parsed.passwords)
    if password_field_map.global_password_fields:
        console.print(f"  [dim]Detected password fields: {password_field_map.global_password_fields}[/dim]")
    custom_asset_schemas = _infer_custom_asset_schemas(parsed, password_field_map)
    console.print(f"  [green]Inferred {len(custom_asset_schemas)} custom asset type schemas[/green]")
    console.print()

    # Step 6: Scan attachments
    console.print("[bold]Step 6:[/bold] Scanning attachments...")
    attachment_stats = _scan_attachments(export_path)
    console.print(
        f"  [green]Found {attachment_stats.get('total_files', 0)} files "
        f"({attachment_stats.get('formatted_size', '0 B')})[/green]"
    )
    console.print()

    # Step 7: Validate attachments against entities
    console.print("[bold]Step 7:[/bold] Validating attachment mappings...")

    # Build entities_to_migrate dict from parsed data
    entities_to_migrate: dict[str, set[str]] = {
        "configurations": {str(c["id"]) for c in parsed.configurations},
        "documents": {str(d["id"]) for d in parsed.documents},
        "passwords": {str(p["id"]) for p in parsed.passwords},
        "locations": {str(loc["id"]) for loc in parsed.locations},
    }

    # Add custom asset type slugs
    for asset_type, assets in parsed.custom_assets.items():
        if asset_type not in entities_to_migrate:
            entities_to_migrate[asset_type] = set()
        for asset in assets:
            entities_to_migrate[asset_type].add(str(asset["id"]))

    # Validate attachments
    scanner = AttachmentScanner()
    attachment_validation = validate_attachments(export_path, entities_to_migrate, scanner)
    console.print(
        f"  [green]Matched {attachment_validation.total_matched_files} files to entities[/green]"
    )
    if attachment_validation.total_orphaned_folders > 0:
        console.print(
            f"  [yellow]⚠️  {attachment_validation.total_orphaned_folders} orphaned folders "
            f"(no matching entity)[/yellow]"
        )
    console.print()

    # Step 8: Detect warnings
    console.print("[bold]Step 8:[/bold] Detecting potential issues...")
    warnings = _detect_warnings(parsed)
    warning_summary = summarize([Warning(**w) for w in warnings])  # type: ignore[arg-type]
    console.print(f"  [green]Found {warning_summary['total']} warnings[/green]")
    console.print()

    # Step 9: Build and write plan
    console.print("[bold]Step 9:[/bold] Generating migration plan...")
    plan = _build_plan(
        export_path=export_path,
        api_url=api_url,
        parsed=parsed,
        org_mapping=org_mapping,
        matcher_stats=stats,
        custom_asset_schemas=custom_asset_schemas,
        attachment_stats=attachment_stats,
        warnings=warnings,
        attachment_validation=attachment_validation.to_dict(),
    )

    # Write plan to file
    try:
        with output.open("w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2, default=str)
        console.print(f"  [green]Plan written to {output}[/green]")
    except OSError as e:
        error_console.print(f"[red]Error:[/red] Failed to write plan file: {e}")
        raise typer.Exit(1) from None

    # Display summary
    _display_summary(plan, warnings)

    console.print()
    console.print(
        Panel(
            f"[green]Preview complete![/green]\n\n"
            f"Plan saved to: {output}\n\n"
            f"Review the plan file and run [bold]itglue-migrate run --plan {output}[/bold] "
            f"to execute the migration.",
            title="Done",
            border_style="green",
        )
    )


@app.command("test-doc")
def test_document(
    export_path: Annotated[Path, typer.Argument(help="Path to IT Glue export directory")],
    doc_id: Annotated[str, typer.Argument(help="Document ID to test (the numeric ID from DOC-xxx-{ID})")],
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output file path (prints to stdout if not specified)")] = None,
) -> None:
    """Test processing a single document without importing.

    Processes the document HTML, applies all transformations (step sections,
    Word formatting cleanup, etc.), converts to markdown, and outputs
    the result without calling any APIs.

    Example:
        itglue-migrate test-doc /path/to/export 9848386 -o /tmp/test.md
    """
    from itglue_migrate.document_processor import DocumentProcessor

    # Find the document folder
    documents_path = export_path / "documents"
    if not documents_path.exists():
        console.print(f"[red]Documents directory not found: {documents_path}[/red]")
        raise typer.Exit(1)

    doc_folder = None

    # Search for DOC-*-{doc_id} folder pattern
    for folder in documents_path.rglob("DOC-*"):
        if not folder.is_dir():
            continue
        # Pattern: DOC-{org_id}-{doc_id} {name}
        match = re.match(r"^DOC-\d+-(\d+)\s", folder.name)
        if match and match.group(1) == doc_id:
            doc_folder = folder
            break

    if not doc_folder:
        console.print(f"[red]Document folder not found for ID {doc_id}[/red]")
        console.print("[yellow]Looking for folders matching: DOC-*-{doc_id} *[/yellow]")
        raise typer.Exit(1)

    # Find HTML file
    html_files = list(doc_folder.glob("*.html"))
    if not html_files:
        html_files = list(doc_folder.glob("*.htm"))

    if not html_files:
        console.print(f"[red]No HTML file found in {doc_folder}[/red]")
        raise typer.Exit(1)

    # Prefer index.html if it exists
    html_file = html_files[0]
    for f in html_files:
        if f.name.lower() in ("index.html", "index.htm"):
            html_file = f
            break

    console.print(f"[blue]Processing:[/blue] {html_file}")
    console.print(f"[blue]Document folder:[/blue] {doc_folder.name}")

    # Read the HTML content
    try:
        html = html_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            html = html_file.read_text(encoding="latin-1")
        except Exception as e:
            console.print(f"[red]Failed to read HTML file: {e}[/red]")
            raise typer.Exit(1)

    console.print(f"[dim]Input HTML size: {len(html)} bytes[/dim]")

    # Create a mock client class (we don't need actual API access)
    class MockClient:
        pass

    processor = DocumentProcessor(MockClient(), export_path)  # type: ignore

    # Apply HTML cleaning
    cleaned = processor._clean_html(html)

    # Convert to markdown
    markdown = processor._html_to_markdown(cleaned)

    console.print(f"[dim]Output markdown size: {len(markdown)} bytes[/dim]")

    # Check if empty
    if not markdown.strip():
        console.print("[yellow]Warning: Document content is empty after processing[/yellow]")

    # Output
    if output:
        output.write_text(markdown)
        console.print(f"[green]Wrote output to {output}[/green]")
    else:
        console.print("\n[bold]--- Processed Content ---[/bold]\n")
        console.print(markdown)


async def _verify_api_connectivity(
    api_url: str,
    token: str,
) -> bool:
    """Verify API connectivity by fetching organizations.

    Args:
        api_url: Base URL of the BifrostDocs API.
        token: API authentication token.

    Returns:
        True if connectivity verified, False otherwise.
    """
    try:
        async with BifrostDocsClient(base_url=api_url, api_key=token) as client:
            await client.list_organizations()
            return True
    except APIError:
        return False


async def _migrate_organizations(
    client: BifrostDocsClient,
    parsed_orgs: list[dict[str, Any]],
    org_mapping: dict[str, dict[str, Any]],
    state: MigrationState,
    reporter: Any,
    dry_run: bool,
    target_org: str | None,
) -> None:
    """Migrate organizations (create new ones, store mappings for existing).

    Args:
        client: BifrostDocs API client.
        parsed_orgs: List of parsed organizations from CSV.
        org_mapping: Organization mapping from plan (name -> status/uuid).
        state: Migration state for tracking progress.
        reporter: Progress reporter.
        dry_run: If True, don't make API calls.
        target_org: If specified, only process this organization.
    """
    # Filter to target org if specified
    if target_org:
        parsed_orgs = [o for o in parsed_orgs if o.get("name") == target_org]

    reporter.start_phase(Phase.ORGANIZATIONS, len(parsed_orgs))

    for org in parsed_orgs:
        org_name = org.get("name", "")
        itglue_id = str(org.get("id", ""))

        # Skip if already completed
        if state.is_completed(Phase.ORGANIZATIONS, itglue_id):
            reporter.update_progress(skipped=1, current_item=f"Skipped: {org_name}")
            continue

        reporter.set_current_item(org_name)

        try:
            mapping_info = org_mapping.get(org_name, {})
            status = mapping_info.get("status", "create")
            existing_uuid = mapping_info.get("uuid")

            if status == "matched" and existing_uuid:
                # Organization already exists - store the mapping
                # Add both by IT Glue ID and by name (CSVs reference orgs by name)
                state.id_mapper.add("organization", itglue_id, existing_uuid)
                state.id_mapper.add("organization", org_name, existing_uuid)
                state.mark_completed(Phase.ORGANIZATIONS, itglue_id)
                reporter.update_progress(succeeded=1, current_item=f"Matched: {org_name}")
            else:
                # Need to create the organization
                if dry_run:
                    # Use placeholder UUID so subsequent phases can validate lookups
                    placeholder_uuid = f"dry-run-org-{itglue_id}"
                    state.id_mapper.add("organization", itglue_id, placeholder_uuid)
                    state.id_mapper.add("organization", org_name, placeholder_uuid)
                    # Note: Don't call state.mark_completed() during dry runs
                    # to avoid persisting state that would cause items to be skipped
                    # when running without --dry-run
                    reporter.update_progress(succeeded=1, current_item=f"[DRY RUN] Would create: {org_name}")
                else:
                    metadata = {"itglue_id": itglue_id}
                    if org.get("description"):
                        metadata["description"] = org["description"]

                    created = await client.create_organization(
                        name=org_name,
                        metadata=metadata,
                    )
                    new_uuid = created.get("id")
                    if new_uuid:
                        # Add both by IT Glue ID and by name (CSVs reference orgs by name)
                        state.id_mapper.add("organization", itglue_id, new_uuid)
                        state.id_mapper.add("organization", org_name, new_uuid)
                    state.mark_completed(Phase.ORGANIZATIONS, itglue_id)
                    reporter.update_progress(succeeded=1, current_item=f"Created: {org_name}")

        except APIError as e:
            state.mark_failed(Phase.ORGANIZATIONS, itglue_id, str(e))
            reporter.error(f"Failed to migrate org '{org_name}': {e}")
            reporter.update_progress(failed=1)

    reporter.complete_phase()


async def _migrate_locations(
    client: BifrostDocsClient,
    parsed_locations: list[dict[str, Any]],
    state: MigrationState,
    reporter: Any,
    dry_run: bool,
    target_org_names: set[str] | None,
    doc_processor: DocumentProcessor | None = None,
    export_path: Path | None = None,
) -> None:
    """Migrate locations.

    Args:
        client: BifrostDocs API client.
        parsed_locations: List of parsed locations from CSV.
        state: Migration state for tracking progress.
        reporter: Progress reporter.
        dry_run: If True, don't make API calls.
        target_org_names: If specified, only process locations for these org names.
        doc_processor: Optional document processor for attachment uploads.
        export_path: Optional export path for attachment uploads.
    """
    # Filter to target orgs if specified
    # Note: organization_id field contains org NAME from IT Glue CSV
    if target_org_names:
        parsed_locations = [
            loc for loc in parsed_locations
            if loc.get("organization_id", "") in target_org_names
        ]

    reporter.start_phase(Phase.LOCATIONS, len(parsed_locations))

    for location in parsed_locations:
        itglue_id = str(location.get("id", ""))
        name = location.get("name", "")
        org_itglue_id = str(location.get("organization_id", ""))

        # Skip if already completed
        if state.is_completed(Phase.LOCATIONS, itglue_id):
            reporter.update_progress(skipped=1, current_item=f"Skipped: {name}")
            continue

        reporter.set_current_item(name)

        # Get the target org UUID
        org_uuid = state.id_mapper.get("organization", org_itglue_id)
        if not org_uuid:
            state.mark_failed(Phase.LOCATIONS, itglue_id, f"Organization {org_itglue_id} not migrated")
            reporter.update_progress(failed=1)
            continue

        try:
            if dry_run:
                # Use placeholder UUID so subsequent phases can validate lookups
                placeholder_uuid = f"dry-run-location-{itglue_id}"
                state.id_mapper.add("location", itglue_id, placeholder_uuid)
                # Note: Don't call state.mark_completed() during dry runs
                reporter.update_progress(succeeded=1, current_item=f"[DRY RUN] Would create: {name}")
            else:
                # Build notes from address fields
                notes_parts = []
                for field in ["address_1", "address_2", "city", "region", "postal_code", "country", "phone"]:
                    if location.get(field):
                        notes_parts.append(f"**{field.replace('_', ' ').title()}**: {location[field]}")

                notes = "\n".join(notes_parts) if notes_parts else None

                created = await client.create_location(
                    org_id=org_uuid,
                    name=name,
                    notes=notes,
                    metadata={"itglue_id": itglue_id},
                )
                new_uuid = created.get("id")
                if new_uuid:
                    state.id_mapper.add("location", itglue_id, new_uuid)
                state.mark_completed(Phase.LOCATIONS, itglue_id)

                # Upload attachments for this location
                if doc_processor and export_path and new_uuid:
                    try:
                        attachment_count = await doc_processor.upload_entity_attachments(
                            entity_type="locations",
                            entity_id=itglue_id,
                            org_uuid=org_uuid,
                            our_entity_id=new_uuid,
                            state=state,
                        )
                        if attachment_count > 0:
                            reporter.info(f"Uploaded {attachment_count} attachments for location {name}")
                    except Exception as e:
                        reporter.warning(f"Failed to upload attachments for location {name}: {e}")

                reporter.update_progress(succeeded=1, current_item=f"Created: {name}")

        except APIError as e:
            state.mark_failed(Phase.LOCATIONS, itglue_id, str(e))
            reporter.error(f"Failed to migrate location '{name}': {e}")
            reporter.update_progress(failed=1)

    reporter.complete_phase()


async def _migrate_configuration_types(
    client: BifrostDocsClient,
    parsed_configs: list[dict[str, Any]],
    state: MigrationState,
    reporter: Any,
    dry_run: bool,
) -> dict[str, str]:
    """Migrate configuration types (extract unique types and create them).

    Args:
        client: BifrostDocs API client.
        parsed_configs: List of parsed configurations from CSV.
        state: Migration state for tracking progress.
        reporter: Progress reporter.
        dry_run: If True, don't make API calls.

    Returns:
        Mapping of configuration type name to UUID.
    """
    # Extract unique configuration types
    unique_types: set[str] = set()
    for config in parsed_configs:
        config_type = config.get("configuration_type")
        if config_type:
            unique_types.add(config_type)

    reporter.start_phase(Phase.CONFIGURATION_TYPES, len(unique_types))

    type_mapping: dict[str, str] = {}

    # Fetch existing configuration types
    if not dry_run:
        try:
            existing_types = await client.list_configuration_types(include_inactive=True)
            for existing in existing_types:
                name = existing.get("name", "")
                uuid = existing.get("id")
                if name and uuid:
                    type_mapping[name.lower()] = uuid
        except APIError as e:
            reporter.warning(f"Failed to fetch existing configuration types: {e}")

    for type_name in sorted(unique_types):
        # Check if already exists (case-insensitive)
        if type_name.lower() in type_mapping:
            state.id_mapper.add("configuration_type", type_name, type_mapping[type_name.lower()])
            reporter.update_progress(skipped=1, current_item=f"Exists: {type_name}")
            continue

        reporter.set_current_item(type_name)

        try:
            if dry_run:
                # Use placeholder UUID so subsequent phases can validate lookups
                placeholder_uuid = f"dry-run-config-type-{type_name}"
                state.id_mapper.add("configuration_type", type_name, placeholder_uuid)
                type_mapping[type_name.lower()] = placeholder_uuid
                reporter.update_progress(succeeded=1, current_item=f"[DRY RUN] Would create: {type_name}")
            else:
                created = await client.create_configuration_type(name=type_name)
                new_uuid = created.get("id")
                if new_uuid:
                    state.id_mapper.add("configuration_type", type_name, new_uuid)
                    type_mapping[type_name.lower()] = new_uuid
                reporter.update_progress(succeeded=1, current_item=f"Created: {type_name}")

        except APIError as e:
            reporter.error(f"Failed to create config type '{type_name}': {e}")
            reporter.update_progress(failed=1)

    reporter.complete_phase()
    return type_mapping


async def _migrate_configurations(
    client: BifrostDocsClient,
    parsed_configs: list[dict[str, Any]],
    state: MigrationState,
    reporter: Any,
    dry_run: bool,
    target_org_names: set[str] | None,
    doc_processor: DocumentProcessor | None = None,
    export_path: Path | None = None,
) -> None:
    """Migrate configurations.

    Args:
        client: BifrostDocs API client.
        parsed_configs: List of parsed configurations from CSV.
        state: Migration state for tracking progress.
        reporter: Progress reporter.
        dry_run: If True, don't make API calls.
        target_org_names: If specified, only process configs for these org names.
        doc_processor: Optional document processor for attachment uploads.
        export_path: Optional export path for attachment uploads.
    """
    # Filter to target orgs if specified
    # Note: organization_id field contains org NAME from IT Glue CSV
    if target_org_names:
        parsed_configs = [
            cfg for cfg in parsed_configs
            if cfg.get("organization_id", "") in target_org_names
        ]

    reporter.start_phase(Phase.CONFIGURATIONS, len(parsed_configs))

    for config in parsed_configs:
        itglue_id = str(config.get("id", ""))
        name = config.get("name", "")
        org_itglue_id = str(config.get("organization_id", ""))

        # Skip if already completed
        if state.is_completed(Phase.CONFIGURATIONS, itglue_id):
            reporter.update_progress(skipped=1, current_item=f"Skipped: {name}")
            continue

        reporter.set_current_item(name)

        # Get the target org UUID
        org_uuid = state.id_mapper.get("organization", org_itglue_id)
        if not org_uuid:
            state.mark_failed(Phase.CONFIGURATIONS, itglue_id, f"Organization {org_itglue_id} not migrated")
            reporter.update_progress(failed=1)
            continue

        # Get configuration type UUID if specified
        config_type_uuid = None
        config_type = config.get("configuration_type")
        if config_type:
            config_type_uuid = state.id_mapper.get("configuration_type", config_type)

        # Compute is_enabled from archived and configuration_status
        archived = config.get("archived")
        is_enabled = map_archived_to_is_enabled(archived)
        config_status = config.get("configuration_status")
        if config_status and config_status.lower() != "active":
            is_enabled = False

        try:
            if dry_run:
                # Use placeholder UUID so subsequent phases can validate lookups
                placeholder_uuid = f"dry-run-config-{itglue_id}"
                state.id_mapper.add("configuration", itglue_id, placeholder_uuid)
                # Note: Don't call state.mark_completed() during dry runs
                reporter.update_progress(succeeded=1, current_item=f"[DRY RUN] Would create: {name}")
            else:
                created = await client.create_configuration(
                    org_id=org_uuid,
                    name=name,
                    configuration_type_id=config_type_uuid,
                    serial_number=config.get("serial"),
                    manufacturer=config.get("manufacturer"),
                    model=config.get("model"),
                    ip_address=config.get("ip"),
                    mac_address=config.get("mac"),
                    notes=config.get("notes"),
                    metadata={"itglue_id": itglue_id},
                    interfaces=config.get("configuration_interfaces"),
                    is_enabled=is_enabled,
                )
                new_uuid = created.get("id")
                if new_uuid:
                    state.id_mapper.add("configuration", itglue_id, new_uuid)
                state.mark_completed(Phase.CONFIGURATIONS, itglue_id)

                # Upload attachments for this configuration
                if doc_processor and export_path and new_uuid:
                    try:
                        attachment_count = await doc_processor.upload_entity_attachments(
                            entity_type="configurations",
                            entity_id=itglue_id,
                            org_uuid=org_uuid,
                            our_entity_id=new_uuid,
                            state=state,
                        )
                        if attachment_count > 0:
                            reporter.info(f"Uploaded {attachment_count} attachments for config {name}")
                    except Exception as e:
                        reporter.warning(f"Failed to upload attachments for config {name}: {e}")

                reporter.update_progress(succeeded=1, current_item=f"Created: {name}")

        except APIError as e:
            state.mark_failed(Phase.CONFIGURATIONS, itglue_id, str(e))
            reporter.error(f"Failed to migrate config '{name}': {e}")
            reporter.update_progress(failed=1)

    reporter.complete_phase()


async def _migrate_custom_asset_types(
    client: BifrostDocsClient,
    custom_asset_schemas: dict[str, dict[str, Any]],
    state: MigrationState,
    reporter: Any,
    dry_run: bool,
) -> dict[str, str]:
    """Migrate custom asset types (create type definitions).

    Args:
        client: BifrostDocs API client.
        custom_asset_schemas: Custom asset type schemas from plan.
        state: Migration state for tracking progress.
        reporter: Progress reporter.
        dry_run: If True, don't make API calls.

    Returns:
        Mapping of custom asset type name to UUID.
    """
    reporter.start_phase(Phase.CUSTOM_ASSET_TYPES, len(custom_asset_schemas))

    type_mapping: dict[str, str] = {}

    # Fetch existing custom asset types
    if not dry_run:
        try:
            existing_types = await client.list_custom_asset_types(include_inactive=True)
            for existing in existing_types:
                name = existing.get("name", "")
                uuid = existing.get("id")
                if name and uuid:
                    type_mapping[name.lower()] = uuid
        except APIError as e:
            reporter.warning(f"Failed to fetch existing custom asset types: {e}")

    for type_slug, schema in custom_asset_schemas.items():
        display_name = schema.get("display_name", slugify_to_display_name(type_slug))

        # Check if already exists (case-insensitive)
        if display_name.lower() in type_mapping:
            uuid = type_mapping[display_name.lower()]
            state.id_mapper.add("custom_asset_type", type_slug, uuid)
            reporter.update_progress(skipped=1, current_item=f"Exists: {display_name}")
            continue

        reporter.set_current_item(display_name)

        try:
            if dry_run:
                # Use placeholder UUID so subsequent phases can validate lookups
                placeholder_uuid = f"dry-run-asset-type-{type_slug}"
                state.id_mapper.add("custom_asset_type", type_slug, placeholder_uuid)
                type_mapping[display_name.lower()] = placeholder_uuid
                reporter.update_progress(succeeded=1, current_item=f"[DRY RUN] Would create: {display_name}")
            else:
                # Convert field definitions to API format
                fields = []
                for field_def in schema.get("fields", []):
                    field = {
                        "key": field_def.get("key", field_def.get("name", "").lower().replace(" ", "_")),
                        "name": field_def.get("name", ""),
                        "type": field_def.get("type", field_def.get("field_type", "text")),
                        "required": field_def.get("required", False),
                        "show_in_list": field_def.get("show_in_list", False),
                    }
                    if "hint" in field_def:
                        field["hint"] = field_def["hint"]
                    if "options" in field_def:
                        field["options"] = field_def["options"]
                    fields.append(field)

                created = await client.create_custom_asset_type(
                    name=display_name,
                    fields=fields,
                )
                new_uuid = created.get("id")
                if new_uuid:
                    state.id_mapper.add("custom_asset_type", type_slug, new_uuid)
                    type_mapping[display_name.lower()] = new_uuid
                reporter.update_progress(succeeded=1, current_item=f"Created: {display_name}")

        except APIError as e:
            reporter.error(f"Failed to create custom asset type '{display_name}': {e}")
            reporter.update_progress(failed=1)

    reporter.complete_phase()
    return type_mapping


def _convert_field_value(value: str, field_type: str) -> Any:
    """Convert a string value from CSV to the appropriate Python type.

    Args:
        value: The string value from CSV.
        field_type: The field type (checkbox, number, text, etc.).

    Returns:
        The converted value (bool, int, float, or original string).
    """
    if field_type == "checkbox":
        # Convert checkbox strings to boolean
        # Common true values: true, yes, 1, on, enabled
        # Common false values: false, no, 0, off, disabled
        lower_value = value.lower()
        if lower_value in {"true", "yes", "1", "on", "enabled"}:
            return True
        elif lower_value in {"false", "no", "0", "off", "disabled"}:
            return False
        else:
            # Default to False for unrecognized values
            return False

    elif field_type == "number":
        # Try to convert to int first, then float
        try:
            # Check if it's an integer (e.g., "6.00" should be 6)
            if "." in value:
                float_val = float(value)
                if float_val.is_integer():
                    return int(float_val)
                return float_val
            return int(value)
        except (ValueError, TypeError):
            # Return as-is if conversion fails
            return value

    # For text, textbox, date, select, etc., return as-is
    return value


def _build_field_type_map(
    schema: dict[str, Any],
) -> dict[str, str]:
    """Build a mapping from field key to field type for a custom asset type schema.

    Args:
        schema: The schema dict for a custom asset type, containing 'fields' list.

    Returns:
        Dict mapping field key (snake_case) to field type.
    """
    field_type_map: dict[str, str] = {}
    for field in schema.get("fields", []):
        field_key = field.get("key", "")
        field_type = field.get("type", "text")
        if field_key:
            field_type_map[field_key] = field_type
    return field_type_map


async def _migrate_custom_assets(
    client: BifrostDocsClient,
    parsed_custom_assets: dict[str, list[dict[str, Any]]],
    custom_asset_schemas: dict[str, dict[str, Any]],
    state: MigrationState,
    reporter: Any,
    dry_run: bool,
    target_org_names: set[str] | None,
    doc_processor: DocumentProcessor | None = None,
    export_path: Path | None = None,
) -> None:
    """Migrate custom assets.

    Args:
        client: BifrostDocs API client.
        parsed_custom_assets: Dict of asset type slug to list of assets.
        custom_asset_schemas: Dict of asset type slug to schema info.
        state: Migration state for tracking progress.
        reporter: Progress reporter.
        dry_run: If True, don't make API calls.
        target_org_names: If specified, only process assets for these org names.
        doc_processor: Optional document processor for attachment uploads.
        export_path: Optional export path for attachment uploads.
    """
    # Flatten all custom assets for counting
    # Note: organization_id field contains org NAME from IT Glue CSV
    all_assets = []
    for type_slug, assets in parsed_custom_assets.items():
        for asset in assets:
            asset["_type_slug"] = type_slug
            if target_org_names:
                if asset.get("organization_id", "") in target_org_names:
                    all_assets.append(asset)
            else:
                all_assets.append(asset)

    reporter.start_phase(Phase.CUSTOM_ASSETS, len(all_assets))

    for asset in all_assets:
        type_slug = asset.get("_type_slug", "")
        itglue_id = str(asset.get("id", ""))
        org_itglue_id = str(asset.get("organization_id", ""))
        fields = asset.get("fields", {})
        name = fields.get("name", f"Asset {itglue_id}")

        # Skip if already completed
        if state.is_completed(Phase.CUSTOM_ASSETS, itglue_id):
            reporter.update_progress(skipped=1, current_item=f"Skipped: {name}")
            continue

        reporter.set_current_item(name)

        # Get the target org UUID
        org_uuid = state.id_mapper.get("organization", org_itglue_id)
        if not org_uuid:
            state.mark_failed(Phase.CUSTOM_ASSETS, itglue_id, f"Organization {org_itglue_id} not migrated")
            reporter.update_progress(failed=1)
            continue

        # Get custom asset type UUID
        type_uuid = state.id_mapper.get("custom_asset_type", type_slug)
        if not type_uuid:
            state.mark_failed(Phase.CUSTOM_ASSETS, itglue_id, f"Custom asset type {type_slug} not migrated")
            reporter.update_progress(failed=1)
            continue

        # Get field type map for this asset type
        schema = custom_asset_schemas.get(type_slug, {})
        field_type_map = _build_field_type_map(schema)

        # Transform field names to snake_case keys and convert values to proper types
        values = {}
        for k, v in fields.items():
            if v is not None:
                field_key = column_name_to_key(k)
                field_type = field_type_map.get(field_key, "text")
                values[field_key] = _convert_field_value(v, field_type)

        try:
            if dry_run:
                # Use placeholder UUID so subsequent phases can validate lookups
                placeholder_uuid = f"dry-run-custom-asset-{itglue_id}"
                state.id_mapper.add("custom_asset", itglue_id, placeholder_uuid)
                # Note: Don't call state.mark_completed() during dry runs
                reporter.update_progress(succeeded=1, current_item=f"[DRY RUN] Would create: {name}")
            else:
                # Compute is_enabled from archived field
                archived = asset.get("archived")
                is_enabled = map_archived_to_is_enabled(archived)

                created = await client.create_custom_asset(
                    org_id=org_uuid,
                    type_id=type_uuid,
                    values=values,
                    metadata={"itglue_id": itglue_id},
                    is_enabled=is_enabled,
                )
                new_uuid = created.get("id")
                if new_uuid:
                    state.id_mapper.add("custom_asset", itglue_id, new_uuid)
                state.mark_completed(Phase.CUSTOM_ASSETS, itglue_id)

                # Upload attachments using asset type slug
                if doc_processor and export_path and new_uuid and type_slug:
                    try:
                        # Pass known custom asset types for proper entity type mapping
                        known_custom_asset_types = set(custom_asset_schemas.keys())
                        attachment_count = await doc_processor.upload_entity_attachments(
                            entity_type=type_slug,
                            entity_id=itglue_id,
                            org_uuid=org_uuid,
                            our_entity_id=new_uuid,
                            state=state,
                            known_custom_asset_types=known_custom_asset_types,
                        )
                        if attachment_count > 0:
                            reporter.info(f"Uploaded {attachment_count} attachments for {type_slug} {name}")
                    except Exception as e:
                        reporter.warning(f"Failed to upload attachments for {type_slug} {name}: {e}")

                reporter.update_progress(succeeded=1, current_item=f"Created: {name}")

        except APIError as e:
            state.mark_failed(Phase.CUSTOM_ASSETS, itglue_id, str(e))
            reporter.error(f"Failed to migrate custom asset '{name}': {e}")
            reporter.update_progress(failed=1)

    reporter.complete_phase()


def _build_document_folder_map(
    documents_path: Path,
) -> dict[str, tuple[str, Path | None]]:
    """
    Scan export documents folder and map document IDs to (folder_path, html_file).

    The IT Glue export structure is:
    - documents/{folder}/DOC-{org}-{doc_id} {name}/{name}.html - nested in folder
    - documents/DOC-{org}-{doc_id} {name}/{name}.html - root level

    Args:
        documents_path: Path to the documents/ folder in the export.

    Returns:
        Dict mapping doc_id to (folder_path, html_file_path).
        folder_path is "/" for root-level documents, otherwise "/FolderName".
        html_file_path is the path to the HTML file, or None if not found.
    """
    from itglue_migrate.attachments import DOC_FOLDER_PATTERN

    result: dict[str, tuple[str, Path | None]] = {}

    if not documents_path.exists():
        logger.warning(f"Documents path does not exist: {documents_path}")
        return result

    # Walk the documents directory
    for item in documents_path.rglob("*"):
        if not item.is_dir():
            continue

        # Check if this is a DOC-* folder
        match = DOC_FOLDER_PATTERN.match(item.name)
        if not match:
            continue

        doc_id = match.group(2)

        # Determine the folder path based on parent
        # If parent is documents_path, it's root level ("/")
        # Otherwise, extract folder name from path between documents_path and item
        rel_path = item.relative_to(documents_path)
        parts = rel_path.parts

        if len(parts) == 1:
            # Root level: documents/DOC-xxx-123 Name/
            folder_path = "/"
        else:
            # Nested: documents/FolderName/DOC-xxx-123 Name/
            # The folder path is everything except the last DOC-* part
            folder_parts = parts[:-1]
            folder_path = "/" + "/".join(folder_parts)

        # Find HTML file inside the DOC-* folder
        html_files = list(item.glob("*.html"))
        html_file = html_files[0] if html_files else None

        result[doc_id] = (folder_path, html_file)
        logger.debug(f"Mapped document {doc_id} -> {folder_path}, {html_file}")

    logger.info(f"Built document folder map with {len(result)} entries")
    return result


async def _migrate_documents(
    client: BifrostDocsClient,
    parsed_docs: list[dict[str, Any]],
    state: MigrationState,
    reporter: Any,
    dry_run: bool,
    target_org_names: set[str] | None,
    doc_processor: DocumentProcessor | None = None,
    export_path: Path | None = None,
    skip_attachments: bool = False,
) -> None:
    """Migrate documents.

    Args:
        client: BifrostDocs API client.
        parsed_docs: List of parsed documents from CSV.
        state: Migration state for tracking progress.
        reporter: Progress reporter.
        dry_run: If True, don't make API calls.
        target_org_names: If specified, only process documents for these org names.
        doc_processor: Optional document processor for attachment uploads.
        export_path: Optional export path for attachment uploads.
    """
    # Filter to target orgs if specified
    # Note: organization_id field contains org NAME from IT Glue CSV
    if target_org_names:
        parsed_docs = [
            doc for doc in parsed_docs
            if doc.get("organization_id", "") in target_org_names
        ]

    reporter.start_phase(Phase.DOCUMENTS, len(parsed_docs))

    # Build folder map once for all documents
    documents_path = export_path / "documents" if export_path else None
    folder_map = _build_document_folder_map(documents_path) if documents_path else {}

    # Track seen documents for duplicate detection (org_uuid -> set of lowercase names)
    seen_docs: dict[str, set[str]] = {}

    for doc in parsed_docs:
        itglue_id = str(doc.get("id", ""))
        name = doc.get("name", "")
        org_itglue_id = str(doc.get("organization_id", ""))

        # Skip if already completed
        if state.is_completed(Phase.DOCUMENTS, itglue_id):
            reporter.update_progress(skipped=1, current_item=f"Skipped: {name}")
            continue

        reporter.set_current_item(name)

        # Get the target org UUID
        org_uuid = state.id_mapper.get("organization", org_itglue_id)
        if not org_uuid:
            state.mark_failed(Phase.DOCUMENTS, itglue_id, f"Organization {org_itglue_id} not migrated")
            reporter.update_progress(failed=1)
            continue

        # Check for duplicate document names within the same org
        name_lower = name.lower()
        if org_uuid in seen_docs and name_lower in seen_docs[org_uuid]:
            reporter.warning(f"Duplicate document '{name}' in organization, skipping")
            reporter.update_progress(skipped=1)
            state.add_warning(f"Skipped duplicate document: {name}")
            continue
        seen_docs.setdefault(org_uuid, set()).add(name_lower)

        try:
            if dry_run:
                # Use placeholder UUID so subsequent phases can validate lookups
                placeholder_uuid = f"dry-run-document-{itglue_id}"
                state.id_mapper.add("document", itglue_id, placeholder_uuid)
                # Note: Don't call state.mark_completed() during dry runs
                reporter.update_progress(succeeded=1, current_item=f"[DRY RUN] Would create: {name}")
            else:
                # Get folder path from folder map (for path field only)
                path = "/"  # Default to root

                if folder_map and itglue_id in folder_map:
                    path, _ = folder_map[itglue_id]
                    logger.debug(f"Document {itglue_id}: found in folder map with path '{path}'")
                elif not folder_map:
                    logger.debug(f"Document {itglue_id}: folder map is empty, using root path")
                else:
                    logger.debug(f"Document {itglue_id}: not found in folder map, using root path")

                # Process document HTML: upload images, transform content
                content = ""
                content_warnings = []

                if doc_processor:
                    try:
                        # Use DocumentProcessor to find HTML, upload images, and transform content
                        processed_html, warnings = await doc_processor.process_document(
                            doc=doc,
                            org_uuid=org_uuid,
                        )
                        content = processed_html
                        content_warnings = warnings

                        if content_warnings:
                            for warning in content_warnings:
                                reporter.warning(f"Document '{name}': {warning}")

                    except Exception as e:
                        reporter.warning(f"Failed to process document HTML for '{name}': {e}")
                        content = ""

                # Check for empty content after processing
                if not content or not content.strip():
                    reporter.warning(f"Document '{name}' has empty content, skipping")
                    reporter.update_progress(skipped=1)
                    state.add_warning(f"Skipped empty document: {name}")
                    continue

                # Compute is_enabled from archived field
                archived = doc.get("archived")
                is_enabled = map_archived_to_is_enabled(archived)

                created = await client.create_document(
                    org_id=org_uuid,
                    path=path,
                    name=name,
                    content=content,
                    metadata={"itglue_id": itglue_id},
                    is_enabled=is_enabled,
                )
                new_uuid = created.get("id")
                if new_uuid:
                    state.id_mapper.add("document", itglue_id, new_uuid)
                state.mark_completed(Phase.DOCUMENTS, itglue_id)

                # Upload attachments for this document
                if doc_processor and export_path and new_uuid and not skip_attachments:
                    try:
                        attachment_count = await doc_processor.upload_entity_attachments(
                            entity_type="documents",
                            entity_id=itglue_id,
                            org_uuid=org_uuid,
                            our_entity_id=new_uuid,
                            state=state,
                        )
                        if attachment_count > 0:
                            reporter.info(f"Uploaded {attachment_count} attachments for document {name}")
                    except Exception as e:
                        reporter.warning(f"Failed to upload attachments for document {name}: {e}")

                reporter.update_progress(succeeded=1, current_item=f"Created: {name}")

        except APIError as e:
            state.mark_failed(Phase.DOCUMENTS, itglue_id, str(e))
            reporter.error(f"Failed to migrate document '{name}': {e}")
            reporter.update_progress(failed=1)

    reporter.complete_phase()


async def _migrate_passwords(
    client: BifrostDocsClient,
    parsed_passwords: list[dict[str, Any]],
    state: MigrationState,
    reporter: Any,
    dry_run: bool,
    target_org_names: set[str] | None,
    doc_processor: DocumentProcessor | None = None,
    export_path: Path | None = None,
) -> None:
    """Migrate passwords.

    Args:
        client: BifrostDocs API client.
        parsed_passwords: List of parsed passwords from CSV.
        state: Migration state for tracking progress.
        reporter: Progress reporter.
        dry_run: If True, don't make API calls.
        target_org_names: If specified, only process passwords for these org names.
        doc_processor: Optional document processor for attachment uploads.
        export_path: Optional export path for attachment uploads.
    """
    # Filter to target orgs if specified
    # Note: organization_id field contains org NAME from IT Glue CSV
    if target_org_names:
        parsed_passwords = [
            pwd for pwd in parsed_passwords
            if pwd.get("organization_id", "") in target_org_names
        ]

    reporter.start_phase(Phase.PASSWORDS, len(parsed_passwords))

    for pwd in parsed_passwords:
        itglue_id = str(pwd.get("id", ""))
        name = pwd.get("name", "")
        org_itglue_id = str(pwd.get("organization_id", ""))

        # Skip if already completed
        if state.is_completed(Phase.PASSWORDS, itglue_id):
            reporter.update_progress(skipped=1, current_item=f"Skipped: {name}")
            continue

        reporter.set_current_item(name)

        # Get the target org UUID
        org_uuid = state.id_mapper.get("organization", org_itglue_id)
        if not org_uuid:
            state.mark_failed(Phase.PASSWORDS, itglue_id, f"Organization {org_itglue_id} not migrated")
            reporter.update_progress(failed=1)
            continue

        try:
            if dry_run:
                # Use placeholder UUID so subsequent phases can validate lookups
                placeholder_uuid = f"dry-run-password-{itglue_id}"
                state.id_mapper.add("password", itglue_id, placeholder_uuid)
                # Note: Don't call state.mark_completed() during dry runs
                reporter.update_progress(succeeded=1, current_item=f"[DRY RUN] Would create: {name}")
            else:
                password_value = pwd.get("password", "")

                # Compute is_enabled from archived field
                archived = pwd.get("archived")
                is_enabled = map_archived_to_is_enabled(archived)

                created = await client.create_password(
                    org_id=org_uuid,
                    name=name,
                    password=password_value or "",
                    username=pwd.get("username"),
                    totp_secret=pwd.get("otp_secret"),
                    url=pwd.get("url"),
                    notes=pwd.get("notes"),
                    metadata={"itglue_id": itglue_id},
                    is_enabled=is_enabled,
                )
                new_uuid = created.get("id")
                if new_uuid:
                    state.id_mapper.add("password", itglue_id, new_uuid)
                state.mark_completed(Phase.PASSWORDS, itglue_id)

                # Upload attachments for this password
                if doc_processor and export_path and new_uuid:
                    try:
                        attachment_count = await doc_processor.upload_entity_attachments(
                            entity_type="passwords",
                            entity_id=itglue_id,
                            org_uuid=org_uuid,
                            our_entity_id=new_uuid,
                            state=state,
                        )
                        if attachment_count > 0:
                            reporter.info(f"Uploaded {attachment_count} attachments for password {name}")
                    except Exception as e:
                        reporter.warning(f"Failed to upload attachments for password {name}: {e}")

                reporter.update_progress(succeeded=1, current_item=f"Created: {name}")

        except APIError as e:
            state.mark_failed(Phase.PASSWORDS, itglue_id, str(e))
            reporter.error(f"Failed to migrate password '{name}': {e}")
            reporter.update_progress(failed=1)

    reporter.complete_phase()


async def _migrate_relationships(
    client: BifrostDocsClient,
    parsed_passwords: list[dict[str, Any]],
    state: MigrationState,
    reporter: Any,
    dry_run: bool,
    target_org_names: set[str] | None,
) -> None:
    """Migrate relationships (embedded passwords -> configurations/assets).

    Args:
        client: BifrostDocs API client.
        parsed_passwords: List of parsed passwords from CSV (with resource links).
        state: Migration state for tracking progress.
        reporter: Progress reporter.
        dry_run: If True, don't make API calls.
        target_org_names: If specified, only process relationships for these org names.
    """
    # Filter passwords that have resource links
    passwords_with_links = [
        pwd for pwd in parsed_passwords
        if pwd.get("resource_type") and pwd.get("resource_id")
    ]

    # Filter to target orgs if specified
    # Note: organization_id field contains org NAME from IT Glue CSV
    if target_org_names:
        passwords_with_links = [
            pwd for pwd in passwords_with_links
            if pwd.get("organization_id", "") in target_org_names
        ]

    reporter.start_phase(Phase.RELATIONSHIPS, len(passwords_with_links))

    for pwd in passwords_with_links:
        itglue_id = str(pwd.get("id", ""))
        name = pwd.get("name", "")
        org_itglue_id = str(pwd.get("organization_id", ""))
        resource_type = pwd.get("resource_type", "").lower()
        resource_id = str(pwd.get("resource_id", ""))

        rel_key = f"{itglue_id}:{resource_type}:{resource_id}"

        # Skip if already completed
        if state.is_completed(Phase.RELATIONSHIPS, rel_key):
            reporter.update_progress(skipped=1, current_item=f"Skipped: {name}")
            continue

        reporter.set_current_item(f"{name} -> {resource_type}")

        # Get the target org UUID
        org_uuid = state.id_mapper.get("organization", org_itglue_id)
        if not org_uuid:
            state.mark_failed(Phase.RELATIONSHIPS, rel_key, f"Organization {org_itglue_id} not migrated")
            reporter.update_progress(failed=1)
            continue

        # Get password UUID
        password_uuid = state.id_mapper.get("password", itglue_id)
        if not password_uuid:
            state.mark_failed(Phase.RELATIONSHIPS, rel_key, f"Password {itglue_id} not migrated")
            reporter.update_progress(failed=1)
            continue

        # Map IT Glue resource type to target entity type
        target_entity_type = None
        target_uuid = None

        if resource_type == "configuration":
            target_entity_type = "configuration"
            target_uuid = state.id_mapper.get("configuration", resource_id)
        elif "asset" in resource_type:
            target_entity_type = "custom_asset"
            target_uuid = state.id_mapper.get("custom_asset", resource_id)

        if not target_uuid or not target_entity_type:
            state.mark_failed(Phase.RELATIONSHIPS, rel_key, f"Target {resource_type}:{resource_id} not migrated")
            reporter.update_progress(failed=1)
            continue

        try:
            if dry_run:
                # Note: Don't call state.mark_completed() during dry runs
                reporter.update_progress(succeeded=1, current_item=f"[DRY RUN] Would link: {name}")
            else:
                await client.create_relationship(
                    org_id=org_uuid,
                    source_type="password",
                    source_id=password_uuid,
                    target_type=target_entity_type,
                    target_id=target_uuid,
                )
                state.mark_completed(Phase.RELATIONSHIPS, rel_key)
                reporter.update_progress(succeeded=1, current_item=f"Linked: {name}")

        except APIError as e:
            # 409 means relationship already exists - that's fine
            if e.status_code == 409:
                state.mark_completed(Phase.RELATIONSHIPS, rel_key)
                reporter.update_progress(succeeded=1, current_item=f"Already linked: {name}")
            else:
                state.mark_failed(Phase.RELATIONSHIPS, rel_key, str(e))
                reporter.error(f"Failed to create relationship for '{name}': {e}")
                reporter.update_progress(failed=1)

    reporter.complete_phase()


async def _execute_migration(
    plan_data: dict[str, Any],
    api_url: str,
    token: str,
    state: MigrationState,
    reporter: Any,
    dry_run: bool,
    target_org: str | None,
    export_path: Path,
    state_file: Path | None,
    skip_attachments: bool = False,
) -> int:
    """Execute the migration.

    Args:
        plan_data: Loaded plan JSON data.
        api_url: BifrostDocs API URL.
        token: API authentication token.
        state: Migration state for tracking progress.
        reporter: Progress reporter.
        dry_run: If True, don't make API calls.
        target_org: If specified, only migrate this organization.
        export_path: Path to the IT Glue export directory.
        state_file: Path to save state file (for resume).

    Returns:
        Exit code (0 for success, non-zero for failures).
    """
    # Parse CSV files from export
    parser = CSVParser()

    # Parse organizations
    parsed_orgs: list[dict[str, Any]] = []
    orgs_file = export_path / "organizations.csv"
    if orgs_file.exists():
        parsed_orgs = parser.parse_organizations(orgs_file)

    # Parse locations
    parsed_locations: list[dict[str, Any]] = []
    locations_file = export_path / "locations.csv"
    if locations_file.exists():
        parsed_locations = parser.parse_locations(locations_file)

    # Parse configurations
    parsed_configs: list[dict[str, Any]] = []
    configs_file = export_path / "configurations.csv"
    if configs_file.exists():
        parsed_configs = parser.parse_configurations(configs_file)

    # Parse documents
    parsed_docs: list[dict[str, Any]] = []
    docs_file = export_path / "documents.csv"
    if docs_file.exists():
        parsed_docs = parser.parse_documents(docs_file)

    # Parse passwords
    parsed_passwords: list[dict[str, Any]] = []
    passwords_file = export_path / "passwords.csv"
    if passwords_file.exists():
        parsed_passwords = parser.parse_passwords(passwords_file)

    # Parse custom assets
    parsed_custom_assets: dict[str, list[dict[str, Any]]] = {}
    custom_types = parser.discover_custom_asset_types(export_path)
    for type_slug in custom_types:
        csv_path = export_path / f"{type_slug}.csv"
        if csv_path.exists():
            _, assets = parser.parse_custom_asset_csv(csv_path, type_slug)
            parsed_custom_assets[type_slug] = assets

    # Get organization mapping from plan
    org_mapping = plan_data.get("organizations", {}).get("mapping", {})

    # Get custom asset schemas from plan
    custom_asset_schemas = plan_data.get("custom_asset_types", {})

    # Determine target org names for filtering
    # Note: IT Glue CSVs use org NAME in the "organization" column, not ID
    target_org_names: set[str] | None = None
    if target_org:
        target_org_names = {target_org}

    async with BifrostDocsClient(base_url=api_url, api_key=token) as client:
        # Create document processor for HTML processing (always needed)
        doc_processor = DocumentProcessor(client=client, export_path=export_path)

        # For attachment uploads, use None if skip_attachments is True
        attachment_export_path = None if skip_attachments else export_path

        # Phase 1: Organizations
        await _migrate_organizations(
            client, parsed_orgs, org_mapping, state, reporter, dry_run, target_org
        )
        if state_file:
            state.save(state_file)

        # Phase 2: Locations
        await _migrate_locations(
            client, parsed_locations, state, reporter, dry_run, target_org_names,
            doc_processor=doc_processor,
            export_path=attachment_export_path,
        )
        if state_file:
            state.save(state_file)

        # Phase 3: Configuration Types
        await _migrate_configuration_types(
            client, parsed_configs, state, reporter, dry_run
        )
        if state_file:
            state.save(state_file)

        # Phase 4: Configurations
        await _migrate_configurations(
            client, parsed_configs, state, reporter, dry_run, target_org_names,
            doc_processor=doc_processor,
            export_path=attachment_export_path,
        )
        if state_file:
            state.save(state_file)

        # Phase 5: Custom Asset Types
        await _migrate_custom_asset_types(
            client, custom_asset_schemas, state, reporter, dry_run
        )
        if state_file:
            state.save(state_file)

        # Phase 6: Custom Assets
        await _migrate_custom_assets(
            client, parsed_custom_assets, custom_asset_schemas, state, reporter, dry_run, target_org_names,
            doc_processor=doc_processor,
            export_path=attachment_export_path,
        )
        if state_file:
            state.save(state_file)

        # Phase 7: Documents
        await _migrate_documents(
            client, parsed_docs, state, reporter, dry_run, target_org_names,
            doc_processor=doc_processor,
            export_path=export_path,
            skip_attachments=skip_attachments,
        )
        if state_file:
            state.save(state_file)

        # Phase 8: Passwords
        await _migrate_passwords(
            client, parsed_passwords, state, reporter, dry_run, target_org_names,
            doc_processor=doc_processor,
            export_path=attachment_export_path,
        )
        if state_file:
            state.save(state_file)

        # Phase 9: Relationships
        await _migrate_relationships(
            client, parsed_passwords, state, reporter, dry_run, target_org_names
        )
        if state_file:
            state.save(state_file)

    # Return exit code based on failures
    total_failed = state.get_total_failed()
    return 1 if total_failed > 0 else 0


def _display_dry_run_summary(plan_data: dict[str, Any], target_org: str | None) -> None:
    """Display a summary of what would be migrated in dry-run mode.

    Args:
        plan_data: Loaded plan JSON data.
        target_org: If specified, only show counts for this organization.
    """
    console.print("[bold yellow]DRY RUN MODE[/bold yellow] - No changes will be made")
    console.print()

    # Organizations
    org_data = plan_data.get("organizations", {})
    if target_org:
        console.print(f"Organizations: 1 (filtered to '{target_org}')")
    else:
        console.print(f"Organizations: {org_data.get('total', 0)}")
        console.print(f"  - Matched: {org_data.get('matched', 0)}")
        console.print(f"  - To create: {org_data.get('to_create', 0)}")

    # Entity counts
    counts = plan_data.get("entity_counts", {})
    console.print(f"Locations: {counts.get('locations', 0)}")
    console.print(f"Configurations: {counts.get('configurations', 0)}")
    console.print(f"Documents: {counts.get('documents', 0)}")
    console.print(f"Passwords: {counts.get('passwords', 0)}")
    console.print(f"Custom Assets: {counts.get('custom_assets', 0)}")

    # Custom asset types
    custom_types = plan_data.get("custom_asset_types", {})
    if custom_types:
        console.print(f"Custom Asset Types: {len(custom_types)}")
        for type_name, info in list(custom_types.items())[:5]:
            console.print(f"  - {info.get('display_name', type_name)}: {info.get('count', 0)} assets")
        if len(custom_types) > 5:
            console.print(f"  ... and {len(custom_types) - 5} more types")

    # Attachment validation
    validation = plan_data.get("attachment_validation")
    if validation:
        console.print()
        console.print("[bold]Attachments to upload:[/bold]")
        matched = validation.get("matched", {})
        for entity_type, stats in matched.items():
            count = stats.get("count", 0)
            size = stats.get("formatted_size", "0 B")
            console.print(f"  {entity_type}: {count} files ({size})")

        total_files = validation.get("total_matched_files", 0)
        total_size = validation.get("formatted_matched_size", "0 B")
        console.print(f"  [bold]Total: {total_files} files ({total_size})[/bold]")

        # Orphan warnings
        orphaned = validation.get("orphaned", {})
        if orphaned:
            total_orphans = validation.get("total_orphaned_folders", 0)
            console.print()
            console.print(
                f"[yellow]⚠️  Orphaned attachments ({total_orphans} folders, "
                f"no matching entity):[/yellow]"
            )
            for entity_type, ids in orphaned.items():
                ids_preview = ", ".join(ids[:5])
                if len(ids) > 5:
                    ids_preview += f", ... ({len(ids)} total)"
                console.print(f"    {entity_type}: {ids_preview}")

    console.print()


@app.command()
def run(
    plan: Annotated[
        Path,
        typer.Option(
            "--plan",
            "-p",
            help="Path to the migration plan JSON file",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ],
    org: Annotated[
        str | None,
        typer.Option(
            "--org",
            "-o",
            help="Migrate a single organization by name",
        ),
    ] = None,
    all_orgs: Annotated[
        bool,
        typer.Option(
            "--all",
            "-a",
            help="Migrate all organizations",
        ),
    ] = False,
    api_url: Annotated[
        str | None,
        typer.Option(
            "--api-url",
            "-u",
            help="BifrostDocs API URL (overrides plan file)",
            envvar="BIFROST_API_URL",
        ),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            "-t",
            help="BifrostDocs API authentication token",
            envvar="BIFROST_API_TOKEN",
        ),
    ] = None,
    state_file: Annotated[
        Path | None,
        typer.Option(
            "--state-file",
            "-s",
            help="State file for resume support",
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-n",
            help="Show what would be done without making changes",
        ),
    ] = False,
    clear_failures: Annotated[
        bool,
        typer.Option(
            "--clear-failures",
            help="Clear previous failures to allow retry",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Show detailed progress",
        ),
    ] = False,
    skip_attachments: Annotated[
        bool,
        typer.Option(
            "--skip-attachments",
            help="Skip attachment uploads for faster testing",
        ),
    ] = False,
) -> None:
    """Execute migration using a plan file.

    Run the actual migration based on a previously generated plan file.
    You must specify either --org to migrate a single organization or
    --all to migrate all organizations.

    Use --state-file to enable resume support. If the migration is
    interrupted, re-run with the same state file to continue.

    Use --dry-run to preview what would be migrated without making
    any API calls.
    """
    # Configure logging based on verbose flag
    if verbose:
        logging.basicConfig(
            level=logging.INFO,
            format="%(name)s - %(levelname)s - %(message)s",
        )

    console.print(Panel("IT Glue Migration - Run", style="bold blue"))
    console.print()

    # Validate inputs
    if not org and not all_orgs:
        error_console.print(
            "[red]Error:[/red] You must specify either --org <name> or --all"
        )
        raise typer.Exit(1)

    if org and all_orgs:
        error_console.print(
            "[red]Error:[/red] Cannot specify both --org and --all"
        )
        raise typer.Exit(1)

    # Load and validate plan file
    try:
        with plan.open("r", encoding="utf-8") as f:
            plan_data = json.load(f)
    except json.JSONDecodeError as e:
        error_console.print(f"[red]Error:[/red] Invalid plan file JSON: {e}")
        raise typer.Exit(1) from None
    except OSError as e:
        error_console.print(f"[red]Error:[/red] Failed to read plan file: {e}")
        raise typer.Exit(1) from None

    # Validate plan version
    plan_version = plan_data.get("version")
    if plan_version != PLAN_VERSION:
        error_console.print(
            f"[red]Error:[/red] Plan file version {plan_version} is not compatible "
            f"with this tool (expected version {PLAN_VERSION})"
        )
        raise typer.Exit(1)

    # Validate export path from plan
    export_path_str = plan_data.get("export_path")
    if not export_path_str:
        error_console.print(
            "[red]Error:[/red] Plan file missing export_path"
        )
        raise typer.Exit(1)

    export_path = Path(export_path_str)
    if not export_path.exists():
        error_console.print(
            f"[red]Error:[/red] Export path does not exist: {export_path}"
        )
        raise typer.Exit(1)

    # Determine API URL (command line overrides plan)
    effective_api_url = api_url or plan_data.get("api_url")
    if not effective_api_url:
        error_console.print(
            "[red]Error:[/red] No API URL specified. Use --api-url, set BIFROST_API_URL, or ensure plan file has api_url."
        )
        raise typer.Exit(1)

    # Validate token
    if not token:
        error_console.print(
            "[red]Error:[/red] No API token specified. Use --token or set BIFROST_API_TOKEN."
        )
        raise typer.Exit(1)

    # Verify org exists in plan if specified
    if org:
        org_mapping = plan_data.get("organizations", {}).get("mapping", {})
        if org not in org_mapping:
            error_console.print(
                f"[red]Error:[/red] Organization '{org}' not found in plan file"
            )
            raise typer.Exit(1)

    # Display configuration
    console.print(f"[bold]Plan file:[/bold] {plan}")
    console.print(f"[bold]API URL:[/bold] {effective_api_url}")
    console.print(f"[bold]Export path:[/bold] {export_path}")

    if org:
        console.print(f"[bold]Target:[/bold] Single organization: {org}")
    else:
        total_orgs = plan_data.get("organizations", {}).get("total", 0)
        console.print(f"[bold]Target:[/bold] All {total_orgs} organizations")

    if state_file:
        console.print(f"[bold]State file:[/bold] {state_file}")

    if dry_run:
        console.print("[bold]Mode:[/bold] [yellow]DRY RUN[/yellow]")

    console.print()

    # Verify API connectivity (skip in dry-run mode)
    if not dry_run:
        console.print("Verifying API connectivity...")
        connected = asyncio.run(_verify_api_connectivity(effective_api_url, token))
        if not connected:
            error_console.print(
                "[red]Error:[/red] Failed to connect to API. Check URL and token."
            )
            raise typer.Exit(1)
        console.print("[green]API connection verified[/green]")
        console.print()

    # Load or create migration state
    state: MigrationState
    if state_file and state_file.exists():
        console.print(f"Loading existing state from {state_file}...")
        try:
            state = MigrationState.load(state_file)
            console.print(
                f"[green]Resumed migration:[/green] "
                f"{state.get_total_completed()} completed, "
                f"{state.get_total_failed()} failed"
            )

            if clear_failures:
                cleared = state.clear_all_failures()
                if cleared > 0:
                    console.print(f"[yellow]Cleared {cleared} previous failures for retry[/yellow]")
                    state.save(state_file)

        except MigrationStateError as e:
            error_console.print(f"[red]Error:[/red] Failed to load state file: {e}")
            raise typer.Exit(1) from None
    else:
        state = MigrationState(
            export_path=str(export_path),
            api_url=effective_api_url,
        )

    console.print()

    # Display dry-run summary if applicable
    if dry_run:
        _display_dry_run_summary(plan_data, org)

    # Create progress reporter
    reporter = create_progress_reporter(
        console=console,
        verbose=verbose,
        simple=not console.is_terminal,  # Live progress for interactive, simple for pipes
    )

    # Execute migration
    with reporter:
        exit_code = asyncio.run(
            _execute_migration(
                plan_data=plan_data,
                api_url=effective_api_url,
                token=token,
                state=state,
                reporter=reporter,
                dry_run=dry_run,
                target_org=org,
                export_path=export_path,
                state_file=state_file,
                skip_attachments=skip_attachments,
            )
        )

    # Display final summary
    reporter.print_final_summary()

    # Save final state
    if state_file:
        state.save(state_file)
        console.print()
        console.print(f"State saved to: {state_file}")

    # Display completion message
    console.print()
    if exit_code == 0:
        if dry_run:
            console.print(
                Panel(
                    "[green]Dry run complete![/green]\n\n"
                    "No changes were made. Run without --dry-run to execute the migration.",
                    title="Done",
                    border_style="green",
                )
            )
        else:
            console.print(
                Panel(
                    "[green]Migration complete![/green]",
                    title="Done",
                    border_style="green",
                )
            )
    else:
        total_failed = state.get_total_failed()
        console.print(
            Panel(
                f"[yellow]Migration completed with {total_failed} failures.[/yellow]\n\n"
                f"Review the errors above and use --state-file with --clear-failures to retry.",
                title="Warning",
                border_style="yellow",
            )
        )

    sys.exit(exit_code)


def _display_sync_plan_summary(
    org_name: str,
    plan: SyncPlan,
) -> None:
    """Display a summary of the sync plan to the console.

    Args:
        org_name: Organization name being synced.
        plan: The sync plan to summarize.
    """
    console.print()
    console.print(f"[bold]Sync Plan for '{org_name}':[/bold]")
    console.print()

    # Build summary table
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Entity Type")
    table.add_column("To Create", justify="right")
    table.add_column("To Update", justify="right")
    table.add_column("Existing", justify="right")

    # Count entities (name, to_create, to_update, existing)
    entity_counts = [
        ("Organizations", len(plan.organizations.to_create), len(plan.organizations.to_update), len(plan.organizations.existing)),
        ("Configuration Types", len(plan.config_types.to_create), len(plan.config_types.to_update), len(plan.config_types.existing)),
        ("Configuration Statuses", len(plan.config_statuses.to_create), len(plan.config_statuses.to_update), len(plan.config_statuses.existing)),
        ("Custom Asset Types", len(plan.custom_asset_types.to_create), len(plan.custom_asset_types.to_update), len(plan.custom_asset_types.existing)),
        ("Locations", len(plan.locations.to_create), len(plan.locations.to_update), len(plan.locations.existing)),
        ("Configurations", len(plan.configurations.to_create), len(plan.configurations.to_update), len(plan.configurations.existing)),
        ("Custom Assets", len(plan.custom_assets.to_create), len(plan.custom_assets.to_update), len(plan.custom_assets.existing)),
        ("Documents", len(plan.documents.to_create), len(plan.documents.to_update), len(plan.documents.existing)),
        ("Passwords", len(plan.passwords.to_create), len(plan.passwords.to_update), len(plan.passwords.existing)),
        ("Relationships", len(plan.relationships.to_create), 0, len(plan.relationships.existing)),  # Relationships don't have to_update
    ]

    for name, to_create, to_update, existing in entity_counts:
        create_style = "green" if to_create > 0 else ""
        update_style = "yellow" if to_update > 0 else ""
        table.add_row(
            name,
            f"[{create_style}]{to_create}[/{create_style}]" if to_create > 0 else str(to_create),
            f"[{update_style}]{to_update}[/{update_style}]" if to_update > 0 else str(to_update),
            str(existing),
        )

    console.print(table)


def _display_sync_result(result: SyncResult) -> None:
    """Display sync execution results.

    Args:
        result: The sync result to display.
    """
    console.print()
    console.print("[bold]Sync Results:[/bold]")
    console.print()

    # Build results table
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Entity Type")
    table.add_column("Created", justify="right")
    table.add_column("Skipped", justify="right")
    table.add_column("Failed", justify="right")

    entity_types = [
        "config_types",
        "config_statuses",
        "custom_asset_types",
        "locations",
        "configurations",
        "custom_assets",
        "documents",
        "passwords",
        "relationships",
    ]

    for entity_type in entity_types:
        created = result.created.get(entity_type, 0)
        skipped = result.skipped.get(entity_type, 0)
        failed = result.failed.get(entity_type, 0)

        # Format with colors
        created_str = f"[green]{created}[/green]" if created > 0 else str(created)
        failed_str = f"[red]{failed}[/red]" if failed > 0 else str(failed)

        # Convert snake_case to Title Case
        display_name = entity_type.replace("_", " ").title()
        table.add_row(display_name, created_str, str(skipped), failed_str)

    console.print(table)

    # Display errors if any
    if result.errors:
        console.print()
        console.print("[bold red]Errors:[/bold red]")
        for error in result.errors[:10]:  # Limit to first 10 errors
            console.print(f"  - {error}")
        if len(result.errors) > 10:
            console.print(f"  ... and {len(result.errors) - 10} more errors")


def _build_attachment_validation_summary(
    export_path: Path,
    *,
    configurations: list[dict[str, Any]],
    locations: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    passwords: list[dict[str, Any]],
    custom_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build read-only attachment validation details for reconciliation."""
    entities_to_migrate: dict[str, set[str]] = {
        "configurations": {str(item.get("id", "")) for item in configurations},
        "locations": {str(item.get("id", "")) for item in locations},
        "documents": {str(item.get("id", "")) for item in documents},
        "passwords": {str(item.get("id", "")) for item in passwords},
    }

    for asset in custom_assets:
        type_slug = str(asset.get("_type_slug") or asset.get("asset_type") or "")
        asset_id = str(asset.get("id", ""))
        if type_slug and asset_id:
            entities_to_migrate.setdefault(type_slug, set()).add(asset_id)

    validation = validate_attachments(export_path, entities_to_migrate)
    image_references = collect_embedded_image_references(export_path, documents)
    image_validation = verify_embedded_images(image_references)
    summary = validation.to_dict()
    summary.pop("orphaned", None)
    summary.pop("total_orphaned_folders", None)
    summary["orphaned_scope"] = "not_reported_per_org"
    summary["failure_categories"] = {
        BROKEN_EMBEDDED_IMAGE: len(image_validation.failures),
    }
    summary["embedded_images"] = {
        "expected_count": image_validation.expected_count,
        "present_count": image_validation.present_count,
        "failure_count": len(image_validation.failures),
        "failures": [failure.to_dict() for failure in image_validation.failures],
    }
    return summary


async def _run_sync(
    export_path: Path,
    api_url: str,
    token: str,
    target_org: str | None,
    _all_orgs: bool,  # Unused - if target_org is None, we sync all
    dry_run: bool,
    update_existing: bool,
    skip_attachments: bool = False,
    reconciliation_output: Path | None = None,
) -> int:
    """Run the sync operation.

    Args:
        export_path: Path to IT Glue export directory.
        api_url: BifrostDocs API URL.
        token: API authentication token.
        target_org: Organization name to sync (if not all).
        all_orgs: Whether to sync all organizations.
        dry_run: Preview changes without making them.
        update_existing: Update entities that already exist.
        skip_attachments: Skip attachment uploads for faster testing.
        reconciliation_output: Optional path to write reconciliation JSON.

    Returns:
        Exit code (0 for success, non-zero for failures).
    """
    # Validate export path
    validation = _validate_export_path(export_path)

    # Parse all CSV files
    parser = CSVParser()
    console.print("[bold]Parsing CSV files...[/bold]")
    parsed = _parse_export_with_progress(parser, export_path, validation)

    console.print(f"  [green]Parsed {len(parsed.organizations)} organizations[/green]")
    console.print()

    # Build password field map from Cell passwords and update field definitions
    password_field_map = build_password_field_map(parsed.passwords)
    if password_field_map.global_password_fields:
        console.print(f"[bold]Detected password fields:[/bold] {password_field_map.global_password_fields}")
    _apply_password_field_types(parsed.field_definitions, password_field_map)
    console.print()

    # Determine which organizations to sync
    if target_org:
        orgs_to_sync = [o for o in parsed.organizations if o.get("name") == target_org]
        if not orgs_to_sync:
            error_console.print(f"[red]Error:[/red] Organization '{target_org}' not found in export")
            return 1
    else:
        orgs_to_sync = parsed.organizations

    console.print(f"[bold]Syncing {len(orgs_to_sync)} organization(s)...[/bold]")
    console.print()

    total_result = SyncResult()
    report = (
        ReconciliationReport.create(
            export_path=export_path,
            target=target_org or "all",
            dry_run=dry_run,
        )
        if reconciliation_output
        else None
    )

    async with BifrostDocsClient(base_url=api_url, api_key=token) as client:
        fetcher = StateFetcher(client)

        # First, get all organizations to resolve org name -> UUID mapping
        console.print("Fetching existing organizations...")
        all_orgs_state = await fetcher.fetch_all_orgs()
        console.print(f"  [green]Found {len(all_orgs_state.org_by_name)} organizations[/green]")
        console.print()

        # Diff organizations to find which need to be created
        org_differ = SyncDiffer(all_orgs_state)
        org_plan = org_differ.diff_organizations(orgs_to_sync)

        # Display org plan if any need to be created
        if org_plan.to_create:
            console.print(f"[bold]Organizations to create: {len(org_plan.to_create)}[/bold]")
            for org_to_create in org_plan.to_create:
                console.print(f"  [green]+ {org_to_create.get('name')}[/green]")
            console.print(f"[dim]Organizations already exist: {len(org_plan.existing)}[/dim]")
            console.print()

            if not dry_run:
                # Create missing organizations first
                console.print("Creating missing organizations...")
                org_sync_plan = SyncPlan(organizations=org_plan)
                org_executor = SyncExecutor(client, org_id="", dry_run=False)  # type: ignore[arg-type]
                org_result = await org_executor.execute(org_sync_plan)

                # Merge org creation results into total
                for key, value in org_result.created.items():
                    total_result.created[key] = total_result.created.get(key, 0) + value
                for key, value in org_result.failed.items():
                    total_result.failed[key] = total_result.failed.get(key, 0) + value
                total_result.errors.extend(org_result.errors)

                if org_result.created.get("organizations", 0) > 0:
                    console.print(f"  [green]Created {org_result.created.get('organizations', 0)} organization(s)[/green]")

                if org_result.failed.get("organizations", 0) > 0:
                    console.print(f"  [red]Failed {org_result.failed.get('organizations', 0)} organization(s)[/red]")

                # Refresh org state after creating new organizations
                console.print("Refreshing organization state...")
                all_orgs_state = await fetcher.fetch_all_orgs()
                console.print(f"  [green]Found {len(all_orgs_state.org_by_name)} organizations[/green]")
                console.print()

        for org in orgs_to_sync:
            org_name = org.get("name", "")
            org_itglue_id = str(org.get("id", ""))

            console.print(f"[bold cyan]Processing organization: {org_name}[/bold cyan]")
            console.print(f"  [dim]ITGlue org ID: {org_itglue_id}[/dim]")

            # Resolve org to UUID
            org_uuid = all_orgs_state.org_by_itglue_id.get(org_itglue_id)
            if not org_uuid:
                org_uuid = all_orgs_state.org_by_name.get(org_name.lower())

            if not org_uuid:
                if dry_run:
                    # In dry-run mode, use a placeholder UUID for new orgs
                    org_uuid = f"dry-run-{org_itglue_id}"
                    console.print("  [yellow]Organization is new (will be created)[/yellow]")
                    # Create empty state since nothing exists yet
                    state = ExistingState()
                else:
                    # This should only happen if org creation failed above
                    message = (
                        "Organization not found in API "
                        "(creation may have failed), skipping"
                    )
                    console.print(f"  [red]{message}[/red]")
                    if report:
                        report.organizations.append(
                            OrganizationReconciliation(
                                name=org_name,
                                itglue_id=org_itglue_id,
                                bifrost_id=None,
                                dry_run=dry_run,
                                entities=build_plan_counts(SyncPlan()),
                                errors=[message],
                            )
                        )
                    console.print()
                    continue
            else:
                # Fetch existing state for this org
                console.print("  Fetching existing state...")
                state = await fetcher.fetch_for_org(org_uuid)

            # Debug: show state summary
            console.print("  [dim]API state:[/dim]")
            console.print(f"    [dim]Config types: {len(state.config_type_by_name)}[/dim]")
            console.print(f"    [dim]Config statuses: {len(state.config_status_by_name)}[/dim]")
            console.print(f"    [dim]Custom asset types: {len(state.custom_asset_type_by_name)}[/dim]")
            console.print(f"    [dim]Locations by itglue_id: {len(state.location_by_itglue_id)}[/dim]")
            console.print(f"    [dim]Documents by itglue_id: {len(state.document_by_itglue_id)}[/dim]")
            console.print(f"    [dim]Configs by itglue_id: {len(state.config_by_itglue_id)}[/dim]")
            console.print(f"    [dim]Passwords by itglue_id: {len(state.password_by_itglue_id)}[/dim]")
            console.print(f"    [dim]Custom assets by itglue_id: {len(state.custom_asset_by_itglue_id)}[/dim]")
            console.print(f"    [dim]Relationships tracked: {len(state.relationships)}[/dim]")

            # Debug: show sample itglue_ids
            if state.document_by_itglue_id:
                sample_api_doc_ids = list(state.document_by_itglue_id.keys())[:5]
                console.print(f"    [dim]Sample API document itglue_ids: {sample_api_doc_ids}[/dim]")

            # Filter CSV data to this org
            (
                org_configs,
                org_locations,
                org_documents,
                org_passwords,
                org_custom_assets,
            ) = _filter_org_records(parsed, org_itglue_id, org_name)

            # Debug: show filter results
            console.print(f"  [dim]CSV items for org (matching '{org_itglue_id}' or '{org_name}'):[/dim]")
            console.print(f"    [dim]Configurations: {len(org_configs)} / {len(parsed.configurations)}[/dim]")
            console.print(f"    [dim]Locations: {len(org_locations)} / {len(parsed.locations)}[/dim]")
            console.print(f"    [dim]Documents: {len(org_documents)} / {len(parsed.documents)}[/dim]")
            console.print(f"    [dim]Passwords: {len(org_passwords)} / {len(parsed.passwords)}[/dim]")

            # Show sample organization_id values from documents to debug filtering
            if parsed.documents:
                sample_org_ids = {str(d.get("organization_id", "")) for d in parsed.documents[:20]}
                console.print(f"    [dim]Sample organization_id values in documents.csv: {sample_org_ids}[/dim]")

            # Debug: show sample CSV document IDs for comparison
            if org_documents:
                sample_csv_doc_ids = [str(d.get("id", "")) for d in org_documents[:5]]
                console.print(f"    [dim]Sample CSV document ids: {sample_csv_doc_ids}[/dim]")

            attachment_summary = (
                _build_attachment_validation_summary(
                    export_path,
                    configurations=org_configs,
                    locations=org_locations,
                    documents=org_documents,
                    passwords=org_passwords,
                    custom_assets=org_custom_assets,
                )
                if report
                else None
            )

            # Create differ and generate plan
            differ = SyncDiffer(state)

            # Validate data quality and display warnings
            warnings = differ.validate_data_quality(
                orgs_to_sync, org_documents, org_passwords
            )
            if warnings:
                console.print("[yellow]Data Quality Warnings:[/yellow]")
                for warning in warnings:
                    console.print(f"  [yellow]⚠️  {warning}[/yellow]")
                console.print()

            # Debug: show custom asset type names being compared
            csv_cat_names = set()
            for asset in org_custom_assets:
                type_slug = asset.get("asset_type") or asset.get("_type_slug")
                if type_slug:
                    # Convert slug to display name for comparison
                    display_name = slugify_to_display_name(type_slug)
                    csv_cat_names.add(display_name)
            api_cat_names = set(state.custom_asset_type_by_name.keys())
            console.print(f"  [dim]Custom asset types in CSV (as display names): {sorted(csv_cat_names)}[/dim]")
            console.print(f"  [dim]Custom asset types in API: {sorted(api_cat_names)}[/dim]")
            # Show which CSV types are NOT in API
            missing_in_api = {name for name in csv_cat_names if name.lower() not in api_cat_names}
            if missing_in_api:
                console.print(f"  [dim]CSV types NOT in API (will create): {sorted(missing_in_api)}[/dim]")

            # Build organization plan for this specific org
            this_org_plan = EntityPlan()
            if any(o.get("name") == org_name for o in org_plan.to_create):
                this_org_plan.to_create = [org]
            elif any(o.get("name") == org_name for o in org_plan.existing):
                this_org_plan.existing = [org]

            plan = SyncPlan(
                organizations=this_org_plan,
                config_types=differ.diff_config_types(org_configs),
                config_statuses=differ.diff_config_statuses(org_configs),
                custom_asset_types=differ.diff_custom_asset_types(
                    org_custom_assets, parsed.field_definitions
                ),
                locations=differ.diff_locations(org_locations),
                configurations=differ.diff_configurations(org_configs),
                custom_assets=differ.diff_custom_assets(org_custom_assets),
                documents=differ.diff_documents(org_documents),
                passwords=differ.diff_passwords(org_passwords),
                relationships=differ.diff_relationships(org_passwords),
            )

            # Display plan summary
            _display_sync_plan_summary(org_name, plan)
            org_counts = build_plan_counts(plan)
            org_errors: list[str] = []

            # Execute if not dry-run
            if dry_run:
                console.print()
                console.print("[yellow]DRY RUN - No changes made[/yellow]")
                if report:
                    doc_processor: DocumentProcessor | None = None
                    if export_path:
                        doc_processor = DocumentProcessor(client, export_path)
                    executor = SyncExecutor(
                        client,  # type: ignore[arg-type]
                        org_id=org_uuid,
                        dry_run=True,
                        state=state,
                        update_existing=update_existing,
                        doc_processor=doc_processor,
                        export_path=export_path,
                        skip_attachments=True,
                    )
                    result = await executor.execute(plan)
                    total_result.errors.extend(result.errors)
                    org_errors = list(result.errors)
                    org_counts = apply_result_counts(org_counts, result)
                    relationship_summary = (
                        result.relationship_summary
                        if result.relationship_summary
                        else None
                    )
            else:
                console.print()
                console.print("Executing sync...")

                # Create progress reporter for live updates
                reporter = create_progress_reporter(console=console, verbose=False)

                # Create document processor for HTML processing and attachments
                doc_processor: DocumentProcessor | None = None
                if export_path:
                    doc_processor = DocumentProcessor(client, export_path)

                executor = SyncExecutor(
                    client,  # type: ignore[arg-type]
                    org_id=org_uuid,
                    dry_run=False,
                    state=state,
                    update_existing=update_existing,
                    reporter=reporter,
                    doc_processor=doc_processor,
                    export_path=export_path,
                    skip_attachments=skip_attachments,
                )

                # Use context manager to start/stop the live display
                with reporter:
                    result = await executor.execute(plan)

                # Merge results
                for key, value in result.created.items():
                    total_result.created[key] = total_result.created.get(key, 0) + value
                for key, value in result.updated.items():
                    total_result.updated[key] = total_result.updated.get(key, 0) + value
                for key, value in result.skipped.items():
                    total_result.skipped[key] = total_result.skipped.get(key, 0) + value
                for key, value in result.failed.items():
                    total_result.failed[key] = total_result.failed.get(key, 0) + value
                total_result.errors.extend(result.errors)
                org_errors = list(result.errors)
                org_counts = apply_result_counts(org_counts, result)
                relationship_summary = (
                    result.relationship_summary if result.relationship_summary else None
                )

                _display_sync_result(result)

            if report:
                report.organizations.append(
                    OrganizationReconciliation(
                        name=org_name,
                        itglue_id=org_itglue_id,
                        bifrost_id=org_uuid,
                        dry_run=dry_run,
                        entities=org_counts,
                        warnings=warnings,
                        errors=org_errors,
                        attachment_summary=attachment_summary,
                        relationship_summary=relationship_summary,
                    )
                )
            console.print()

    # Display total results if multiple orgs
    if len(orgs_to_sync) > 1 and not dry_run:
        console.print("[bold]Total Results Across All Organizations:[/bold]")
        _display_sync_result(total_result)

    # Determine exit code
    total_failed = sum(total_result.failed.values())
    if reconciliation_output and report:
        report.errors.extend(total_result.errors)
        report.write_json(reconciliation_output)
        console.print(
            f"[green]Reconciliation report written to {reconciliation_output}[/green]"
        )
    return 1 if total_failed > 0 else 0


@app.command()
def sync(
    export_path: Annotated[
        Path,
        typer.Option(
            "--export-path",
            "-e",
            help="Path to the IT Glue export directory",
            exists=False,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ],
    api_url: Annotated[
        str,
        typer.Option(
            "--api-url",
            "-u",
            help="BifrostDocs API URL (e.g., https://api.example.com)",
            envvar="BIFROST_API_URL",
        ),
    ],
    token: Annotated[
        str,
        typer.Option(
            "--token",
            "-t",
            help="BifrostDocs API authentication token",
            envvar="BIFROST_API_TOKEN",
        ),
    ],
    org: Annotated[
        str | None,
        typer.Option(
            "--org",
            "-o",
            help="Sync a single organization by name",
        ),
    ] = None,
    all_orgs: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Sync all organizations",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-n",
            help="Preview changes without making them",
        ),
    ] = False,
    update_existing: Annotated[
        bool,
        typer.Option(
            "--update-existing",
            help="Update entities that already exist",
        ),
    ] = False,
    skip_attachments: Annotated[
        bool,
        typer.Option(
            "--skip-attachments",
            help="Skip attachment uploads for faster testing",
        ),
    ] = False,
    reconciliation_output: Annotated[
        Path | None,
        typer.Option(
            "--reconciliation-output",
            help="Write a JSON reconciliation report to this path",
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
    itglue_api_key: Annotated[
        str | None,
        typer.Option(
            "--itglue-api-key",
            help="IT Glue API key for accurate password field detection",
            envvar="IT_GLUE_API_KEY",
        ),
    ] = None,
) -> None:
    """Sync IT Glue export data with existing BifrostDocs data.

    This command compares the IT Glue export with existing data in BifrostDocs
    and creates only the missing entities. Unlike the 'run' command which uses
    a plan file and state tracking, 'sync' fetches current state from the API
    and diffs against the CSV export.

    Use --org to sync a single organization or --all to sync all organizations
    in the export.

    Use --dry-run to preview what would be created without making changes.
    """
    # Reserved for future use (relationship mapping)
    _ = itglue_api_key

    console.print(Panel("IT Glue Migration - Sync", style="bold blue"))
    console.print()

    # Validate inputs
    if not org and not all_orgs:
        error_console.print(
            "[red]Error:[/red] You must specify either --org <name> or --all"
        )
        raise typer.Exit(1)

    if org and all_orgs:
        error_console.print(
            "[red]Error:[/red] Cannot specify both --org and --all"
        )
        raise typer.Exit(1)

    # Display configuration
    console.print(f"[bold]Export path:[/bold] {export_path}")
    console.print(f"[bold]API URL:[/bold] {api_url}")

    if org:
        console.print(f"[bold]Target:[/bold] Single organization: {org}")
    else:
        console.print("[bold]Target:[/bold] All organizations")

    if dry_run:
        console.print("[bold]Mode:[/bold] [yellow]DRY RUN[/yellow]")

    if update_existing:
        console.print("[bold]Update existing:[/bold] Yes")

    if skip_attachments:
        console.print("[bold]Skip attachments:[/bold] Yes")

    console.print()

    # Run the sync
    exit_code = asyncio.run(
        _run_sync(
            export_path=export_path,
            api_url=api_url,
            token=token,
            target_org=org,
            _all_orgs=all_orgs,
            dry_run=dry_run,
            update_existing=update_existing,
            skip_attachments=skip_attachments,
            reconciliation_output=reconciliation_output,
        )
    )

    # Display completion message
    console.print()
    if exit_code == 0:
        if dry_run:
            console.print(
                Panel(
                    "[green]Dry run complete![/green]\n\n"
                    "No changes were made. Run without --dry-run to execute the sync.",
                    title="Done",
                    border_style="green",
                )
            )
        else:
            console.print(
                Panel(
                    "[green]Sync complete![/green]",
                    title="Done",
                    border_style="green",
                )
            )
    else:
        console.print(
            Panel(
                "[yellow]Sync completed with failures.[/yellow]\n\n"
                "Review the errors above.",
                title="Warning",
                border_style="yellow",
            )
        )

    sys.exit(exit_code)


def _check_url_reachable(url: str, timeout_seconds: float = 10.0) -> bool:
    """Check whether a migrated URL is reachable without downloading it.

    Read-only: issues HEAD, falling back to GET for servers that reject HEAD.

    Args:
        url: Absolute URL to check.
        timeout_seconds: Per-request timeout.

    Returns:
        True when the URL responds with a success status.
    """
    try:
        response = httpx.head(url, follow_redirects=True, timeout=timeout_seconds)
        if response.status_code in (403, 405, 501):
            with httpx.stream(
                "GET", url, follow_redirects=True, timeout=timeout_seconds
            ) as stream:
                return stream.status_code < 400
        return response.status_code < 400
    except Exception:
        return False


def _invert_entity_identities(
    state: ExistingState,
) -> dict[str, tuple[str, str]]:
    """Map migrated entity UUIDs back to (export entity type, IT Glue ID).

    Custom-asset type slugs are normalized to ``custom_assets`` to match the
    comparison vocabulary; per-asset precision is preserved via IT Glue ID.
    """
    inverted: dict[str, tuple[str, str]] = {}
    for export_type, mapping in (
        ("configurations", state.config_by_itglue_id),
        ("locations", state.location_by_itglue_id),
        ("documents", state.document_by_itglue_id),
        ("passwords", state.password_by_itglue_id),
        ("custom_assets", state.custom_asset_by_itglue_id),
    ):
        for itglue_id, uuid in mapping.items():
            inverted[str(uuid)] = (export_type, str(itglue_id))
    return inverted


async def _verify_org_fidelity(
    fetcher: StateFetcher,
    export_path: Path,
    org_name: str,
    org_itglue_id: str,
    org_uuid: str,
    state: ExistingState,
    org_configs: list[dict[str, Any]],
    org_locations: list[dict[str, Any]],
    org_documents: list[dict[str, Any]],
    org_passwords: list[dict[str, Any]],
    org_custom_assets: list[dict[str, Any]],
    url_checker: Any | None,
) -> dict[str, Any]:
    """Run read-only fidelity checks for one organization (GET/HEAD only)."""
    warnings: list[str] = []

    # --- Attachments: export files vs migrated records ---
    core_ids = {
        "configurations": {str(item.get("id", "")) for item in org_configs},
        "locations": {str(item.get("id", "")) for item in org_locations},
        "documents": {str(item.get("id", "")) for item in org_documents},
        "passwords": {str(item.get("id", "")) for item in org_passwords},
    }
    custom_ids = {str(asset.get("id", "")) for asset in org_custom_assets}

    scanner = AttachmentScanner()
    all_attachments = scanner.get_all_attachments(export_path)
    expected: set[tuple[str, str, str]] = set()
    for (folder_type, entity_id), paths in all_attachments.items():
        entity_id = str(entity_id)
        if folder_type in core_ids:
            if entity_id not in core_ids[folder_type]:
                continue
            export_type = folder_type
        else:
            if entity_id not in custom_ids:
                continue
            export_type = "custom_assets"
        for path in paths:
            expected.add((export_type, entity_id, path.name))

    identities = _invert_entity_identities(state)
    migrated: set[tuple[str, str, str]] = set()
    unresolved: list[MigratedAttachment] = []
    skipped_records = 0
    try:
        records = await fetcher.list_all_attachments(org_uuid)
    except APIError as e:
        warnings.append(f"Could not list migrated attachments: {e}")
        records = []
    for record in records:
        filename = record.get("filename")
        entity_uuid = record.get("entity_id")
        if not filename or not entity_uuid:
            skipped_records += 1
            continue
        identity = identities.get(str(entity_uuid))
        if identity is None:
            unresolved.append(
                MigratedAttachment(
                    attachment_id=str(record.get("id", "")),
                    entity_type=str(record.get("entity_type", "")),
                    entity_id=str(entity_uuid),
                    filename=str(filename),
                )
            )
        else:
            export_type, itglue_id = identity
            migrated.add((export_type, itglue_id, str(filename)))
    if skipped_records:
        warnings.append(
            f"Skipped {skipped_records} migrated attachment records "
            "with missing filename or entity reference."
        )
    attachment_result = reconcile_migrated_attachments(expected, migrated, unresolved)

    # --- Embedded images: export files, then migrated document content ---
    image_references = collect_embedded_image_references(export_path, org_documents)
    export_image_result = verify_embedded_images(image_references)
    refs_by_doc: dict[str, int] = {}
    for ref in image_references:
        refs_by_doc[ref.document_id] = refs_by_doc.get(ref.document_id, 0) + 1

    image_failures = list(export_image_result.failures)
    documents_checked = 0
    present_total = 0
    for doc in org_documents:
        doc_id = str(doc.get("id", ""))
        doc_name = str(doc.get("name", doc_id))
        migrated_uuid = state.document_by_itglue_id.get(doc_id)
        if not migrated_uuid:
            warnings.append(
                f"Document '{doc_name}' (IT Glue ID {doc_id}) not found in "
                "the API; migrated image check skipped."
            )
            continue
        try:
            migrated_doc = await fetcher.client.get_document(org_uuid, migrated_uuid)
        except APIError as e:
            warnings.append(
                f"Could not fetch migrated document '{doc_name}': {e}"
            )
            continue
        documents_checked += 1
        content = str(migrated_doc.get("content", "") or "")
        result = verify_migrated_document_images(
            document_id=doc_id,
            document_name=doc_name,
            expected_count=refs_by_doc.get(doc_id, 0),
            image_urls=extract_markdown_image_urls(content),
            url_checker=url_checker,
        )
        present_total += result.present_count
        image_failures.extend(result.failures)

    embedded_section = {
        "expected_count": export_image_result.expected_count,
        "migrated_documents_checked": documents_checked,
        "present_count": present_total,
        "failure_count": len(image_failures),
        "failures": [failure.to_dict() for failure in image_failures],
    }

    failure_categories: dict[str, int] = {}
    for failure in (
        attachment_result.failures + image_failures
    ):
        failure_categories[failure.category] = (
            failure_categories.get(failure.category, 0) + 1
        )

    return {
        "name": org_name,
        "itglue_id": org_itglue_id,
        "bifrost_id": org_uuid,
        "attachments": attachment_result.to_dict(),
        "embedded_images": embedded_section,
        "failure_categories": failure_categories,
        "warnings": warnings,
    }


def _display_verify_report(report: dict[str, Any]) -> None:
    """Display fidelity verification results."""
    console.print()
    table = Table(title="Fidelity Verification", show_header=True)
    table.add_column("Organization", style="cyan")
    table.add_column("Attachments OK", justify="right")
    table.add_column("Missing Uploads", justify="right")
    table.add_column("Images Present/Expected", justify="right")
    table.add_column("Image Failures", justify="right")

    for org in report["organizations"]:
        attachments = org["attachments"]
        embedded = org["embedded_images"]
        missing = org["failure_categories"].get(MISSING_UPLOAD, 0)
        ok_str = (
            "[green]yes[/green]" if attachments["ok"] else "[red]no[/red]"
        )
        missing_str = f"[red]{missing}[/red]" if missing else str(missing)
        table.add_row(
            org["name"],
            ok_str,
            missing_str,
            f"{embedded['present_count']}/{embedded['expected_count']}",
            str(embedded["failure_count"]),
        )
    console.print(table)

    failures_total = report["summary"]["failure_count"]
    if failures_total:
        console.print()
        console.print("[bold red]Failures (first 10 per category shown):[/bold red]")
        shown = 0
        for org in report["organizations"]:
            for section in ("attachments", "embedded_images"):
                for failure in org[section]["failures"]:
                    if shown >= 10:
                        break
                    console.print(
                        f"  - [{failure['category']}] {org['name']}: "
                        f"{failure['message']}"
                    )
                    shown += 1

    console.print()
    follow_up = report["summary"]["follow_up_required"]
    style = "yellow" if follow_up else "green"
    console.print(
        f"[{style}]Follow-up required: {follow_up} "
        f"({failures_total} failures)[/{style}]"
    )


async def _run_verify(
    export_path: Path,
    api_url: str,
    token: str,
    target_org: str | None,
    check_urls: bool = False,
    output: Path | None = None,
) -> int:
    """Run read-only fidelity verification (GET/HEAD requests only).

    Returns:
        Exit code (0 when clean, 1 when failures were found).
    """
    validation = _validate_export_path(export_path)
    parser = CSVParser()
    console.print("[bold]Parsing CSV files...[/bold]")
    parsed = _parse_export_with_progress(parser, export_path, validation)

    if target_org:
        orgs_to_verify = [
            o for o in parsed.organizations if o.get("name") == target_org
        ]
        if not orgs_to_verify:
            error_console.print(
                f"[red]Error:[/red] Organization '{target_org}' not found in export"
            )
            return 1
    else:
        orgs_to_verify = parsed.organizations

    url_checker = _check_url_reachable if check_urls else None
    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "export_path": str(export_path),
        "target": target_org or "all",
        "check_urls": check_urls,
        "organizations": [],
    }

    async with BifrostDocsClient(base_url=api_url, api_key=token) as client:
        fetcher = StateFetcher(client)
        all_orgs_state = await fetcher.fetch_all_orgs()

        for org in orgs_to_verify:
            org_name = org.get("name", "")
            org_itglue_id = str(org.get("id", ""))
            console.print(f"[bold cyan]Verifying organization: {org_name}[/bold cyan]")

            org_uuid = all_orgs_state.org_by_itglue_id.get(org_itglue_id)
            if not org_uuid:
                org_uuid = all_orgs_state.org_by_name.get(org_name.lower())
            if not org_uuid:
                message = "Organization not found in API; verification skipped."
                console.print(f"  [red]{message}[/red]")
                report["organizations"].append(
                    {
                        "name": org_name,
                        "itglue_id": org_itglue_id,
                        "bifrost_id": None,
                        "attachments": {
                            "ok": False,
                            "expected_count": 0,
                            "migrated_count": 0,
                            "failure_count": 0,
                            "failures": [],
                        },
                        "embedded_images": {
                            "expected_count": 0,
                            "migrated_documents_checked": 0,
                            "present_count": 0,
                            "failure_count": 0,
                            "failures": [],
                        },
                        "failure_categories": {},
                        "warnings": [message],
                    }
                )
                continue

            state = await fetcher.fetch_for_org(org_uuid)

            (
                org_configs,
                org_locations,
                org_documents,
                org_passwords,
                org_custom_assets,
            ) = _filter_org_records(parsed, org_itglue_id, org_name)

            org_report = await _verify_org_fidelity(
                fetcher=fetcher,
                export_path=export_path,
                org_name=org_name,
                org_itglue_id=org_itglue_id,
                org_uuid=org_uuid,
                state=state,
                org_configs=org_configs,
                org_locations=org_locations,
                org_documents=org_documents,
                org_passwords=org_passwords,
                org_custom_assets=org_custom_assets,
                url_checker=url_checker,
            )
            report["organizations"].append(org_report)

    failure_categories: dict[str, int] = {}
    failure_count = 0
    for org_report in report["organizations"]:
        for category, count in org_report["failure_categories"].items():
            failure_categories[category] = failure_categories.get(category, 0) + count
        failure_count += org_report["attachments"]["failure_count"]
        failure_count += org_report["embedded_images"]["failure_count"]

    report["summary"] = {
        "organization_count": len(report["organizations"]),
        "failure_count": failure_count,
        "failure_categories": failure_categories,
        "follow_up_required": failure_count > 0,
    }

    _display_verify_report(report)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        console.print(f"[green]Fidelity report written to {output}[/green]")
    return 1 if failure_count > 0 else 0


@app.command()
def verify(
    export_path: Annotated[
        Path,
        typer.Option(
            "--export-path",
            "-e",
            help="Path to the IT Glue export directory",
            exists=False,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ],
    api_url: Annotated[
        str,
        typer.Option(
            "--api-url",
            "-u",
            help="BifrostDocs API URL (e.g., https://api.example.com)",
            envvar="BIFROST_API_URL",
        ),
    ],
    token: Annotated[
        str,
        typer.Option(
            "--token",
            "-t",
            help="BifrostDocs API authentication token",
            envvar="BIFROST_API_TOKEN",
        ),
    ],
    org: Annotated[
        str | None,
        typer.Option(
            "--org",
            "-o",
            help="Verify a single organization by name",
        ),
    ] = None,
    all_orgs: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Verify all organizations",
        ),
    ] = False,
    check_urls: Annotated[
        bool,
        typer.Option(
            "--check-urls",
            help="Also check that migrated download/image URLs are reachable",
        ),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            help="Write a JSON fidelity report to this path",
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
) -> None:
    """Verify attachment and embedded image fidelity after import.

    Read-only: only GET requests (plus HEAD/GET URL checks with --check-urls).
    Compares export files against migrated API records, checks migrated
    document content for broken image links, and writes a machine-readable
    report whose failure categories match the reconciliation vocabulary so
    results can be folded into reconciliation artifacts.

    Use --org to verify a single organization or --all for every organization
    in the export. Exits non-zero when failures are found.
    """
    console.print(Panel("IT Glue Migration - Verify Fidelity", style="bold blue"))
    console.print()

    if not org and not all_orgs:
        error_console.print(
            "[red]Error:[/red] You must specify either --org <name> or --all"
        )
        raise typer.Exit(1)

    if org and all_orgs:
        error_console.print(
            "[red]Error:[/red] Cannot specify both --org and --all"
        )
        raise typer.Exit(1)

    console.print(f"[bold]Export path:[/bold] {export_path}")
    console.print(f"[bold]API URL:[/bold] {api_url}")
    console.print(f"[bold]Target:[/bold] {org if org else 'All organizations'}")
    if check_urls:
        console.print("[bold]URL checks:[/bold] Enabled")
    console.print()

    exit_code = asyncio.run(
        _run_verify(
            export_path=export_path,
            api_url=api_url,
            token=token,
            target_org=org,
            check_urls=check_urls,
            output=output,
        )
    )

    console.print()
    if exit_code == 0:
        console.print(
            Panel(
                "[green]Fidelity verification passed![/green]\n\n"
                "All expected attachments and images reconciled.",
                title="Done",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                "[yellow]Fidelity verification found issues.[/yellow]\n\n"
                "Review the failures above.",
                title="Warning",
                border_style="yellow",
            )
        )

    sys.exit(exit_code)


if __name__ == "__main__":
    app()
