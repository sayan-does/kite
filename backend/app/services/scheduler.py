from datetime import datetime, timedelta, timezone

import httpx

from app.agents.discovery.graph import run_discovery_for_tag, run_discovery_for_user
from app.agents.dependency.graph import run_dependency_update
from app.config import settings
from app.db import supabase
from app.services.email import send_digest
from app.services.kb import cleanup_knowledgebase, refresh_knowledgebase

TIMELINE_RETENTION_DAYS = 90


async def run_daily():
    if isinstance(getattr(settings, "FEED_V3", False), bool) and settings.FEED_V3:
        from app.services.feed_pipeline import run_fast_cycle, run_slow_cycle
        from app.services.prefill import all_category_names

        # A bare run_fast_cycle() falls back to the categories some user already
        # follows, which would let unfollowed ones go cold and make them a slow
        # first pick at onboarding.
        await run_fast_cycle(topics=all_category_names() or None)
        await run_slow_cycle()
    elif settings.KB_FEED:
        await refresh_knowledgebase()
    else:
        await _run_discovery_graphs()
    await _run_dependency_graphs()
    prune_package_version_timeline()
    await _send_digests()
    if settings.KB_FEED or settings.FEED_V3:
        cleanup_knowledgebase()


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


async def _send_digests():
    user_ids = _collect_user_ids()

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

        if settings.KB_FEED:
            supabase.table("profiles").update({
                "last_digest_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", user_id).execute()


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
