#!/usr/bin/env python3
"""
Init container script for Skra.

Runs database migrations and required data backfills before API starts.

Usage:
    python -m scripts.init_container

Exit codes:
    0 - Success
    1 - Migration failure
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [init] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("init_container")


def run_migrations() -> bool:
    """
    Run alembic migrations.

    Returns:
        True if migrations succeeded, False otherwise
    """
    logger.info("Running database migrations...")

    # Get the api/ directory (parent of scripts/)
    api_dir = Path(__file__).parent.parent

    try:
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=api_dir,
            capture_output=True,
            text=True,
            check=True,
            timeout=300,  # 5 minute timeout
        )

        # Log migration output
        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    logger.info(f"alembic: {line}")

        logger.info("Database migrations completed successfully")
        return True

    except subprocess.TimeoutExpired:
        logger.error("Migration timed out after 5 minutes")
        return False

    except subprocess.CalledProcessError as e:
        logger.error(f"Migration failed with exit code {e.returncode}")
        if e.stderr:
            for line in e.stderr.strip().split("\n"):
                logger.error(f"alembic: {line}")
        if e.stdout:
            for line in e.stdout.strip().split("\n"):
                logger.info(f"alembic: {line}")
        return False

    except FileNotFoundError:
        logger.error("alembic command not found - ensure it's installed")
        return False


def run_expiration_projection_backfill() -> bool:
    """Populate the projection required by upcoming-expiration reads.

    The backfill is rerunnable and commits after each asset type, so an
    interrupted startup converges on retry. Startup remains blocked until it
    succeeds; serving projection-backed routes with an empty upgrade table
    would silently hide existing expirations.
    """
    logger.info("Backfilling expiration projections...")
    api_dir = Path(__file__).parent.parent

    try:
        result = subprocess.run(
            [sys.executable, "-m", "scripts.backfill_expiration_projections"],
            cwd=api_dir,
            capture_output=True,
            text=True,
            check=True,
            timeout=1800,
        )
        for output in (result.stdout, result.stderr):
            if output:
                for line in output.strip().split("\n"):
                    if line.strip():
                        logger.info("expiration-backfill: %s", line)
        logger.info("Expiration projection backfill completed successfully")
        return True
    except subprocess.TimeoutExpired:
        logger.error("Expiration projection backfill timed out after 30 minutes")
        return False
    except subprocess.CalledProcessError as exc:
        logger.error("Expiration projection backfill failed with exit code %s", exc.returncode)
        if exc.stderr:
            for line in exc.stderr.strip().split("\n"):
                logger.error("expiration-backfill: %s", line)
        if exc.output:
            for line in exc.output.strip().split("\n"):
                logger.error("expiration-backfill: %s", line)
        return False
    except FileNotFoundError:
        logger.error("python command not found for expiration projection backfill")
        return False


def main() -> int:
    """
    Main entry point for init container.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    logger.info("=" * 60)
    logger.info("Skra Init Container Starting")
    logger.info("=" * 60)

    logger.info("")
    logger.info("Running Database Migrations")
    logger.info("-" * 40)

    if not run_migrations():
        logger.error("FAILED: Database migrations failed - aborting startup")
        return 1

    logger.info("")
    logger.info("Running Required Data Backfills")
    logger.info("-" * 40)

    if not run_expiration_projection_backfill():
        logger.error("FAILED: Required data backfill failed - aborting startup")
        return 1

    logger.info("")
    logger.info("=" * 60)
    logger.info("Init Container Completed Successfully")
    logger.info("=" * 60)

    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
