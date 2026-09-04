"""GitHub Releases Atom feeds for tracked stack packages and category feeds."""

from __future__ import annotations

import re

import feedparser

from app.collectors.base import CollectedItem, conditional_get, parse_datetime
from app.services.extractive import clean_snippet
from app.db import supabase

_GH_REPO_RE = re.compile(r"github\.com/([^/]+/[^/#?]+)")


def _github_release_atom_url(package_name: str) -> str | None:
    """Best-effort map npm/pypi package to github.com/org/repo/releases.atom."""
    row = (
        supabase.table("tracked_dependencies")
        .select("github_repo")
        .eq("package_name", package_name)
        .not_.is_("github_repo", "null")
        .limit(1)
        .execute()
    )
    if row.data and row.data[0].get("github_repo"):
        repo = row.data[0]["github_repo"].strip("/")
        return f"https://github.com/{repo}/releases.atom"
    return None


async def collect_github_releases(feed: dict, *, ignore_cache: bool = False) -> tuple[list[CollectedItem], dict]:
    url = feed["url"]
    if url.startswith("pkg:"):
        package_name = url.removeprefix("pkg:")
        atom_url = _github_release_atom_url(package_name)
        if not atom_url:
            return [], {"last_polled_at": "now()", "last_status": 404}
        url = atom_url

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
    if resp.not_modified:
        poll_update["consecutive_not_modified"] = feed.get("consecutive_not_modified", 0) + 1
        return [], poll_update
    if resp.status != 200 or not resp.body:
        poll_update["consecutive_failures"] = feed.get("consecutive_failures", 0) + 1
        return [], poll_update

    parsed = feedparser.parse(resp.body)
    items: list[CollectedItem] = []
    repo_match = _GH_REPO_RE.search(url)
    package_topic = feed.get("topic") or (repo_match.group(1) if repo_match else None)
    # A stack-kind article is only matched by get_user_feed when its topic is a
    # tracked dependency, so a repo feed attached to a category has to opt into
    # 'interest' or nobody would ever see it. The pkg: rows carry no value and
    # keep the original stack behaviour.
    topic_kind = feed.get("topic_kind") or "stack"

    for entry in parsed.entries[:15]:
        link = entry.get("link") or ""
        title = (entry.get("title") or "").strip()
        if not link or not title:
            continue
        items.append(
            CollectedItem(
                title=title,
                url=link,
                snippet=clean_snippet(entry.get("summary") or ""),
                published_at=parse_datetime(entry.get("published") or entry.get("updated")),
                topic=package_topic,
                tag_id=feed.get("tag_id"),
                topic_kind=topic_kind,
                source_adapter="github",
                source_weight=float(feed.get("weight") or 1.2),
                feed_id=feed.get("id"),
                signals={"release": True},
            )
        )

    poll_update.update({"consecutive_failures": 0, "last_success_at": "now()"})
    return items, poll_update
