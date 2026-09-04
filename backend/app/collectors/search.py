"""SearXNG / DDG search backfill collector."""

from __future__ import annotations

from app.agents.common import search
from app.collectors.base import CollectedItem, parse_datetime
from app.services.extractive import clean_snippet


async def collect_search_backfill(feed: dict, *, query: str) -> tuple[list[CollectedItem], dict]:
    poll_update = {"last_polled_at": "now()", "last_status": 0}
    if not query:
        return [], poll_update

    year = "2026"
    full_query = f"{query} news {year}"
    results = await search(full_query)
    poll_update["last_status"] = 200 if results else 503

    items: list[CollectedItem] = []
    for r in results[:12]:
        url = r.get("url", "")
        title = (r.get("title") or "").strip()
        snippet = clean_snippet(r.get("snippet") or "")
        if not url or not title:
            continue
        items.append(
            CollectedItem(
                title=title,
                url=url,
                snippet=snippet,
                published_at=parse_datetime(None),
                topic=feed.get("topic") or query,
                tag_id=feed.get("tag_id"),
                source_adapter="search",
                source_weight=float(feed.get("weight") or 0.8),
                feed_id=feed.get("id"),
            )
        )

    if items:
        poll_update["consecutive_failures"] = 0
        poll_update["last_success_at"] = "now()"
    else:
        poll_update["consecutive_failures"] = feed.get("consecutive_failures", 0) + 1
    return items, poll_update
