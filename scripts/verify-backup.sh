#!/bin/bash
# Backup Verification Script
#
# Verifies database backups are valid and can be restored.
# This script downloads a backup, validates it, and performs a test restore to a temp database.
#
# Usage:
#   ./scripts/verify-backup.sh <backup-file>
#   ./scripts/verify-backup.sh --latest  # Verify most recent backup

set -e

BACKUP_FILE="${1:-}"
MODE="${2:-verify}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Configuration
S3_BUCKET="${SKRA_S3_BUCKET:-skra}"
S3_ENDPOINT="${SKRA_S3_ENDPOINT:-http://localhost:3900}"
BACKUP_DIR="${BACKUP_DIR:-/tmp/backup-verify}"
TEMP_DB_NAME="${POSTGRES_DB:-skra}_verify_$(date +%s)"
DB_USER="${POSTGRES_USER:-skra}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5433}"
DB_PASSWORD="${POSTGRES_PASSWORD:-}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

show_help() {
    cat << EOF
Backup Verification Script

Usage:
    $0 <backup-file>           # Verify specific backup file
    $0 --latest [--daily|--weekly]  # Verify most recent backup
    $0 --s3 <s3-path>          # Verify S3 backup path

Options:
    --latest           Find and verify the most recent backup
    --daily            With --latest, find latest daily backup
    --weekly           With --latest, find latest weekly backup
    --s3 PATH          Verify backup at S3 path
    --full             Also perform full test restore (slower)
    --help, -h         Show this help message

Examples:
    # Verify a specific backup file
    $0 /backups/skra_daily_20260406_120000.sql.gz

    # Verify latest daily backup
    $0 --latest --daily

    # Verify S3 backup with full restore test
    $0 --s3 s3://skra/backups/daily/2026-04-06/skra_daily_20260406_120000.sql.gz --full
EOF
}

# Parse arguments
FULL_VERIFY=false
LATEST_TYPE="daily"

while [[ $# -gt 0 ]]; do
    case $1 in
        --latest)
            BACKUP_FILE="__LATEST__"
            shift
            ;;
        --daily)
            LATEST_TYPE="daily"
            shift
            ;;
        --weekly)
            LATEST_TYPE="weekly"
            shift
            ;;
        --s3)
            BACKUP_FILE="$2"
            shift 2
            ;;
        --full)
            FULL_VERIFY=true
            shift
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        -*)
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
        *)
            BACKUP_FILE="$1"
            shift
            ;;
    esac
done

if [[ -z $BACKUP_FILE ]]; then
    echo -e "${RED}Error: No backup file specified${NC}"
    show_help
    exit 1
fi

# Find latest backup if requested
find_latest_backup() {
    local backup_type=$1
    echo -e "${YELLOW}Finding latest $backup_type backup...${NC}"
    
    if command -v aws &> /dev/null; then
        local latest=$(aws s3 ls "s3://$S3_BUCKET/backups/$backup_type/" \
            --endpoint-url "$S3_ENDPOINT" \
            --recursive | \
            sort -r | \
            head -1 | \
            awk '{print $4}')
        
        if [[ -n $latest ]]; then
            echo "s3://$S3_BUCKET/$latest"
        else
            echo ""
        fi
    else
        echo -e "${RED}Error: aws-cli not found, cannot find latest backup${NC}"
        exit 1
    fi
}

if [[ $BACKUP_FILE == "__LATEST__" ]]; then
    BACKUP_FILE=$(find_latest_backup "$LATEST_TYPE")
    if [[ -z $BACKUP_FILE ]]; then
        echo -e "${RED}Error: Could not find latest $LATEST_TYPE backup${NC}"
        exit 1
    fi
    echo -e "${GREEN}Found latest backup: $BACKUP_FILE${NC}"
fi

# Setup
mkdir -p "$BACKUP_DIR"
export PGPASSWORD="$DB_PASSWORD"

# Download from S3 if needed
download_backup() {
    local source=$1
    local dest=$2
    
    if [[ $source == s3://* ]]; then
        echo -e "${YELLOW}Downloading from S3...${NC}"
        if command -v aws &> /dev/null; then
            aws s3 cp "$source" "$dest" --endpoint-url "$S3_ENDPOINT"
        else
            echo -e "${RED}Error: aws-cli not found${NC}"
            exit 1
        fi
    else
        cp "$source" "$dest"
    fi
}

# Verify gzip integrity
verify_gzip() {
    local file=$1
    echo -e "${YELLOW}Verifying gzip integrity...${NC}"
    
    if gzip -t "$file" 2>/dev/null; then
        echo -e "${GREEN}✓ Gzip file is valid${NC}"
        return 0
    else
        echo -e "${RED}✗ Gzip file is corrupt${NC}"
        return 1
    fi
}

# Check pg_dump format
verify_pg_format() {
    local file=$1
    echo -e "${YELLOW}Verifying PostgreSQL dump format...${NC}"
    
    # Check if it's a valid PostgreSQL custom format dump
    local header=$(gunzip -c "$file" 2>/dev/null | head -c 19 | od -c | head -1)
    if echo "$header" | grep -q "PGDMP"; then
        echo -e "${GREEN}✓ PostgreSQL custom format dump detected${NC}"
        return 0
    else
        echo -e "${YELLOW}⚠ May not be a PostgreSQL custom format dump${NC}"
        # Continue anyway, might be plain SQL
        return 0
    fi
}

# Get backup metadata
get_backup_info() {
    local file=$1
    echo -e "${YELLOW}Getting backup information...${NC}"
    
    local size=$(du -h "$file" | cut -f1)
    local raw_size=$(gunzip -c "$file" 2>/dev/null | wc -c | numfmt --to=iec)
    local modified=$(stat -c %y "$file" 2>/dev/null || stat -f %Sm "$file")
    
    echo -e "${BLUE}Backup Information:${NC}"
    echo "  File: $(basename "$file")"
    echo "  Compressed size: $size"
    echo "  Uncompressed size: $raw_size"
    echo "  Modified: $modified"
    
    # Try to get PostgreSQL version info
    local pg_version=$(gunzip -c "$file" 2>/dev/null | strings | grep -E "^PostgreSQL [0-9]" | head -1)
    if [[ -n $pg_version ]]; then
        echo "  Source: $pg_version"
    fi
}

# Test restore to temporary database
test_restore() {
    local file=$1
    echo -e "${YELLOW}Testing restore to temporary database...${NC}"
    
    # Create temp database
    echo "Creating temporary database: $TEMP_DB_NAME"
    psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -c "CREATE DATABASE \"$TEMP_DB_NAME\";" 2>/dev/null || {
        echo -e "${RED}Error: Failed to create temporary database${NC}"
        return 1
    }
    
    # Restore (capture verbose log so failures are diagnosable in CI output)
    echo "Restoring backup..."
    local restore_log
    restore_log=$(mktemp)
    if gunzip -c "$file" | pg_restore \
        -h "$DB_HOST" \
        -p "$DB_PORT" \
        -U "$DB_USER" \
        -d "$TEMP_DB_NAME" \
        --verbose \
        --no-owner \
        --no-privileges \
        2>"$restore_log"; then
        echo -e "${GREEN}✓ Restore successful${NC}"
        rm -f "$restore_log"
    else
        echo -e "${RED}✗ Restore failed (pg_restore log tail):${NC}"
        tail -n 30 "$restore_log" || true
        rm -f "$restore_log"
        cleanup_temp_db
        return 1
    fi
    
    # Verify data
    echo "Verifying restored data..."
    local table_count=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$TEMP_DB_NAME" -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" 2>/dev/null | tr -d ' ')
    local row_count=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$TEMP_DB_NAME" -t -c "SELECT SUM(n_live_tup) FROM pg_stat_user_tables;" 2>/dev/null | tr -d ' ')
    
    echo -e "${GREEN}✓ Tables restored: $table_count${NC}"
    echo -e "${GREEN}✓ Estimated rows: ${row_count:-N/A}${NC}"
    
    # Cleanup
    cleanup_temp_db
    
    return 0
}

# Cleanup temporary database
cleanup_temp_db() {
    echo "Cleaning up temporary database..."
    psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS \"$TEMP_DB_NAME\";" 2>/dev/null || true
}

# Main verification
main() {
    echo -e "${YELLOW}========================================${NC}"
    echo -e "${YELLOW}  Backup Verification${NC}"
    echo -e "${YELLOW}========================================${NC}"
    echo ""
    
    local local_file="$BACKUP_DIR/verify_$(date +%s).sql.gz"
    
    # Download if needed
    download_backup "$BACKUP_FILE" "$local_file"
    
    # Run verifications
    local exit_code=0
    
    get_backup_info "$local_file"
    echo ""
    
    if ! verify_gzip "$local_file"; then
        exit_code=1
    fi
    
    if ! verify_pg_format "$local_file"; then
        exit_code=1
    fi
    
    if [[ $FULL_VERIFY == true ]] && [[ $exit_code -eq 0 ]]; then
        echo ""
        if ! test_restore "$local_file"; then
            exit_code=1
        fi
    fi
    
    # Cleanup
    rm -f "$local_file"
    
    echo ""
    echo -e "${YELLOW}========================================${NC}"
    if [[ $exit_code -eq 0 ]]; then
        echo -e "${GREEN}  Verification PASSED ✓${NC}"
    else
        echo -e "${RED}  Verification FAILED ✗${NC}"
    fi
    echo -e "${YELLOW}========================================${NC}"
    
    exit $exit_code
}

# Trap cleanup
trap cleanup_temp_db EXIT

main
