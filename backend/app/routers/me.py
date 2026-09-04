import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, HTTPException
from fastapi import Depends as depends
from pydantic import BaseModel

from app.agents.discovery.graph import run_discovery_for_tag, run_discovery_for_user
from app.auth import get_current_user_id
from app.config import settings
from app.db import supabase

router = APIRouter()

# Categories are picked once at onboarding and changed only in Settings, so the
# cap is enforced here rather than left to the two call sites.
MAX_INTERESTS = 3

# A discovery task outlives its request, so it needs a strong reference or the
# loop may garbage-collect it mid-collect.
_interest_tasks: set[asyncio.Task] = set()


@router.get("/me")
async def get_me(user_id: str = depends(get_current_user_id)):
    result = supabase.table("profiles").select("id, created_at").eq("id", user_id).execute()
    if not result.data:
        return {"id": user_id, "created_at": None}
    return result.data[0]


@router.get("/me/interests")
async def get_interests(user_id: str = depends(get_current_user_id)):
    result = supabase.table("user_interests").select("tag_id").eq("user_id", user_id).execute()
    return {"tag_ids": [row["tag_id"] for row in (result.data or [])]}


class PutInterestsBody(BaseModel):
    tag_ids: list[int]


async def _trigger_discovery(
    user_id: str,
    tag_ids: list[int],
    *,
    new_tag_ids: list[int] | None = None,
    job_id: str | None = None,
):
    """Run the active discovery pipeline, always closing out the progress job."""
    from app.services import feed_jobs

    try:
        await _run_discovery(user_id, tag_ids, new_tag_ids=new_tag_ids, job_id=job_id)
    except Exception as e:
        logging.getLogger(__name__).exception("discovery failed for %s: %s", user_id, e)
        feed_jobs.finish(job_id, error=str(e)[:500])
    else:
        feed_jobs.finish(job_id)


async def _run_discovery(
    user_id: str,
    tag_ids: list[int],
    *,
    new_tag_ids: list[int] | None = None,
    job_id: str | None = None,
):
    if isinstance(getattr(settings, "FEED_V3", False), bool) and settings.FEED_V3:
        from app.services.feed_pipeline import run_fast_cycle, run_slow_cycle

        topics: list[str] = []
        ids = new_tag_ids if new_tag_ids is not None else tag_ids
        if ids:
            tag_rows = supabase.table("interest_tags").select("id, name").in_("id", ids).execute().data or []
            topics = [t["name"] for t in tag_rows if t.get("name")]

        # A brand-new interest must not be skipped because its feed was polled
        # recently, and needs a search fallback if it stays empty.
        await run_fast_cycle(
            topics=topics or None,
            force=True,
            allow_search_backfill=True,
            job_id=job_id,
        )
        await run_slow_cycle(topics=topics or None, job_id=job_id)
        return

    if settings.DISCOVERY_V2:
        await run_discovery_for_user(user_id)
        return

    if isinstance(getattr(settings, "KB_FEED", False), bool) and settings.KB_FEED:
        from app.agents.discovery.kb_graph import run_kb_discovery_for_topic

        ids = new_tag_ids if new_tag_ids is not None else tag_ids
        for tag_id in ids:
            tag_info = supabase.table("interest_tags").select("name").eq("id", tag_id).execute()
            tag_name = tag_info.data[0]["name"] if tag_info.data else ""
            if not tag_name:
                continue
            try:
                await run_kb_discovery_for_topic(tag_name, "interest", tag_id)
            except Exception:
                pass
        return

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    for tag_id in tag_ids:
        recent = supabase.table("articles").select("id").eq("tag_id", tag_id).gt(
            "published_at", cutoff
        ).limit(1).execute()
        if recent.data:
            continue
        tag_info = supabase.table("interest_tags").select("name").eq("id", tag_id).execute()
        tag_name = tag_info.data[0]["name"] if tag_info.data else ""
        try:
            await run_discovery_for_tag(tag_id, tag_name)
        except Exception:
            pass


@router.put("/me/interests")
async def put_interests(body: PutInterestsBody, user_id: str = depends(get_current_user_id)):
    supabase.table("profiles").upsert({"id": user_id}, on_conflict="id").execute()

    tag_ids = sorted(set(body.tag_ids))

    if not 1 <= len(tag_ids) <= MAX_INTERESTS:
        raise HTTPException(
            status_code=400,
            detail=f"Select between 1 and {MAX_INTERESTS} categories",
        )

    existing = supabase.table("interest_tags").select("id").in_("id", tag_ids).execute()
    existing_ids = {row["id"] for row in (existing.data or [])}
    unknown = [tid for tid in tag_ids if tid not in existing_ids]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown tag_ids: {unknown}")

    prev = supabase.table("user_interests").select("tag_id").eq("user_id", user_id).execute().data or []
    prev_ids = {row["tag_id"] for row in prev}

    supabase.table("user_interests").delete().eq("user_id", user_id).execute()
    rows = [{"user_id": user_id, "tag_id": tid} for tid in tag_ids]
    supabase.table("user_interests").insert(rows).execute()

    new_tag_ids = [tid for tid in tag_ids if tid not in prev_ids]

    # Created synchronously so the client can poll /feed/progress immediately
    # after this response, before the background task has done any work.
    from app.services import feed_jobs

    tag_names = [
        row["name"]
        for row in (
            supabase.table("interest_tags")
            .select("name")
            .in_("id", new_tag_ids or tag_ids)
            .execute()
            .data
            or []
        )
        if row.get("name")
    ]
    job_id = feed_jobs.create_job(user_id, tag_names)

    task = asyncio.create_task(
        _trigger_discovery(user_id, tag_ids, new_tag_ids=new_tag_ids, job_id=job_id)
    )
    _interest_tasks.add(task)
    task.add_done_callback(_interest_tasks.discard)

    return {"tag_ids": tag_ids, "job_id": job_id}


SOURCE_TYPES = ["official_docs", "github", "blog", "youtube"]


def _ensure_citation_prefs(user_id: str):
    supabase.table("profiles").upsert({"id": user_id}, on_conflict="id").execute()
    existing = supabase.table("citation_prefs").select("source_type").eq("user_id", user_id).execute()
    existing_types = {row["source_type"] for row in (existing.data or [])}
    missing = [st for st in SOURCE_TYPES if st not in existing_types]
    if missing:
        supabase.table("citation_prefs").insert(
            [{"user_id": user_id, "source_type": st, "enabled": True} for st in missing]
        ).execute()


@router.get("/me/citation-prefs")
async def get_citation_prefs(user_id: str = depends(get_current_user_id)):
    _ensure_citation_prefs(user_id)
    result = supabase.table("citation_prefs").select("source_type, enabled").eq("user_id", user_id).execute()
    return {"prefs": {row["source_type"]: row["enabled"] for row in (result.data or [])}}


class PutCitationPrefsBody(BaseModel):
    prefs: dict[str, bool]


@router.put("/me/citation-prefs")
async def put_citation_prefs(body: PutCitationPrefsBody, user_id: str = depends(get_current_user_id)):
    _ensure_citation_prefs(user_id)
    unknown = [st for st in body.prefs if st not in SOURCE_TYPES]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown source types: {unknown}")
    for source_type, enabled in body.prefs.items():
        supabase.table("citation_prefs").update({"enabled": enabled}).eq("user_id", user_id).eq(
            "source_type", source_type
        ).execute()
    result = supabase.table("citation_prefs").select("source_type, enabled").eq("user_id", user_id).execute()
    return {"prefs": {row["source_type"]: row["enabled"] for row in (result.data or [])}}


DELETE_TABLES = [
    "tracked_dependencies",
    "user_interests",
    "notification_settings",
    "citation_prefs",
]


@router.delete("/me")
async def delete_me(user_id: str = depends(get_current_user_id)):
    for table in DELETE_TABLES:
        supabase.table(table).delete().eq("user_id", user_id).execute()
    supabase.table("profiles").delete().eq("id", user_id).execute()

    admin_url = f"{settings.SUPABASE_URL}/auth/v1/admin/users/{user_id}"
    admin_headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
    }
    try:
        resp = httpx.delete(admin_url, headers=admin_headers, timeout=10)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Account data deleted but auth removal failed: {e.response.status_code}. Contact support if needed.",
        )

    return {"status": "deleted"}
