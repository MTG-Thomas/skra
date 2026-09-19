#!/bin/bash
# Local CI Script
# Mirrors the GitHub Actions workflow for local testing
# Usage: ./scripts/ci-check.sh [target]
#   target: all (default) | backend | frontend | docker

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

TARGET=${1:-all}

# =============================================================================
# Backend Checks
# =============================================================================
backend_checks() {
    echo -e "${YELLOW}=== Running Backend Checks ===${NC}"
    
    cd api
    
    # Check if virtual environment exists
    if [ ! -d ".venv" ]; then
        echo -e "${YELLOW}Creating virtual environment...${NC}"
        python3 -m venv .venv
    fi
    
    source .venv/bin/activate
    
    # Install dependencies
    echo -e "${YELLOW}Installing dependencies...${NC}"
    pip install -e ".[dev]" -q
    
    # Run Ruff linter
    echo -e "${YELLOW}Running Ruff linter...${NC}"
    ruff check src tests || { echo -e "${RED}Ruff check failed${NC}"; exit 1; }
    ruff format --check src tests || { echo -e "${RED}Ruff format check failed${NC}"; exit 1; }
    echo -e "${GREEN}✓ Ruff checks passed${NC}"
    
    # Run Pyright type checker (if installed)
    if command -v pyright &> /dev/null; then
        echo -e "${YELLOW}Running Pyright type checker...${NC}"
        pyright src || { echo -e "${RED}Pyright check failed${NC}"; exit 1; }
        echo -e "${GREEN}✓ Pyright checks passed${NC}"
    else
        echo -e "${YELLOW}⚠ Pyright not installed, skipping type check${NC}"
    fi
    
    cd ..
    echo -e "${GREEN}✓ Backend checks complete${NC}"
}

# =============================================================================
# Frontend Checks
# =============================================================================
frontend_checks() {
    echo -e "${YELLOW}=== Running Frontend Checks ===${NC}"
    
    cd client
    
    # Install dependencies if node_modules doesn't exist
    if [ ! -d "node_modules" ]; then
        echo -e "${YELLOW}Installing npm dependencies...${NC}"
        npm ci
    fi
    
    # TypeScript check
    echo -e "${YELLOW}Running TypeScript compiler...${NC}"
    npm run tsc || { echo -e "${RED}TypeScript check failed${NC}"; exit 1; }
    echo -e "${GREEN}✓ TypeScript checks passed${NC}"
    
    # ESLint
    echo -e "${YELLOW}Running ESLint...${NC}"
    npm run lint || { echo -e "${RED}ESLint check failed${NC}"; exit 1; }
    echo -e "${GREEN}✓ ESLint checks passed${NC}"
    
    # Build check
    echo -e "${YELLOW}Running production build...${NC}"
    npm run build || { echo -e "${RED}Build failed${NC}"; exit 1; }
    echo -e "${GREEN}✓ Build successful${NC}"
    
    cd ..
    echo -e "${GREEN}✓ Frontend checks complete${NC}"
}

# =============================================================================
# Docker Build Check
# =============================================================================
docker_checks() {
    echo -e "${YELLOW}=== Running Docker Build Checks ===${NC}"
    
    # Check if Docker is running
    if ! docker info > /dev/null 2>&1; then
        echo -e "${RED}Docker is not running. Skipping Docker checks.${NC}"
        return 0
    fi
    
    # Build API image
    echo -e "${YELLOW}Building API Docker image...${NC}"
    docker build -t skra-api:ci-test ./api || { echo -e "${RED}API Docker build failed${NC}"; exit 1; }
    echo -e "${GREEN}✓ API Docker build successful${NC}"
    
    # Build Client image
    echo -e "${YELLOW}Building Client Docker image...${NC}"
    docker build -t skra-client:ci-test ./client || { echo -e "${RED}Client Docker build failed${NC}"; exit 1; }
    echo -e "${GREEN}✓ Client Docker build successful${NC}"
    
    # Clean up test images
    docker rmi skra-api:ci-test skra-client:ci-test 2>/dev/null || true
    
    echo -e "${GREEN}✓ Docker checks complete${NC}"
}

# =============================================================================
# E2E Test Check (if containers are running)
# =============================================================================
e2e_checks() {
    echo -e "${YELLOW}=== Running E2E Test Checks ===${NC}"
    
    # Check if dev environment is running
    if docker compose ps | grep -q "skra-api"; then
        echo -e "${YELLOW}Development environment detected. Running E2E tests...${NC}"
        
        cd client
        if [ -d "node_modules" ]; then
            npx playwright test --reporter=line || { echo -e "${RED}E2E tests failed${NC}"; exit 1; }
            echo -e "${GREEN}✓ E2E tests passed${NC}"
        else
            echo -e "${YELLOW}⚠ npm dependencies not installed, skipping E2E tests${NC}"
        fi
        cd ..
    else
        echo -e "${YELLOW}⚠ Dev environment not running. Skipping E2E tests.${NC}"
        echo -e "${YELLOW}   Start with: docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d${NC}"
    fi
}

# =============================================================================
# Main
# =============================================================================
main() {
    echo -e "${YELLOW}========================================${NC}"
    echo -e "${YELLOW}  Skra CI Checks (Local)${NC}"
    echo -e "${YELLOW}========================================${NC}"
    echo ""
    
    case $TARGET in
        all)
            backend_checks
            echo ""
            frontend_checks
            echo ""
            docker_checks
            echo ""
            e2e_checks
            ;;
        backend)
            backend_checks
            ;;
        frontend)
            frontend_checks
            ;;
        docker)
            docker_checks
            ;;
        e2e)
            e2e_checks
            ;;
        *)
            echo "Usage: $0 [all|backend|frontend|docker|e2e]"
            exit 1
            ;;
    esac
    
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  All CI checks passed! ✅${NC}"
    echo -e "${GREEN}========================================${NC}"
}

main
