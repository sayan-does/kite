"""RSS/Atom collector with conditional GET."""

from __future__ import annotations

import feedparser

from app.collectors.base import CollectedItem, conditional_get, parse_datetime
from app.services.extractive import clean_snippet


def _entry_datetime(entry) -> str | None:
    for attr in ("published", "updated", "created"):
        if getattr(entry, attr, None):
            return getattr(entry, attr)
    if entry.get("published_parsed"):
        return entry.published
    if entry.get("updated_parsed"):
        return entry.updated
    return None


async def collect_rss(feed: dict, *, ignore_cache: bool = False) -> tuple[list[CollectedItem], dict]:
    """Poll one source_feeds row. Returns items plus poll-state updates.

    ``ignore_cache`` drops the validators so a cold topic cannot be starved by a
    304 that would otherwise leave it with no articles at all.
    """
    url = feed["url"]
    resp = await conditional_get(
        url,
        etag=None if ignore_cache else feed.get("etag"),
        last_modified=None if ignore_cache else feed.get("last_modified"),
    )
    poll_update = {
        "last_polled_at": "now()",
        "last_status": resp.status,
        "etag": resp.etag,
        "last_modified": resp.last_modified,
    }

    if resp.not_modified or resp.status == 304:
        poll_update["consecutive_not_modified"] = feed.get("consecutive_not_modified", 0) + 1
        poll_update["consecutive_failures"] = 0
        return [], poll_update

    if resp.status != 200 or not resp.body:
        poll_update["consecutive_failures"] = feed.get("consecutive_failures", 0) + 1
        return [], poll_update

    parsed = feedparser.parse(resp.body)
    items: list[CollectedItem] = []
    for entry in parsed.entries[:40]:
        link = entry.get("link") or entry.get("id") or ""
        title = (entry.get("title") or "").strip()
        snippet = clean_snippet(entry.get("summary") or entry.get("description") or "")
        if not link or not title:
            continue
        published = parse_datetime(_entry_datetime(entry))
        items.append(
            CollectedItem(
                title=title,
                url=link,
                snippet=snippet,
                published_at=published,
                topic=feed.get("topic"),
                tag_id=feed.get("tag_id"),
                source_adapter="rss",
                source_weight=float(feed.get("weight") or 1.0),
                feed_id=feed.get("id"),
            )
        )

    poll_update["consecutive_failures"] = 0
    poll_update["consecutive_not_modified"] = 0
    poll_update["last_success_at"] = "now()"
    return items, poll_update
