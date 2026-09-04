from dataclasses import dataclass
from typing import Literal

from app.config import settings
from app.db import supabase


@dataclass(frozen=True)
class KbTopic:
    topic: str
    topic_kind: Literal["interest", "stack"]
    tag_id: int | None


def resolve_kb_topics() -> list[KbTopic]:
    topics: dict[tuple[str, str], KbTopic] = {}

    interest_rows = supabase.table("user_interests").select("tag_id").execute().data or []
    distinct_tag_ids = {row["tag_id"] for row in interest_rows if row.get("tag_id") is not None}
    if distinct_tag_ids:
        tag_rows = (
            supabase.table("interest_tags")
            .select("id, name")
            .in_("id", list(distinct_tag_ids))
            .execute()
            .data
            or []
        )
        for tag in tag_rows:
            key = (tag["name"], "interest")
            topics[key] = KbTopic(topic=tag["name"], topic_kind="interest", tag_id=tag["id"])

    dep_rows = supabase.table("tracked_dependencies").select("user_id, package_name").execute().data or []
    package_users: dict[str, set[str]] = {}
    for row in dep_rows:
        pkg = row.get("package_name")
        uid = row.get("user_id")
        if pkg and uid:
            package_users.setdefault(pkg, set()).add(uid)

    min_users = settings.KB_STACK_MIN_USERS
    for package_name, user_ids in package_users.items():
        if len(user_ids) >= min_users:
            key = (package_name, "stack")
            topics[key] = KbTopic(topic=package_name, topic_kind="stack", tag_id=None)

    return sorted(topics.values(), key=lambda t: t.topic)


async def refresh_knowledgebase() -> None:
    from app.agents.discovery.kb_graph import run_kb_discovery_for_topic

    for topic in resolve_kb_topics():
        try:
            await run_kb_discovery_for_topic(topic.topic, topic.topic_kind, topic.tag_id)
        except Exception as exc:
            print(f"KB refresh failed for {topic.topic}: {exc}")


def cleanup_knowledgebase() -> None:
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.KB_RETENTION_DAYS)
    (
        supabase.table("kb_articles")
        .delete()
        .lt("fetched_at", cutoff.isoformat())
        .execute()
    )
