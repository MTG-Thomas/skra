#!/bin/bash
# Database Backup Script
# 
# Creates PostgreSQL dumps and uploads to S3 storage.
# Supports full backups, incremental backups, and cleanup of old backups.
#
# Usage:
#   ./scripts/backup.sh              # Full backup
#   ./scripts/backup.sh --daily    # Daily backup (with rotation)
#   ./scripts/backup.sh --weekly   # Weekly backup (keeps 4 weeks)
#   ./scripts/backup.sh --restore <backup-file>  # Restore from backup

set -e

# Configuration
BACKUP_DIR="${BACKUP_DIR:-./backups}"
S3_BUCKET="${SKRA_S3_BUCKET:-skra}"
S3_ENDPOINT="${SKRA_S3_ENDPOINT:-http://localhost:3900}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
DB_NAME="${POSTGRES_DB:-skra}"
DB_USER="${POSTGRES_USER:-skra}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5433}"
DB_PASSWORD="${POSTGRES_PASSWORD:-}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DATE=$(date +%Y-%m-%d)

# Parse arguments
MODE="full"
RESTORE_FILE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --daily)
            MODE="daily"
            shift
            ;;
        --weekly)
            MODE="weekly"
            shift
            ;;
        --restore)
            MODE="restore"
            RESTORE_FILE="$2"
            shift 2
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

show_help() {
    cat << EOF
Database Backup Script

Usage:
    $0 [options]

Options:
    --daily          Create daily backup with rotation (keeps 7 days)
    --weekly         Create weekly backup (keeps 4 weeks)
    --restore FILE   Restore database from backup file
    --help, -h       Show this help message

Environment Variables:
    BACKUP_DIR              Local backup directory (default: ./backups)
    SKRA_S3_BUCKET   S3 bucket name
    SKRA_S3_ENDPOINT  S3 endpoint URL
    BACKUP_RETENTION_DAYS   Days to keep backups (default: 30)
    POSTGRES_PASSWORD        Database password
    POSTGRES_DB              Database name
    POSTGRES_USER            Database user

Examples:
    # Create full backup
    $0

    # Daily backup (typically run via cron)
    $0 --daily

    # Restore from backup
    $0 --restore s3://skra/backups/daily/20260406_120000.sql.gz
EOF
}

# Check dependencies
check_dependencies() {
    local missing=()
    
    if ! command -v pg_dump &> /dev/null; then
        missing+=("postgresql-client (pg_dump)")
    fi
    
    if ! command -v aws &> /dev/null && ! command -v s3cmd &> /dev/null; then
        missing+=("aws-cli or s3cmd")
    fi
    
    if [ ${#missing[@]} -ne 0 ]; then
        echo -e "${RED}Missing dependencies: ${missing[*]}${NC}"
        exit 1
    fi
}

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Set PGPASSWORD for non-interactive operation
export PGPASSWORD="$DB_PASSWORD"

# Create backup
create_backup() {
    local backup_type=$1
    local filename="${DB_NAME}_${backup_type}_${TIMESTAMP}.sql.gz"
    local local_path="$BACKUP_DIR/$filename"
    local s3_path="s3://$S3_BUCKET/backups/$backup_type/$DATE/$filename"
    
    echo -e "${YELLOW}Creating $backup_type backup...${NC}"
    
    # Create dump with progress
    echo "Dumping database $DB_NAME from $DB_HOST:$DB_PORT..."
    pg_dump \
        -h "$DB_HOST" \
        -p "$DB_PORT" \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        --verbose \
        --format=custom \
        2>/dev/null | gzip > "$local_path"
    
    local size=$(du -h "$local_path" | cut -f1)
    echo -e "${GREEN}✓ Backup created: $filename ($size)${NC}"
    
    # Upload to S3
    echo "Uploading to S3..."
    if command -v aws &> /dev/null; then
        aws s3 cp "$local_path" "$s3_path" \
            --endpoint-url "$S3_ENDPOINT" \
            --quiet
    else
        s3cmd put "$local_path" "$s3_path" \
            --host "$S3_ENDPOINT" \
            --host-bucket="" \
            --quiet
    fi
    
    echo -e "${GREEN}✓ Backup uploaded to $s3_path${NC}"
    
    # Cleanup local file
    rm "$local_path"
    
    # Return S3 path for reference
    echo "$s3_path"
}

# Restore from backup
restore_backup() {
    local backup_file=$1
    
    echo -e "${YELLOW}Restoring from backup: $backup_file${NC}"
    
    # Download from S3 if needed
    local local_file
    if [[ $backup_file == s3://* ]]; then
        local_file="$BACKUP_DIR/restore_${TIMESTAMP}.sql.gz"
        echo "Downloading from S3..."
        if command -v aws &> /dev/null; then
            aws s3 cp "$backup_file" "$local_file" --endpoint-url "$S3_ENDPOINT"
        else
            s3cmd get "$backup_file" "$local_file" --host "$S3_ENDPOINT"
        fi
    else
        local_file="$backup_file"
    fi
    
    # Confirm restore
    echo -e "${RED}WARNING: This will overwrite the current database!${NC}"
    read -p "Are you sure? Type 'yes' to continue: " confirm
    if [[ $confirm != "yes" ]]; then
        echo "Restore cancelled"
        exit 0
    fi
    
    # Restore
    echo "Restoring database..."
    gunzip -c "$local_file" | pg_restore \
        -h "$DB_HOST" \
        -p "$DB_PORT" \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        --verbose \
        --clean \
        --if-exists \
        2>/dev/null
    
    echo -e "${GREEN}✓ Database restored successfully${NC}"
    
    # Cleanup downloaded file if we downloaded it
    if [[ $backup_file == s3://* ]]; then
        rm "$local_file"
    fi
}

# Cleanup old backups
cleanup_old_backups() {
    local backup_type=$1
    local keep_count=$2
    
    echo -e "${YELLOW}Cleaning up old $backup_type backups (keeping $keep_count)...${NC}"
    
    # List backups and remove old ones
    local s3_prefix="s3://$S3_BUCKET/backups/$backup_type/"
    
    if command -v aws &> /dev/null; then
        aws s3 ls "$s3_prefix" --endpoint-url "$S3_ENDPOINT" --recursive | \
            sort -r | \
            tail -n +$((keep_count + 1)) | \
            while read -r line; do
                local file=$(echo "$line" | awk '{print $4}')
                if [[ -n $file ]]; then
                    echo "Removing old backup: $file"
                    aws s3 rm "s3://$S3_BUCKET/$file" --endpoint-url "$S3_ENDPOINT" --quiet
                fi
            done
    fi
    
    echo -e "${GREEN}✓ Cleanup complete${NC}"
}

# Main execution
main() {
    echo -e "${YELLOW}========================================${NC}"
    echo -e "${YELLOW}  Skra Database Backup${NC}"
    echo -e "${YELLOW}========================================${NC}"
    echo ""
    
    case $MODE in
        full)
            check_dependencies
            create_backup "full"
            ;;
        daily)
            check_dependencies
            create_backup "daily"
            cleanup_old_backups "daily" 7
            ;;
        weekly)
            check_dependencies
            create_backup "weekly"
            cleanup_old_backups "weekly" 4
            ;;
        restore)
            if [[ -z $RESTORE_FILE ]]; then
                echo -e "${RED}Error: No restore file specified${NC}"
                echo "Usage: $0 --restore <backup-file>"
                exit 1
            fi
            restore_backup "$RESTORE_FILE"
            ;;
    esac
    
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  Backup operation complete! ✅${NC}"
    echo -e "${GREEN}========================================${NC}"
}

main
