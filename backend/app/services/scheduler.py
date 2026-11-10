from datetime import datetime, timedelta, timezone
import logging
from typing import Any

import httpx

from app.agents.discovery.graph import run_discovery_for_tag, run_discovery_for_user
from app.agents.dependency.graph import run_dependency_update
from app.config import settings
from app.db import supabase
from app.services.email import send_digest
from app.services.kb import cleanup_knowledgebase, refresh_knowledgebase

TIMELINE_RETENTION_DAYS = 90
logger = logging.getLogger(__name__)


async def run_daily() -> dict[str, Any]:
    """
    Run the complete daily job cycle and return results.
    
    Returns a dict with timing info, results from each step, and any errors encountered.
    """
    start_time = datetime.now(timezone.utc)
    job_id = None
    results: dict[str, Any] = {
        "started_at": start_time.isoformat(),
        "fast_cycle": None,
        "slow_cycle": None,
        "dependency_updates": None,
        "timeline_pruned": None,
        "digests_sent": 0,
        "kb_cleaned": None,
        "errors": [],
    }
    
    try:
        # Create job tracking record if table exists
        try:
            job_record = supabase.table("job_runs").insert({
                "job_type": "daily",
                "status": "running",
                "started_at": start_time.isoformat(),
            }).execute()
            job_id = job_record.data[0]["id"] if job_record.data else None
        except Exception as e:
            logger.warning("Could not create job_runs record: %s", e)
        
        # Feed pipeline
        if isinstance(getattr(settings, "FEED_V3", False), bool) and settings.FEED_V3:
            try:
                from app.services.feed_pipeline import run_fast_cycle, run_slow_cycle
                from app.services.prefill import all_category_names

                # A bare run_fast_cycle() falls back to the categories some user already
                # follows, which would let unfollowed ones go cold and make them a slow
                # first pick at onboarding.
                results["fast_cycle"] = await run_fast_cycle(topics=all_category_names() or None)
                logger.info("Fast cycle completed: %s", results["fast_cycle"])
            except Exception as e:
                error_msg = f"Fast cycle failed: {str(e)}"
                logger.exception(error_msg)
                results["errors"].append(error_msg)
            
            try:
                results["slow_cycle"] = await run_slow_cycle()
                logger.info("Slow cycle completed: %s", results["slow_cycle"])
            except Exception as e:
                error_msg = f"Slow cycle failed: {str(e)}"
                logger.exception(error_msg)
                results["errors"].append(error_msg)
                
        elif settings.KB_FEED:
            try:
                await refresh_knowledgebase()
                results["kb_refreshed"] = True
                logger.info("Knowledge base refreshed")
            except Exception as e:
                error_msg = f"KB refresh failed: {str(e)}"
                logger.exception(error_msg)
                results["errors"].append(error_msg)
        else:
            try:
                await _run_discovery_graphs()
                results["discovery_complete"] = True
                logger.info("Discovery graphs completed")
            except Exception as e:
                error_msg = f"Discovery graphs failed: {str(e)}"
                logger.exception(error_msg)
                results["errors"].append(error_msg)
        
        # Dependency updates
        try:
            await _run_dependency_graphs()
            results["dependency_updates"] = "completed"
            logger.info("Dependency updates completed")
        except Exception as e:
            error_msg = f"Dependency updates failed: {str(e)}"
            logger.exception(error_msg)
            results["errors"].append(error_msg)
        
        # Timeline pruning
        try:
            pruned_count = prune_package_version_timeline()
            results["timeline_pruned"] = pruned_count
            logger.info("Timeline pruned: %d records", pruned_count)
        except Exception as e:
            error_msg = f"Timeline pruning failed: {str(e)}"
            logger.exception(error_msg)
            results["errors"].append(error_msg)
        
        # Send digests
        try:
            digest_count = await _send_digests()
            results["digests_sent"] = digest_count
            logger.info("Digests sent: %d", digest_count)
        except Exception as e:
            error_msg = f"Digest sending failed: {str(e)}"
            logger.exception(error_msg)
            results["errors"].append(error_msg)
        
        # Cleanup
        if settings.KB_FEED or settings.FEED_V3:
            try:
                cleanup_knowledgebase()
                results["kb_cleaned"] = True
                logger.info("Knowledge base cleaned")
            except Exception as e:
                error_msg = f"KB cleanup failed: {str(e)}"
                logger.exception(error_msg)
                results["errors"].append(error_msg)
        
        # Calculate duration and mark as completed
        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()
        results["completed_at"] = end_time.isoformat()
        results["duration_seconds"] = duration
        
        # Update job record
        if job_id:
            try:
                supabase.table("job_runs").update({
                    "status": "completed" if not results["errors"] else "completed_with_errors",
                    "completed_at": end_time.isoformat(),
                    "duration_seconds": duration,
                    "result": results,
                }).eq("id", job_id).execute()
            except Exception as e:
                logger.warning("Could not update job_runs record: %s", e)
        
        return results
        
    except Exception as e:
        # Fatal error - update job record and re-raise
        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()
        error_msg = f"Fatal error in run_daily: {str(e)}"
        logger.exception(error_msg)
        
        results["errors"].append(error_msg)
        results["completed_at"] = end_time.isoformat()
        results["duration_seconds"] = duration
        
        if job_id:
            try:
                supabase.table("job_runs").update({
                    "status": "failed",
                    "completed_at": end_time.isoformat(),
                    "duration_seconds": duration,
                    "error": error_msg,
                    "result": results,
                }).eq("id", job_id).execute()
            except Exception as exc:
                logger.warning("Could not update failed job_runs record: %s", exc)
        
        raise


def prune_package_version_timeline(retention_days: int = TIMELINE_RETENTION_DAYS) -> int:
    """Delete timeline rows older than the rolling retention window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_iso = cutoff.isoformat()

    # Prefer published_at; fall back to ingested_at when published_at is null.
    stale_by_published = (
        supabase.table("package_version_timeline")
        .select("id")
        .lt("published_at", cutoff_iso)
        .execute()
        .data
        or []
    )
    stale_null_published = (
        supabase.table("package_version_timeline")
        .select("id")
        .is_("published_at", "null")
        .lt("ingested_at", cutoff_iso)
        .execute()
        .data
        or []
    )
    ids = {row["id"] for row in stale_by_published + stale_null_published}
    deleted = 0
    for row_id in ids:
        supabase.table("package_version_timeline").delete().eq("id", row_id).execute()
        deleted += 1
    return deleted


async def _run_discovery_graphs():
    if settings.DISCOVERY_V2:
        user_ids = _collect_user_ids()
        for user_id in user_ids:
            await run_discovery_for_user(user_id)
        return

    tag_result = supabase.table("user_interests").select("tag_id").execute()
    distinct_tag_ids = {row["tag_id"] for row in (tag_result.data or [])}
    for tag_id in distinct_tag_ids:
        tag_info = supabase.table("interest_tags").select("name").eq("id", tag_id).execute()
        tag_name = tag_info.data[0]["name"] if tag_info.data else ""
        await run_discovery_for_tag(tag_id, tag_name)


async def _run_dependency_graphs():
    dep_result = supabase.table("tracked_dependencies").select("ecosystem, package_name").execute()
    distinct_packages = {(row["ecosystem"], row["package_name"]) for row in (dep_result.data or [])}
    for ecosystem, package_name in distinct_packages:
        await run_dependency_update(ecosystem, package_name)


async def _send_digests() -> int:
    """Send email digests to users and return count of emails sent."""
    user_ids = _collect_user_ids()
    sent_count = 0

    for user_id in user_ids:
        items = _collect_new_items(user_id)

        if not settings.KB_FEED and not items:
            continue

        settings_rows = (supabase.table("notification_settings")
                         .select("*").eq("user_id", user_id).execute().data or [])
        settings_map = {(r["category"], r["channel"]): r["enabled"] for r in settings_rows}

        email_enabled_discovery = settings_map.get(("discovery", "email"), True)
        email_enabled_dependency = settings_map.get(("dependency", "email"), True)

        # Filter each category independently so disabling one never suppresses the other.
        filtered = [
            *([i for i in items if i["type"] == "article"] if email_enabled_discovery else []),
            *([i for i in items if i["type"] == "dependency_update"] if email_enabled_dependency else []),
        ]

        if not settings.KB_FEED and not filtered:
            continue

        if filtered:
            email = _get_user_email(user_id)
            if email:
                await send_digest(email, filtered)
                sent_count += 1

        if settings.KB_FEED:
            supabase.table("profiles").update({
                "last_digest_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", user_id).execute()
    
    return sent_count


def _collect_user_ids() -> set:
    user_ids = set()
    for row in (supabase.table("user_interests").select("user_id").execute().data or []):
        user_ids.add(row["user_id"])
    for row in (supabase.table("tracked_dependencies").select("user_id").execute().data or []):
        user_ids.add(row["user_id"])
    return user_ids


def _parse_timestamp(value: str | None):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _collect_new_items(user_id: str) -> list:
    items = []

    if settings.KB_FEED:
        profile = (
            supabase.table("profiles")
            .select("last_digest_at")
            .eq("id", user_id)
            .execute()
        )
        last_digest_at = profile.data[0].get("last_digest_at") if profile.data else None
        last_digest_ts = _parse_timestamp(last_digest_at)

        feed_rows = (
            supabase.rpc(
                "get_user_feed",
                {"uid": user_id, "lim": 1000, "off": 0, "topic_filter": None},
            )
            .execute()
            .data
            or []
        )
        # Prefer reviewed-tier items; fall back to raw when nothing reviewed yet.
        reviewed = [r for r in feed_rows if r.get("tier") == "reviewed"]
        candidates = reviewed if reviewed else feed_rows

        for row in candidates:
            fetched_ts = _parse_timestamp(row.get("fetched_at"))
            if last_digest_ts is None or (fetched_ts and fetched_ts > last_digest_ts):
                citations = row.get("citations") or []
                link = row.get("url") or (citations[0].get("url") if citations else "")
                items.append({
                    "type": "article",
                    "title": row["title"],
                    "summary": row.get("one_liner") or row["summary"],
                    "url": link,
                    "tier": row.get("tier", "raw"),
                })
    else:
        tags = supabase.table("user_interests").select("tag_id").eq("user_id", user_id).execute().data or []
        if tags:
            tag_ids = [t["tag_id"] for t in tags]
            articles = supabase.table("articles").select("title, summary").in_("tag_id", tag_ids).execute().data or []
            for a in articles:
                items.append({"type": "article", "title": a["title"], "summary": a["summary"]})

    deps = (supabase.table("tracked_dependencies")
            .select("ecosystem, package_name").eq("user_id", user_id).execute().data or [])
    if deps:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        for dep in deps:
            updates = (supabase.table("dependency_updates")
                       .select("package_name, version, update_type, summary, published_at")
                       .eq("ecosystem", dep["ecosystem"])
                       .eq("package_name", dep["package_name"])
                       .gte("published_at", since.isoformat())
                       .order("published_at", desc=True)
                       .limit(3)
                       .execute().data or [])
            for u in updates:
                items.append({
                    "type": "dependency_update",
                    "package_name": u["package_name"],
                    "version": u["version"],
                    "update_type": u["update_type"],
                    "summary": u["summary"],
                })

    return items


def _get_user_email(user_id: str) -> str | None:
    try:
        url = f"{settings.SUPABASE_URL}/auth/v1/admin/users/{user_id}"
        headers = {
            "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        }
        resp = httpx.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json().get("email")
    except Exception:
        return None
