"""Fast and slow feed pipeline cycles (FEED_V3)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlparse

from app.agents.discovery.nodes import _classify_url
from app.agents.discovery.research import apply_research_metadata
from app.collectors.base import CollectedItem, url_is_reachable
from app.collectors.github_releases import collect_github_releases
from app.collectors.hn import collect_hn
from app.collectors.papers import collect_papers
from app.collectors.rss import collect_rss
from app.collectors.search import collect_search_backfill
from app.config import settings
from app.db import supabase
from app.services import feed_jobs
from app.services.extractive import clean_snippet, extractive_one_liner
from app.services.ranking import assign_cluster_ids, compute_score, dedup_items, topic_relevance

logger = logging.getLogger(__name__)

MIN_RELEVANCE = 0.25
POLL_MIN = 30
POLL_MAX = 360


async def _collect_one_feed(
    feed: dict,
    *,
    ignore_cache: bool = False,
    topic_filter: str | None = None,
    tag_id: int | None = None,
) -> tuple[list[CollectedItem], dict]:
    kind = feed.get("kind")
    if kind == "rss":
        return await collect_rss(feed, ignore_cache=ignore_cache)
    if kind == "hn":
        return await collect_hn(
            feed,
            topic_filter=topic_filter or feed.get("topic"),
            tag_id=tag_id,
        )
    if kind == "papers":
        return await collect_papers(feed, ignore_cache=ignore_cache)
    if kind == "github":
        return await collect_github_releases(feed, ignore_cache=ignore_cache)
    if kind == "search":
        query = topic_filter or feed.get("topic") or "software development"
        return await collect_search_backfill(feed, query=query)
    return [], {"last_polled_at": "now()", "last_status": 400}


def _cold_topics(topics: list[str]) -> set[str]:
    """Topics with no active article at all — a 304 would leave them empty."""
    if not topics:
        return set()
    rows = (
        supabase.table("kb_articles")
        .select("topic")
        .eq("status", "active")
        .in_("topic", topics)
        .execute()
        .data
        or []
    )
    return set(topics) - {r["topic"] for r in rows if r.get("topic")}


def _tag_ids_by_name(names: list[str]) -> dict[str, int]:
    if not names:
        return {}
    rows = (
        supabase.table("interest_tags")
        .select("id, name")
        .in_("name", names)
        .execute()
        .data
        or []
    )
    return {r["name"]: r["id"] for r in rows if r.get("name")}


def _interest_topics(limit: int) -> list[tuple[str, int | None]]:
    """Distinct interest tag names that at least one user follows."""
    rows = supabase.table("user_interests").select("tag_id").execute().data or []
    tag_ids = sorted({r["tag_id"] for r in rows if r.get("tag_id")})
    if not tag_ids:
        return []
    tags = (
        supabase.table("interest_tags")
        .select("id, name")
        .in_("id", tag_ids)
        .execute()
        .data
        or []
    )
    return [(t["name"], t["id"]) for t in tags if t.get("name")][:limit]


async def _collect_hn_for_topics(
    feed: dict,
    target_topics: list[tuple[str, int | None]],
) -> tuple[list[CollectedItem], dict]:
    """The seeded HN row has topic=null, so a bare query returns all-time hits.

    Expanding it per target topic is what makes HN able to fill a category.
    """
    if not target_topics:
        return await _collect_one_feed(feed)

    merged: list[CollectedItem] = []
    poll: dict = {"last_polled_at": "now()", "last_status": 0}
    succeeded = False
    for topic, tag_id in target_topics:
        items, last_poll = await _collect_one_feed(feed, topic_filter=topic, tag_id=tag_id)
        merged.extend(items)
        if last_poll.get("last_status") == 200:
            succeeded = True
        else:
            poll["last_status"] = last_poll.get("last_status", 0)

    if succeeded:
        poll.update({"last_status": 200, "consecutive_failures": 0, "last_success_at": "now()"})
    else:
        poll["consecutive_failures"] = feed.get("consecutive_failures", 0) + 1
    return merged, poll


def _feeds_due(limit: int = 50, *, force: bool = False) -> list[dict]:
    rows = (
        supabase.table("source_feeds")
        .select("*")
        .eq("enabled", True)
        .order("last_polled_at")
        .limit(limit)
        .execute()
        .data
        or []
    )
    if force:
        return rows
    now = datetime.now(timezone.utc)
    due: list[dict] = []
    for row in rows:
        last = row.get("last_polled_at")
        interval = row.get("poll_interval_minutes") or 60
        if not last:
            due.append(row)
            continue
        last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        if last_dt + timedelta(minutes=interval) <= now:
            due.append(row)
    return due


def _update_feed_poll(feed_id: str | None, poll_update: dict) -> None:
    if not feed_id:
        return
    clean = {k: v for k, v in poll_update.items() if v != "now()"}
    if poll_update.get("last_polled_at") == "now()":
        clean["last_polled_at"] = datetime.now(timezone.utc).isoformat()
    if poll_update.get("last_success_at") == "now()":
        clean["last_success_at"] = datetime.now(timezone.utc).isoformat()

    feed = supabase.table("source_feeds").select("poll_interval_minutes, consecutive_not_modified, consecutive_failures").eq("id", feed_id).execute()
    base = feed.data[0] if feed.data else {}
    interval = base.get("poll_interval_minutes") or 60

    if poll_update.get("consecutive_not_modified", 0) > 2:
        interval = min(POLL_MAX, int(interval * 1.5))
    elif poll_update.get("last_success_at"):
        interval = max(POLL_MIN, int(interval * 0.85))

    if poll_update.get("consecutive_failures", 0) > 2:
        interval = min(POLL_MAX, interval + 30)

    clean["poll_interval_minutes"] = interval
    supabase.table("source_feeds").update(clean).eq("id", feed_id).execute()


async def _persist_items(items: list[CollectedItem]) -> dict:
    """Rank, dedup, and insert raw-tier rows. Returns per-pass counters."""
    deduped = dedup_items(items)
    clusters = assign_cluster_ids(deduped)
    inserted = 0
    skipped_unreachable = 0
    skipped_irrelevant = 0

    for item in deduped:
        if topic_relevance(item) < MIN_RELEVANCE:
            skipped_irrelevant += 1
            continue
        if item.source_adapter == "search" and not await url_is_reachable(item.url):
            skipped_unreachable += 1
            continue

        score = compute_score(item)
        if score <= 0:
            skipped_irrelevant += 1
            continue

        canon = item.url_canonical
        cluster_id = str(clusters.get(canon or item.url, ""))
        source_type = _classify_url(item.url)
        snippet = clean_snippet(item.snippet or "")
        one_liner = extractive_one_liner(item.title, snippet)
        row = apply_research_metadata(
            {
                "topic": item.topic or "General",
                "topic_kind": item.topic_kind,
                "tag_id": item.tag_id,
                "title": item.title,
                "one_liner": one_liner,
                "summary": one_liner,
                "body": snippet,
                "source_type": source_type,
                "citations": [{"type": source_type, "url": item.url, "title": item.title}],
                "url": item.url,
                "url_canonical": canon,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "tier": "raw",
                "status": "active",
                "cluster_id": cluster_id or None,
                "score": score,
                "source_adapter": item.source_adapter,
                "signals": item.signals,
            },
            snippet,
        )

        existing = (
            supabase.table("kb_articles")
            .select("id")
            .eq("topic", row["topic"])
            .eq("url_canonical", canon)
            .limit(1)
            .execute()
        )
        if existing.data:
            supabase.table("kb_articles").update({
                "score": score,
                "signals": item.signals,
                "collected_at": row["collected_at"],
            }).eq("id", existing.data[0]["id"]).execute()
            continue

        resp = supabase.table("kb_articles").insert(row).execute()
        if resp.data:
            inserted += 1

    return {
        "deduped": len(deduped),
        "inserted": inserted,
        "skipped_unreachable": skipped_unreachable,
        "skipped_irrelevant": skipped_irrelevant,
    }


async def run_fast_cycle(
    *,
    topics: list[str] | None = None,
    force: bool = False,
    allow_search_backfill: bool = False,
    job_id: str | None = None,
) -> dict:
    """Collect, rank, dedup, and persist raw-tier articles."""
    if not (isinstance(getattr(settings, "FEED_V3", False), bool) and settings.FEED_V3):
        from app.services.kb import refresh_knowledgebase
        await refresh_knowledgebase()
        return {"mode": "legacy", "inserted": 0}

    feeds = _feeds_due(force=force)
    if topics:
        topic_set = {t.lower() for t in topics}
        feeds = [f for f in feeds if (f.get("topic") or "").lower() in topic_set or f.get("kind") == "hn"]

    if topics:
        tag_map = _tag_ids_by_name(topics)
        target_topics = [(t, tag_map.get(t)) for t in topics]
    else:
        target_topics = _interest_topics(settings.COLLECT_MAX_CONCURRENCY)

    cold = _cold_topics([t for t, _ in target_topics])

    due_feeds = feeds[: settings.COLLECT_MAX_CONCURRENCY]
    feed_jobs.update(
        job_id,
        status="running",
        stage="collecting",
        feeds_total=len(due_feeds),
        topics_total=len(target_topics),
    )

    all_items: list[CollectedItem] = []
    for feed in due_feeds:
        try:
            if feed.get("kind") == "hn":
                items, poll = await _collect_hn_for_topics(feed, target_topics)
            else:
                items, poll = await _collect_one_feed(
                    feed,
                    ignore_cache=feed.get("topic") in cold,
                )
            _update_feed_poll(feed["id"], poll)
            all_items.extend(items)
        except Exception as exc:
            logger.exception("collector failed for %s: %s", feed.get("url"), exc)
        finally:
            feed_jobs.increment(job_id, "feeds_done")

    feed_jobs.update(job_id, stage="ranking", articles_collected=len(all_items))
    stats = await _persist_items(all_items)
    result = {"mode": "fast", "collected": len(all_items), **stats}
    feed_jobs.update(job_id, articles_inserted=stats["inserted"])

    if not allow_search_backfill or not target_topics:
        feed_jobs.update(
            job_id,
            topics_ready=len(target_topics) - len(_cold_topics([t for t, _ in target_topics])),
        )
        return result

    # Last resort: a topic with still no article gets a search-backfilled card
    # rather than an empty category.
    still_cold = _cold_topics([t for t, _ in target_topics])
    backfilled: list[str] = []
    for topic, tag_id in target_topics:
        if topic not in still_cold:
            continue
        virtual_feed = {
            "id": None,
            "kind": "search",
            "topic": topic,
            "tag_id": tag_id,
            "weight": 0.8,
        }
        try:
            items, _ = await _collect_one_feed(virtual_feed, topic_filter=topic, tag_id=tag_id)
        except Exception as exc:
            logger.exception("search backfill failed for %s: %s", topic, exc)
            continue
        backfill_stats = await _persist_items(items)
        backfilled.append(topic)
        result["collected"] += len(items)
        for key, value in backfill_stats.items():
            result[key] = result.get(key, 0) + value

    if backfilled:
        result["search_backfilled"] = backfilled

    feed_jobs.update(
        job_id,
        articles_collected=result["collected"],
        articles_inserted=result.get("inserted", 0),
        topics_ready=len(target_topics) - len(_cold_topics([t for t, _ in target_topics])),
    )
    return result


async def run_slow_cycle(
    *,
    topics: list[str] | None = None,
    job_id: str | None = None,
) -> dict:
    """Review raw-tier articles and promote/reject under LLM budget."""
    from app.agents.review_graph import run_review_cycle

    if not (isinstance(getattr(settings, "FEED_V3", False), bool) and settings.FEED_V3):
        return {"mode": "legacy", "reviewed": 0}

    feed_jobs.update(job_id, stage="reviewing")

    def _report(done: int, total: int) -> None:
        # The bar measures review against what collect inserted, so a batch
        # smaller than that (the usual case) still advances proportionally.
        feed_jobs.update(job_id, articles_reviewed=done)

    return await run_review_cycle(
        topics=topics,
        on_progress=_report if job_id else None,
    )
