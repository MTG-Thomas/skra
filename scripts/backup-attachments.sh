#!/bin/bash
# S3 Attachments Backup Script
#
# Backs up S3 objects (attachments, exports) to a separate location for disaster recovery.
#
# Usage:
#   ./scripts/backup-attachments.sh              # Full attachments backup
#   ./scripts/backup-attachments.sh --sync       # Sync changes only
#   ./scripts/backup-attachments.sh --verify     # Verify backup integrity

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Configuration
SOURCE_BUCKET="${SKRA_S3_BUCKET:-skra}"
SOURCE_ENDPOINT="${SKRA_S3_ENDPOINT:-http://localhost:3900}"
BACKUP_BUCKET="${SKRA_BACKUP_BUCKET:-skra-backup}"
BACKUP_ENDPOINT="${SKRA_BACKUP_ENDPOINT:-$SOURCE_ENDPOINT}"
BACKUP_PREFIX="attachments/$(date +%Y-%m-%d)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

MODE="full"
SHOW_HELP=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --sync)
            MODE="sync"
            shift
            ;;
        --verify)
            MODE="verify"
            shift
            ;;
        --list)
            MODE="list"
            shift
            ;;
        --help|-h)
            SHOW_HELP=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            SHOW_HELP=true
            shift
            ;;
    esac
done

if $SHOW_HELP; then
    cat << EOF
S3 Attachments Backup Script

Usage:
    $0 [options]

Options:
    --sync          Sync only changed files (faster)
    --verify        Verify backup integrity
    --list          List backup contents
    --help, -h      Show this help message

Environment Variables:
    SKRA_S3_BUCKET         Source bucket (default: skra)
    SKRA_S3_ENDPOINT       Source S3 endpoint
    SKRA_BACKUP_BUCKET     Backup bucket (default: skra-backup)
    SKRA_BACKUP_ENDPOINT   Backup S3 endpoint

Examples:
    # Full backup
    $0

    # Sync only changes
    $0 --sync

    # Verify backup
    $0 --verify
EOF
    exit 0
fi

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}  S3 Attachments Backup${NC}"
echo -e "${YELLOW}========================================${NC}"
echo ""
echo -e "${BLUE}Source:${NC} $SOURCE_ENDPOINT/$SOURCE_BUCKET"
echo -e "${BLUE}Backup:${NC} $BACKUP_ENDPOINT/$BACKUP_BUCKET/$BACKUP_PREFIX"
echo ""

# Check dependencies
if ! command -v aws &> /dev/null; then
    echo -e "${RED}Error: aws-cli not found${NC}"
    exit 1
fi

# Get attachment count from source
echo -e "${YELLOW}Analyzing source bucket...${NC}"
SOURCE_COUNT=$(aws s3 ls "s3://$SOURCE_BUCKET/attachments/" \
    --endpoint-url "$SOURCE_ENDPOINT" \
    --recursive 2>/dev/null | wc -l || echo "0")
echo "Source objects: $SOURCE_COUNT"

case $MODE in
    full)
        echo -e "${YELLOW}Performing full backup...${NC}"
        aws s3 sync "s3://$SOURCE_BUCKET/attachments/" \
            "s3://$BACKUP_BUCKET/$BACKUP_PREFIX/" \
            --endpoint-url "$SOURCE_ENDPOINT" \
            --endpoint-url "$BACKUP_ENDPOINT"
        echo -e "${GREEN}✓ Full backup complete${NC}"
        ;;
    
    sync)
        echo -e "${YELLOW}Syncing changes only...${NC}"
        aws s3 sync "s3://$SOURCE_BUCKET/attachments/" \
            "s3://$BACKUP_BUCKET/$BACKUP_PREFIX/" \
            --endpoint-url "$SOURCE_ENDPOINT" \
            --endpoint-url "$BACKUP_ENDPOINT" \
            --delete
        echo -e "${GREEN}✓ Sync complete${NC}"
        ;;
    
    verify)
        echo -e "${YELLOW}Verifying backup integrity...${NC}"
        
        # Count objects in backup
        BACKUP_COUNT=$(aws s3 ls "s3://$BACKUP_BUCKET/$BACKUP_PREFIX/" \
            --endpoint-url "$BACKUP_ENDPOINT" \
            --recursive 2>/dev/null | wc -l || echo "0")
        
        echo "Source objects: $SOURCE_COUNT"
        echo "Backup objects: $BACKUP_COUNT"
        
        if [[ $SOURCE_COUNT -eq $BACKUP_COUNT ]]; then
            echo -e "${GREEN}✓ Object counts match${NC}"
        else
            echo -e "${YELLOW}⚠ Object count mismatch${NC}"
            echo "Run backup to sync: $0 --sync"
        fi
        
        # Sample verification
        echo ""
        echo -e "${YELLOW}Sampling backup objects...${NC}"
        aws s3 ls "s3://$BACKUP_BUCKET/$BACKUP_PREFIX/" \
            --endpoint-url "$BACKUP_ENDPOINT" \
            --recursive | head -10
        ;;
    
    list)
        echo -e "${YELLOW}Backup contents:${NC}"
        aws s3 ls "s3://$BACKUP_BUCKET/" \
            --endpoint-url "$BACKUP_ENDPOINT" \
            --recursive | head -20
        ;;
esac

echo ""
echo -e "${YELLOW}========================================${NC}"
echo -e "${GREEN}  Operation complete${NC}"
echo -e "${YELLOW}========================================${NC}"
