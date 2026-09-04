"""Hacker News collector via Algolia (no API key)."""

from __future__ import annotations

import time

import httpx

from app.collectors.base import CollectedItem, parse_datetime

HN_API = "https://hn.algolia.com/api/v1/search"

# Without a window Algolia returns all-time top stories, whose recency decay
# rounds the score to zero and drops every item.
HN_SINCE_DAYS = 7


async def collect_hn(
    feed: dict,
    *,
    topic_filter: str | None = None,
    tag_id: int | None = None,
    since_days: int = HN_SINCE_DAYS,
) -> tuple[list[CollectedItem], dict]:
    numeric_filters = ["points>20"]
    if since_days:
        cutoff = int(time.time()) - since_days * 86400
        numeric_filters.append(f"created_at_i>{cutoff}")

    params = {
        "tags": "story",
        "numericFilters": ",".join(numeric_filters),
        "hitsPerPage": 30,
    }
    if topic_filter:
        params["query"] = topic_filter

    poll_update = {"last_polled_at": "now()", "last_status": 0}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(HN_API, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError:
        poll_update["consecutive_failures"] = feed.get("consecutive_failures", 0) + 1
        poll_update["last_status"] = 0
        return [], poll_update

    topic = topic_filter or feed.get("topic")
    resolved_tag_id = tag_id if tag_id is not None else feed.get("tag_id")

    items: list[CollectedItem] = []
    for hit in data.get("hits", []):
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        title = (hit.get("title") or "").strip()
        if not title:
            continue
        created = hit.get("created_at")
        items.append(
            CollectedItem(
                title=title,
                url=url,
                snippet=title,
                published_at=parse_datetime(created),
                topic=topic,
                tag_id=resolved_tag_id,
                source_adapter="hn",
                source_weight=float(feed.get("weight") or 1.0),
                feed_id=feed.get("id"),
                signals={
                    "hn_points": hit.get("points", 0),
                    "hn_comments": hit.get("num_comments", 0),
                },
            )
        )

    poll_update.update({
        "last_status": 200,
        "consecutive_failures": 0,
        "last_success_at": "now()",
    })
    return items, poll_update
