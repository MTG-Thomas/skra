"""TEMPORARY PROBE for CodeQL py/log-injection patterns. DO NOT MERGE.

Opened as a draft PR solely to observe which sanitization patterns the
production CodeQL query accepts. Closed and deleted after reading results.
"""

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

from src.core.security import sanitize_log_value

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/_probe", tags=["probe"])


class ProbeBody(BaseModel):
    v: str


def _local_clean(value: str) -> str:
    return str(value).replace("\r", "").replace("\n", "")


@router.post("/logtest")
async def probe_log_patterns(request: Request, body: ProbeBody) -> dict:
    v = body.v
    q = request.query_params.get("q", "")
    logger.info(f"P1-direct-body {v}")
    logger.info(f"P2-direct-query {q}")
    # Hoisted out of the f-string: 3.11 forbids backslashes in f-string
    # expressions, and the barrier semantics are identical.
    p3 = v.replace("\n", "")
    p4 = v.replace("\r\n", "")
    logger.info(f"P3-inline-n {p3}")
    logger.info(f"P4-inline-rn {p4}")
    logger.info(f"P5-helper {sanitize_log_value(v)}")
    logger.info(f"P6-local {_local_clean(v)}")
    logger.info("P7-const", extra={"v": v})
    logger.info("P8-const", extra={"v": sanitize_log_value(v)})
    logger.info("P9-const", extra={"v": v.replace("\n", "")})
    logger.info("P10-pct %s", v)
    return {"ok": True}
