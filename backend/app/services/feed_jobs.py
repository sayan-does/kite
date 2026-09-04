"""Progress tracking for a single feed build.

The collect and review cycles report counters here as they run so the Discover
screen can show a real progress bar. Every write is best-effort: a failure to
record progress must never abort the build that is actually producing articles.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.db import supabase

logger = logging.getLogger(__name__)

# Collect is the long pole and the part the user is waiting on, so it owns most
# of the bar. Review only sharpens summaries for articles that already exist.
COLLECT_WEIGHT = 60
REVIEW_WEIGHT = 40

# A build with nothing left to review still has to finish somewhere below 100,
# or the bar would sit full while the feed is empty.
_MIN_VISIBLE_PERCENT = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_percent(job: dict) -> int:
    """Collect and review progress, weighted, clamped, never regressing."""
    feeds_total = job.get("feeds_total") or 0
    feeds_done = job.get("feeds_done") or 0
    collect = COLLECT_WEIGHT * (min(feeds_done, feeds_total) / feeds_total) if feeds_total else 0.0

    # There is no reliable count of what the review loop will pick up, so
    # reviewed articles are measured against what collect actually inserted.
    inserted = job.get("articles_inserted") or 0
    reviewed = job.get("articles_reviewed") or 0
    review = REVIEW_WEIGHT * (min(reviewed, inserted) / inserted) if inserted else 0.0

    if job.get("stage") == "done" or job.get("status") in {"done", "failed"}:
        return 100

    candidate = int(round(collect + review))
    monotonic = max(job.get("percent") or 0, candidate)
    return max(_MIN_VISIBLE_PERCENT, min(99, monotonic))


def create_job(user_id: str | None, topics: list[str]) -> str | None:
    """Insert a queued job and return its id, or None if tracking is unavailable."""
    row = {
        "user_id": user_id,
        "status": "pending",
        "stage": "queued",
        "topics": topics,
        "topics_total": len(topics),
        "percent": _MIN_VISIBLE_PERCENT,
    }
    try:
        resp = supabase.table("feed_build_jobs").insert(row).execute()
    except Exception:
        logger.warning("could not create feed build job", exc_info=True)
        return None
    if not resp.data:
        return None
    return str(resp.data[0]["id"])


def _read(job_id: str) -> dict | None:
    try:
        resp = supabase.table("feed_build_jobs").select("*").eq("id", job_id).limit(1).execute()
    except Exception:
        logger.warning("could not read feed build job %s", job_id, exc_info=True)
        return None
    return resp.data[0] if resp.data else None


def update(job_id: str | None, **fields: Any) -> None:
    """Apply absolute field values and recompute percent from the merged row."""
    if not job_id:
        return
    current = _read(job_id)
    if current is None:
        return

    merged = {**current, **fields}
    patch = {**fields, "percent": compute_percent(merged), "updated_at": _now()}
    try:
        supabase.table("feed_build_jobs").update(patch).eq("id", job_id).execute()
    except Exception:
        logger.warning("could not update feed build job %s", job_id, exc_info=True)


def increment(job_id: str | None, field: str, by: int = 1) -> None:
    """Read-modify-write a counter.

    Cycles are driven from a single task per job, so there is no concurrent
    writer to lose an update to.
    """
    if not job_id:
        return
    current = _read(job_id)
    if current is None:
        return
    update(job_id, **{field: (current.get(field) or 0) + by})


def finish(job_id: str | None, *, error: str | None = None, topics_ready: int | None = None) -> None:
    if not job_id:
        return
    patch: dict[str, Any] = {
        "status": "failed" if error else "done",
        "stage": "done",
        "percent": 100,
        "error": error,
        "finished_at": _now(),
        "updated_at": _now(),
    }
    if topics_ready is not None:
        patch["topics_ready"] = topics_ready
    try:
        supabase.table("feed_build_jobs").update(patch).eq("id", job_id).execute()
    except Exception:
        logger.warning("could not finish feed build job %s", job_id, exc_info=True)


def latest_for_user(user_id: str) -> dict | None:
    try:
        resp = (
            supabase.table("feed_build_jobs")
            .select("*")
            .eq("user_id", user_id)
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception:
        logger.warning("could not load latest feed build job", exc_info=True)
        return None
    return resp.data[0] if resp.data else None
