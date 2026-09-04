"""Keep every category warm, whether or not a user follows it.

The collect cycle is normally driven by what users already follow, which means
the first person to pick a category waits for a cold collect. Prefill closes
that gap: it runs on startup and again on the daily cron, so any category a new
user can choose already has articles behind it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.db import supabase

logger = logging.getLogger(__name__)


def all_category_names() -> list[str]:
    """Category names straight from the table, so the seed stays authoritative."""
    rows = supabase.table("interest_tags").select("name").order("id").execute().data or []
    return [row["name"] for row in rows if row.get("name")]


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def categories_needing_fill(names: list[str]) -> list[str]:
    """Categories that are thin on articles or whose newest article went stale."""
    if not names:
        return []

    rows = (
        supabase.table("kb_articles")
        .select("topic, collected_at, fetched_at")
        .eq("status", "active")
        .in_("topic", names)
        .execute()
        .data
        or []
    )

    counts: dict[str, int] = {name: 0 for name in names}
    newest: dict[str, datetime | None] = {name: None for name in names}
    for row in rows:
        topic = row.get("topic")
        if topic not in counts:
            continue
        counts[topic] += 1
        ts = _parse_ts(row.get("collected_at")) or _parse_ts(row.get("fetched_at"))
        if ts and (newest[topic] is None or ts > newest[topic]):
            newest[topic] = ts

    stale_before = datetime.now(timezone.utc) - timedelta(hours=settings.PREFILL_STALE_HOURS)
    needed: list[str] = []
    for name in names:
        if counts[name] < settings.PREFILL_TARGET_ARTICLES:
            needed.append(name)
        elif newest[name] is None or newest[name] < stale_before:
            needed.append(name)
    return needed


async def prefill_all_categories(*, force: bool = False) -> dict:
    """Collect and review for every category that is empty or stale.

    Categories are handled one at a time rather than as a single batch so a
    slow or failing source cannot starve the rest.
    """
    from app.services.feed_pipeline import run_fast_cycle, run_slow_cycle

    if not (isinstance(getattr(settings, "FEED_V3", False), bool) and settings.FEED_V3):
        return {"skipped": "FEED_V3 disabled", "filled": []}

    names = all_category_names()
    targets = names if force else categories_needing_fill(names)
    if not targets:
        logger.info("prefill: all %d categories already warm", len(names))
        return {"filled": [], "categories": len(names)}

    logger.info("prefill: filling %s", targets)
    filled: list[str] = []
    failed: list[str] = []
    for name in targets:
        try:
            await run_fast_cycle(topics=[name], force=True, allow_search_backfill=True)
            await run_slow_cycle(topics=[name])
            filled.append(name)
        except Exception:
            logger.exception("prefill failed for category %s", name)
            failed.append(name)

    return {"filled": filled, "failed": failed, "categories": len(names)}
