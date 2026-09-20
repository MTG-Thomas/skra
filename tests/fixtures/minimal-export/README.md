# Seeded Migration Fixture

This directory contains a minimal synthetic IT Glue export fixture for testing the migration tool. All data is synthetic and safe to commit.

## Structure

```
fixtures/
└── minimal-export/
    ├── organizations.csv      # 2 test organizations
    ├── configurations.csv     # 2 test configurations
    ├── documents.csv          # 1 test document
    ├── locations.csv          # 1 test location
    ├── passwords.csv          # 2 test passwords
    └── README.md              # This file
```

## Usage

### Manual Testing

```bash
cd tools/itglue-migrate

# Preview the migration
python -m itglue_migrate.cli preview \
    --export ../../tests/fixtures/minimal-export \
    --api-url http://localhost:8080 \
    --token $SKRA_TOKEN

# Run the migration (dry-run first)
python -m itglue_migrate.cli run \
    --export ../../tests/fixtures/minimal-export \
    --plan /tmp/test-plan.json \
    --api-url http://localhost:8080 \
    --token $SKRA_TOKEN \
    --dry-run
```

### Automated Testing

```bash
# Run the smoke test
pytest tests/integration/test_migration_smoke.py -v
```

## Data Overview

### Organizations

| ID | Name | Status |
|----|------|--------|
| 1001 | Acme Corp Test | Active |
| 1002 | Test Technologies Inc | Active |

### Configurations

| ID | Organization | Name | Type | Status |
|----|--------------|------|------|--------|
| 2001 | Acme Corp Test | Test Server 01 | Server | Active |
| 2002 | Test Technologies Inc | Test Workstation 01 | Workstation | Active |

### Documents

| ID | Organization | Name | Path |
|----|--------------|------|------|
| 3001 | Acme Corp Test | Test Onboarding Guide | / |

### Locations

| ID | Organization | Name | Address |
|----|--------------|------|---------|
| 4001 | Acme Corp Test | Test Main Office | 123 Test St, Test City |

### Passwords

| ID | Organization | Name | Username |
|----|--------------|------|----------|
| 5001 | Acme Corp Test | Test Admin Password | admin.test |
| 5002 | Test Technologies Inc | Test User Password | user.test |

## Safety

All data in this fixture is:
- Synthetic (not real customer data)
- Clearly labeled as "Test" or "Test_"
- Safe to commit to version control
- Used only for testing migration behavior
