# Acceptance Criteria: skra-migration-patterns

**Repository:** `MTG-Thomas/skra`  
**Tool:** `tools/itglue-migrate/`  
**Purpose:** Validate migration tool patterns

---

## 1. CSV Parsing Patterns

### ✅ CORRECT: Handle Optional Fields

```python
def parse_configurations(self, path: Path) -> list[Configuration]:
    configs = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            config = Configuration(
                id=row["id"],
                name=row["name"],
                # Handle optional fields with defaults
                serial_number=row.get("serial_number") or None,
                asset_tag=row.get("asset_tag") or None,
                notes=row.get("notes") or None,
            )
            configs.append(config)
    return configs
```

### ❌ INCORRECT: Assume All Fields Present

```python
def parse_configurations(self, path: Path) -> list[Configuration]:
    configs = []
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            config = Configuration(
                id=row["id"],
                serial_number=row["serial_number"],  # WRONG: May be missing!
            )
```

### ✅ CORRECT: UTF-8 Encoding

```python
with open(path, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
```

### ❌ INCORRECT: Default Encoding

```python
with open(path, "r") as f:  # WRONG: May fail on special chars
    reader = csv.DictReader(f)
```

---

## 2. Import Context Pattern

### ✅ CORRECT: Track Progress

```python
@dataclass
class ImportContext:
    api_url: str
    api_token: str
    dry_run: bool = False
    
    # Counters
    imported_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    errors: list[dict] = field(default_factory=list)

    def add_error(self, entity_type: str, source_id: str, error: str):
        self.error_count += 1
        self.errors.append({
            "entity_type": entity_type,
            "source_id": source_id,
            "error": error,
        })
```

### ❌ INCORRECT: No Context Object

```python
# WRONG: Loose variables
count = 0
errors = []
# Hard to track state across functions
```

---

## 3. API Client Pattern

### ✅ CORRECT: Async with aiohttp

```python
async def _import_organization(
    self,
    org: Organization,
    ctx: ImportContext,
) -> ImportResult:
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {ctx.api_token}"}
            
            async with session.post(
                f"{ctx.api_url}/api/organizations",
                json={"name": org.name},
                headers=headers,
            ) as resp:
                if resp.status == 201:
                    data = await resp.json()
                    return ImportResult(
                        success=True,
                        source_id=org.id,
                        target_id=UUID(data["id"]),
                    )
                elif resp.status == 409:
                    return ImportResult(
                        success=True,
                        action="skipped",
                        error="Already exists",
                    )
                else:
                    return ImportResult(
                        success=False,
                        error=f"HTTP {resp.status}",
                    )
    except Exception as e:
        return ImportResult(success=False, error=str(e))
```

### ❌ INCORRECT: Synchronous Requests

```python
import requests  # WRONG: Blocking in async context

def import_organization(self, org):
    resp = requests.post(...)  # Blocks event loop!
```

---

## 4. Reconciliation Pattern

### ✅ CORRECT: Compare Source vs Target

```python
def generate_report(
    self,
    source_counts: dict[str, int],
    target_counts: dict[str, int],
) -> dict:
    report = {
        "summary": {
            "total_source": sum(source_counts.values()),
            "total_target": sum(target_counts.values()),
            "difference": sum(source_counts.values()) - sum(target_counts.values()),
        },
        "by_entity_type": {},
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
            "status": "ok" if diff == 0 else "gap",
        }
        
        if diff > 0:
            report["recommendations"].append(
                f"{entity_type}: {diff} items not migrated"
            )
    
    return report
```

---

## 5. Relationship Mapping Pattern

### ✅ CORRECT: ID Mapping Lookup

```python
class RelationshipMapper:
    def __init__(self, id_mapping: dict[str, UUID]):
        self.id_mapping = id_mapping

    def map_relationship(
        self,
        source_id: str,
        target_id: str,
    ) -> tuple[UUID, UUID] | None:
        source_skra = self.id_mapping.get(source_id)
        target_skra = self.id_mapping.get(target_id)
        
        if not source_skra or not target_skra:
            return None  # Can't map, skip
        
        return (source_skra, target_skra)
```

### ❌ INCORRECT: Assume All IDs Map

```python
# WRONG: No None check
source_uuid = id_mapping[source_id]  # KeyError if missing!
target_uuid = id_mapping[target_id]
```

---

## 6. Dry Run Pattern

### ✅ CORRECT: Check Dry Run Flag

```python
async def import_entity(self, entity, ctx: ImportContext) -> ImportResult:
    if ctx.dry_run:
        return ImportResult(
            success=True,
            action="dry_run",
            source_id=entity.id,
        )
    
    # Actual import logic
    ...
```

### ❌ INCORRECT: No Dry Run Support

```python
async def import_entity(self, entity):
    # WRONG: Always imports!
    await self.api.create(entity)
```

---

## 7. Test Fixture Pattern

### ✅ CORRECT: Synthetic Test Data

```csv
# organizations.csv
id,name,status,organization_status
1001,Test Org 01,Active,Active
1002,Test Org 02,Active,Active
```

Requirements:
- Use "Test" in names
- Safe to commit
- No real customer data
- Documented in README

### ❌ INCORRECT: Real Data in Repo

```csv
# WRONG: Real customer names!
id,name,status
1001,Acme Corporation,Active
1002,Microsoft,Active
```

---

## 8. CLI Pattern

### ✅ CORRECT: Click with Help

```python
@click.command()
@click.option(
    "--export",
    "-e",
    required=True,
    type=click.Path(exists=True),
    help="Path to IT Glue export directory",
)
@click.option(
    "--dry-run",
    "-d",
    is_flag=True,
    help="Validate without importing",
)
def run(export: Path, dry_run: bool):
    """Run full migration from IT Glue export."""
    ...
```

### ❌ INCORRECT: Argparse without Types

```python
import argparse  # WRONG: Click is preferred

parser = argparse.ArgumentParser()
parser.add_argument("--export")  # No type validation!
```

---

## 9. Common Mistakes Checklist

| Mistake | Why It's Wrong | Correct Approach |
|---------|---------------|------------------|
| No optional field handling | KeyError on missing data | Use `.get()` with defaults |
| Blocking I/O | Async context blocked | Use `aiohttp` for async |
| No dry run | Can't preview changes | Check `ctx.dry_run` flag |
| No progress tracking | Can't report status | Use `ImportContext` counters |
| Hard delete mapping | Data loss | Use `is_enabled` mapping |
| Real data in fixtures | Security risk | Use synthetic "Test" data |
| No reconciliation | Can't verify migration | Generate comparison reports |
