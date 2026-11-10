from __future__ import annotations

"""TinyFish Search / SearXNG / DDG search backfill collector."""

import asyncio
import logging

from app.agents.common import search
from app.collectors.base import CollectedItem, parse_datetime
from app.config import settings
from app.services.extractive import clean_snippet
from app.services.tinyfish_budget import tinyfish_budget

logger = logging.getLogger(__name__)


async def _tinyfish_search(query: str) -> list[dict] | None:
    """Search using TinyFish Search API."""
    if not settings.TINYFISH_API_KEY:
        return None
    
    try:
        from tinyfish import TinyFish
        client = TinyFish(api_key=settings.TINYFISH_API_KEY)
        response = await asyncio.to_thread(
            client.search.query,
            query=query,
            domain_type="news",
            location="US"
        )
        return [
            {"title": r.title, "url": r.url, "snippet": r.snippet}
            for r in response.results[:12]
        ]
    except Exception as exc:
        logger.warning(f"TinyFish search failed: {exc}")
        return None


async def collect_search_backfill(feed: dict, *, query: str) -> tuple[list[CollectedItem], dict]:
    poll_update = {"last_polled_at": "now()", "last_status": 0}
    if not query:
        return [], poll_update

    # Try TinyFish Search first
    if settings.TINYFISH_ENABLED and settings.TINYFISH_API_KEY:
        if tinyfish_budget.try_spend_search():
            try:
                year = "2026"
                full_query = f"{query} news {year}"
                results = await _tinyfish_search(full_query)
                if results:
                    items = _build_collected_items(results, feed, query)
                    poll_update["last_status"] = 200
                    poll_update["consecutive_failures"] = 0
                    poll_update["last_success_at"] = "now()"
                    return items, poll_update
            except Exception as exc:
                logger.warning(f"TinyFish search failed: {exc}, falling back to SearXNG/DDG")
    
    # Fallback to existing SearXNG/DDG path
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


def _build_collected_items(results: list[dict], feed: dict, query: str) -> list[CollectedItem]:
    """Build CollectedItem list from search results."""
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
    return items
