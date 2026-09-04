import asyncio
import logging
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth import get_current_user_id
from app.config import settings
from app.db import supabase
from app.services import feed_jobs
from app.services.article_enrich import fallback_payload, needs_enrichment, summarize_article
from app.services.feed_pipeline import run_fast_cycle
from app.services.rate_limit import check_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter()

PREFETCH_TAG_CAP = 15
CACHE_KEY_ALL = "__all__"

# How long a refresh request waits before handing the collect off to the
# background and letting the client poll.
REFRESH_WAIT_SECONDS = 10.0

# Tasks that outlive their request need a strong reference or the loop may
# garbage-collect them mid-collect.
_background_collects: set[asyncio.Task] = set()


class FeedStateUpdate(BaseModel):
    seen: Optional[bool] = None
    read: Optional[bool] = None
    dismissed: Optional[bool] = None


@router.get("/interest-tags")
async def list_interest_tags():
    result = supabase.table("interest_tags").select("id, name, category").order("id").execute()
    return {"tags": result.data}


def _filter_citations(citations: list, disabled_types: set) -> list:
    if not disabled_types:
        return citations
    return [c for c in citations if c.get("type") not in disabled_types]


def _absolute_url(raw: str | None) -> str | None:
    """Ensure feed links are absolute https URLs for the client."""
    if not raw or not str(raw).strip():
        return None
    value = str(raw).strip()
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("//"):
        return f"https:{value}"
    if "." in value.split("/")[0]:
        return f"https://{value.lstrip('/')}"
    return value


def _article_payload(a: dict, disabled_types: set, *, include_body: bool = True) -> dict:
    citations = _filter_citations(a.get("citations") or [], disabled_types)
    youtube_url = a.get("youtube_url")
    if "youtube" in disabled_types:
        youtube_url = None
    payload = {
        "id": a["id"],
        "tag_id": a.get("tag_id"),
        "title": a["title"],
        "summary": a["summary"],
        "citations": [
            {**c, "url": _absolute_url(c.get("url")) or c.get("url")}
            for c in citations
            if _absolute_url(c.get("url")) or c.get("url")
        ],
        "youtube_url": youtube_url,
        "url": _absolute_url(a.get("url")),
        "published_at": a.get("published_at"),
    }
    if include_body:
        payload["body"] = a.get("body")
    if settings.DISCOVERY_V2 or settings.KB_FEED:
        payload.update({
            "one_liner": a.get("one_liner"),
            "source_type": a.get("source_type"),
            "source": a.get("source"),
            "topic": a.get("topic"),
            "fetched_at": a.get("fetched_at"),
            "is_research": bool(a.get("is_research", False)),
            "tier": a.get("tier", "raw"),
            "score": a.get("score"),
        })
        if a.get("source_type") in disabled_types:
            payload["source_type"] = None
    return payload


def _disabled_citation_types(user_id: str) -> set:
    prefs_resp = (
        supabase.table("citation_prefs")
        .select("source_type, enabled")
        .eq("user_id", user_id)
        .execute()
    )
    return {
        row["source_type"]
        for row in (prefs_resp.data or [])
        if not row["enabled"]
    }


def _interest_tag_names(user_id: str) -> list[str]:
    interests = (
        supabase.table("user_interests")
        .select("tag_id")
        .eq("user_id", user_id)
        .execute()
    )
    tag_ids = [row["tag_id"] for row in (interests.data or [])]
    if not tag_ids:
        return []
    tags = (
        supabase.table("interest_tags")
        .select("name")
        .in_("id", tag_ids)
        .execute()
    )
    return [row["name"] for row in (tags.data or []) if row.get("name")]


def _user_can_access_kb_article(user_id: str, article: dict) -> bool:
    """Match get_user_feed visibility rules."""
    if article.get("status") != "active":
        return False

    interests = (
        supabase.table("user_interests")
        .select("tag_id")
        .eq("user_id", user_id)
        .execute()
    )
    tag_ids = {row["tag_id"] for row in (interests.data or [])}
    if article.get("tag_id") in tag_ids:
        return True

    if article.get("topic_kind") == "stack":
        tracked = (
            supabase.table("tracked_dependencies")
            .select("package_name")
            .eq("user_id", user_id)
            .execute()
        )
        package_names = {row["package_name"] for row in (tracked.data or [])}
        if article.get("topic") in package_names:
            return True

    return False


def _kb_feed_page(
    user_id: str,
    tag: str | None,
    page: int,
    disabled_types: set,
    *,
    include_body: bool,
) -> dict:
    page_size = 20
    offset = (page - 1) * page_size
    rpc_args = {
        "uid": user_id,
        "lim": page_size + 1,
        "off": offset,
        "topic_filter": tag,
    }
    result = supabase.rpc("get_user_feed", rpc_args).execute()
    articles_data = result.data or []

    has_next = len(articles_data) > page_size
    if has_next:
        articles_data = articles_data[:page_size]

    for a in articles_data:
        a["source"] = a.get("topic_kind")

    articles = [_article_payload(a, disabled_types, include_body=include_body) for a in articles_data]
    return {"articles": articles, "page": page, "has_next": has_next}


@router.get("/feed/articles/{kb_article_id}")
async def get_feed_article(
    kb_article_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Return one feed card with body; enrich on demand when still raw."""
    if not settings.KB_FEED:
        raise HTTPException(status_code=404, detail="Article detail requires KB_FEED")

    check_rate_limit(user_id)

    article_resp = (
        supabase.table("kb_articles")
        .select("*")
        .eq("id", kb_article_id)
        .limit(1)
        .execute()
    )
    if not article_resp.data:
        raise HTTPException(status_code=404, detail="Article not found")

    row = article_resp.data[0]
    if not _user_can_access_kb_article(user_id, row):
        raise HTTPException(status_code=404, detail="Article not found")

    generating = False
    if needs_enrichment(row):
        summary = await summarize_article(row, use_budget=False)
        if summary:
            update = {
                **summary,
                "tier": "reviewed",
                "score": float(row.get("score") or 0) * 1.15,
            }
            supabase.table("kb_articles").update(update).eq("id", kb_article_id).execute()
            row = {**row, **update}
        else:
            fallback = fallback_payload(row)
            row = {**row, **fallback}
            generating = True

    row["source"] = row.get("topic_kind")
    disabled_types = _disabled_citation_types(user_id)
    article = _article_payload(row, disabled_types, include_body=True)
    return {"article": article, "generating": generating}


@router.get("/feed")
async def get_feed(
    tag: str = Query(None),
    page: int = Query(1, ge=1),
    view: Literal["list", "detail"] = Query("list"),
    user_id: str = Depends(get_current_user_id),
):
    include_body = view == "detail"
    disabled_types = _disabled_citation_types(user_id)

    if settings.KB_FEED:
        return _kb_feed_page(user_id, tag, page, disabled_types, include_body=include_body)

    if settings.DISCOVERY_V2:
        query = (
            supabase.table("articles")
            .select("*")
            .eq("user_id", user_id)
            .order("fetched_at", desc=True)
            .limit(10)
        )
        if tag:
            query = query.eq("topic", tag)
        result = query.execute()
        articles_data = result.data or []
        articles = [
            _article_payload(a, disabled_types, include_body=include_body) for a in articles_data
        ]
        return {"articles": articles, "page": 1, "has_next": False}

    followed = supabase.table("user_interests").select("tag_id").eq("user_id", user_id).execute()
    followed_ids = [row["tag_id"] for row in (followed.data or [])]
    if not followed_ids:
        return {"articles": [], "page": page, "has_next": False}

    tag_id_filter = None
    if tag:
        tag_res = supabase.table("interest_tags").select("id").eq("name", tag).maybe_single().execute()
        if not tag_res.data:
            raise HTTPException(status_code=404, detail="Unknown tag")
        tag_id_filter = tag_res.data["id"]

    query = supabase.table("articles").select("*").in_("tag_id", followed_ids).order("published_at", desc=True)
    if tag_id_filter:
        query = query.eq("tag_id", tag_id_filter)

    page_size = 20
    offset = (page - 1) * page_size
    query = query.range(offset, offset + page_size)
    result = query.execute()
    articles_data = result.data or []

    has_next = len(articles_data) > page_size
    if has_next:
        articles_data = articles_data[:page_size]

    articles = [
        _article_payload(a, disabled_types, include_body=include_body) for a in articles_data
    ]
    return {"articles": articles, "page": page, "has_next": has_next}


@router.get("/feed/prefetch")
async def prefetch_feeds(
    view: Literal["list", "detail"] = Query("list"),
    user_id: str = Depends(get_current_user_id),
):
    if not settings.KB_FEED:
        raise HTTPException(status_code=404, detail="Prefetch requires KB_FEED")

    include_body = view == "detail"
    disabled_types = _disabled_citation_types(user_id)
    tag_names = _interest_tag_names(user_id)[:PREFETCH_TAG_CAP]

    feeds: dict[str, dict] = {}
    all_feed = _kb_feed_page(user_id, None, 1, disabled_types, include_body=include_body)
    feeds[CACHE_KEY_ALL] = {
        "articles": all_feed["articles"],
        "has_next": all_feed["has_next"],
    }

    for name in tag_names:
        page = _kb_feed_page(user_id, name, 1, disabled_types, include_body=include_body)
        feeds[name] = {
            "articles": page["articles"],
            "has_next": page["has_next"],
        }

    return {
        "feeds": feeds,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/feed/progress")
async def get_feed_progress(user_id: str = Depends(get_current_user_id)):
    """Real build progress for the Discover loading state.

    Reports the latest build job alongside a live count of what is already
    readable, so the client can show articles landing before the job finishes.
    """
    job = feed_jobs.latest_for_user(user_id)

    tag_names = _interest_tag_names(user_id)
    ready_rows = (
        supabase.table("kb_articles")
        .select("topic")
        .eq("status", "active")
        .in_("topic", tag_names)
        .execute()
        .data
        or []
    ) if tag_names else []

    per_category: dict[str, int] = {name: 0 for name in tag_names}
    for row in ready_rows:
        topic = row.get("topic")
        if topic in per_category:
            per_category[topic] += 1

    categories_ready = sum(1 for count in per_category.values() if count > 0)

    if job is None:
        # No build has ever been recorded for this user: if articles already
        # exist the feed is simply ready, otherwise nothing has started.
        return {
            "status": "done" if categories_ready else "idle",
            "stage": "done" if categories_ready else "queued",
            "percent": 100 if categories_ready else 0,
            "articles_ready": len(ready_rows),
            "categories_total": len(tag_names),
            "categories_ready": categories_ready,
            "per_category": per_category,
            "topics": tag_names,
            "error": None,
        }

    return {
        "status": job.get("status"),
        "stage": job.get("stage"),
        "percent": job.get("percent") or 0,
        "feeds_total": job.get("feeds_total") or 0,
        "feeds_done": job.get("feeds_done") or 0,
        "articles_collected": job.get("articles_collected") or 0,
        "articles_inserted": job.get("articles_inserted") or 0,
        "articles_reviewed": job.get("articles_reviewed") or 0,
        "articles_ready": len(ready_rows),
        "categories_total": len(tag_names),
        "categories_ready": categories_ready,
        "per_category": per_category,
        "topics": job.get("topics") or tag_names,
        "error": job.get("error"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
    }


def _spawn_collect(tag: str) -> asyncio.Task:
    task = asyncio.create_task(
        run_fast_cycle(topics=[tag], force=True, allow_search_backfill=True)
    )
    _background_collects.add(task)

    def _done(finished: asyncio.Task) -> None:
        _background_collects.discard(finished)
        if not finished.cancelled() and finished.exception():
            logger.exception(
                "refresh collect failed for %s", tag, exc_info=finished.exception()
            )

    task.add_done_callback(_done)
    return task


@router.post("/feed/refresh")
async def refresh_feed_topic(
    tag: str = Query(..., min_length=1),
    view: Literal["list", "detail"] = Query("list"),
    user_id: str = Depends(get_current_user_id),
):
    """Force a collect for one category and return whatever landed in time."""
    if not settings.KB_FEED:
        raise HTTPException(status_code=404, detail="Refresh requires KB_FEED")

    check_rate_limit(user_id)

    tag_row = (
        supabase.table("interest_tags")
        .select("id, name")
        .eq("name", tag)
        .limit(1)
        .execute()
    )
    if not tag_row.data:
        raise HTTPException(status_code=404, detail="Unknown tag")

    task = _spawn_collect(tag)
    done, _pending = await asyncio.wait({task}, timeout=REFRESH_WAIT_SECONDS)

    # A collect still running is deliberately left alone; the client polls.
    timed_out = task not in done
    inserted = 0
    if not timed_out and not task.cancelled() and task.exception() is None:
        inserted = int(task.result().get("inserted") or 0)

    disabled_types = _disabled_citation_types(user_id)
    page = _kb_feed_page(user_id, tag, 1, disabled_types, include_body=view == "detail")
    return {**page, "timed_out": timed_out, "inserted": inserted}


@router.post("/feed/{kb_article_id}/state")
async def update_feed_state(
    kb_article_id: str,
    body: FeedStateUpdate,
    user_id: str = Depends(get_current_user_id),
):
    article_resp = (
        supabase.table("kb_articles")
        .select("id")
        .eq("id", kb_article_id)
        .execute()
    )
    if not article_resp.data:
        raise HTTPException(status_code=404, detail="Article not found")

    if body.seen is None and body.read is None and body.dismissed is None:
        raise HTTPException(status_code=400, detail="At least one state field required")

    existing_resp = (
        supabase.table("user_article_state")
        .select("seen, read, dismissed")
        .eq("user_id", user_id)
        .eq("kb_article_id", kb_article_id)
        .execute()
    )
    prev = existing_resp.data[0] if existing_resp.data else {}

    row = {
        "user_id": user_id,
        "kb_article_id": kb_article_id,
        "seen": body.seen if body.seen is not None else prev.get("seen", False),
        "read": body.read if body.read is not None else prev.get("read", False),
        "dismissed": body.dismissed if body.dismissed is not None else prev.get("dismissed", False),
    }
    supabase.table("user_article_state").upsert(
        row, on_conflict="user_id, kb_article_id"
    ).execute()
    return {"ok": True}
