#!/usr/bin/env python3
"""
Backfill the expiration projection (issue #136).

Re-derives projection rows for every custom asset type. Upserts are
idempotent and per-asset refresh prunes stale rows, so reruns converge
instead of duplicating work. Commits after each asset type.

Usage:
    python scripts/backfill_expiration_projections.py [--page-size 500]
"""

import argparse
import asyncio
import logging

from src.core.database import get_session_factory
from src.services.expiration_projection import backfill_all_projections

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill normalized expiration projection rows.")
    parser.add_argument(
        "--page-size",
        type=int,
        default=500,
        help="Assets/types per page (default 500)",
    )
    args = parser.parse_args()

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            result = await backfill_all_projections(session, page_size=args.page_size)
            logger.info(
                "Expiration projection backfill complete: "
                f"{result['types']} types, {result['assets']} assets refreshed"
            )
        except Exception:
            logger.error("Expiration projection backfill failed", exc_info=True)
            raise


if __name__ == "__main__":
    asyncio.run(main())
