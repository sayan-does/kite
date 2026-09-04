"""Protected internal endpoints for cron and on-demand refresh."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Header, HTTPException, Query

from app.config import settings
from app.services.feed_pipeline import run_fast_cycle, run_slow_cycle
from app.services.scheduler import run_daily

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal", tags=["internal"])


def _check_secret(x_internal_secret: str | None) -> None:
    secret = settings.INTERNAL_TRIGGER_SECRET
    if not secret:
        raise HTTPException(status_code=503, detail="INTERNAL_TRIGGER_SECRET not configured")
    if x_internal_secret != secret:
        raise HTTPException(status_code=401, detail="Invalid internal secret")


@router.post("/refresh")
async def refresh_feed(
    mode: str = Query("fast", pattern="^(fast|slow)$"),
    topic: str | None = Query(None),
    force: bool = Query(False),
    x_internal_secret: str | None = Header(None, alias="X-Internal-Secret"),
):
    _check_secret(x_internal_secret)
    topics = [topic] if topic else None

    async def _run():
        try:
            if mode == "slow":
                result = await run_slow_cycle()
            else:
                result = await run_fast_cycle(topics=topics, force=force)
            logger.info("refresh %s complete: %s", mode, result)
        except Exception:
            logger.exception("refresh %s failed", mode)

    asyncio.create_task(_run())
    return {"ok": True, "mode": mode, "started": True}


@router.post("/run-daily")
async def trigger_run_daily(
    x_internal_secret: str | None = Header(None, alias="X-Internal-Secret"),
):
    """External cron entrypoint so hosts that sleep can still run the daily job."""
    _check_secret(x_internal_secret)

    async def _run():
        try:
            await run_daily()
            logger.info("run_daily complete")
        except Exception:
            logger.exception("run_daily failed")

    asyncio.create_task(_run())
    return {"ok": True, "started": True}
