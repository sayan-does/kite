"""Dedup, topic filtering, and importance scoring for collected items."""

from __future__ import annotations

import math
import re
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher

from app.collectors.base import CollectedItem
from app.config import settings

_VERSION_RE = re.compile(r"\b(\d+(?:\.\d+)+)\b")
_TOPIC_ALIASES: dict[str, set[str]] = {
    "frontend": {"react", "vue", "angular", "css", "html", "javascript", "typescript", "vite", "webpack"},
    "backend": {"api", "server", "node", "python", "fastapi", "django", "express", "graphql"},
    "ai/ml": {"ai", "ml", "llm", "machine", "learning", "model", "gpt", "neural", "deepmind", "huggingface"},
    "devops": {"kubernetes", "docker", "ci", "cd", "terraform", "helm", "devops", "deploy"},
    "security": {"security", "cve", "vulnerability", "encryption", "auth", "oauth"},
    # topic_relevance divides hits by 0.35 * token count, so an oversized alias
    # set makes a single hit score lower than it does for other categories.
    # Kept to ten so one match clears MIN_RELEVANCE, as it does elsewhere.
    "automation": {
        "automation", "automate", "workflow", "n8n", "playwright",
        "selenium", "scraping", "orchestration", "webhook", "rpa",
    },
    "programming languages": {"rust", "go", "python", "java", "typescript", "javascript", "c++", "ruby"},
}


def _normalize_title(title: str) -> str:
    t = re.sub(r"[^\w\s]", " ", title.lower())
    return re.sub(r"\s+", " ", t).strip()


def _extract_versions(text: str) -> set[str]:
    return set(_VERSION_RE.findall(text))


def _version_conflict(a: str, b: str) -> bool:
    va, vb = _extract_versions(a), _extract_versions(b)
    if not va or not vb:
        return False
    return va.isdisjoint(vb) is False and va != vb


def title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize_title(a), _normalize_title(b)).ratio()


def topic_relevance(item: CollectedItem) -> float:
    """Score 0-1 how well item matches its assigned topic."""
    topic = (item.topic or "").strip()
    if not topic:
        return 0.5
    text = f"{item.title} {item.snippet}".lower()
    topic_lower = topic.lower()
    aliases = _TOPIC_ALIASES.get(topic_lower, set())
    topic_tokens = {w for w in re.split(r"\W+", topic_lower) if len(w) > 2} | aliases
    if not topic_tokens:
        return 0.5
    hits = sum(1 for t in topic_tokens if t in text)
    return min(1.0, hits / max(1, len(topic_tokens) * 0.35))


def recency_decay(published_at: datetime | None, *, half_life_hours: float | None = None) -> float:
    half_life = half_life_hours or settings.FEED_HALF_LIFE_HOURS
    if not published_at:
        return 0.75
    now = datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now - published_at).total_seconds() / 3600)
    return math.pow(0.5, age_hours / half_life)


def community_signal(signals: dict) -> float:
    points = float(signals.get("hn_points") or 0)
    comments = float(signals.get("hn_comments") or 0)
    if points <= 0 and comments <= 0:
        return 1.0
    return 1.0 + min(2.0, math.log1p(points) / 5 + math.log1p(comments) / 8)


def compute_score(item: CollectedItem, *, substance: float = 1.0) -> float:
    rel = topic_relevance(item)
    if rel < 0.2:
        return 0.0
    half_life = settings.FEED_STACK_HALF_LIFE_HOURS if item.topic_kind == "stack" else settings.FEED_HALF_LIFE_HOURS
    return round(
        item.source_weight
        * recency_decay(item.published_at, half_life_hours=half_life)
        * community_signal(item.signals)
        * substance
        * rel,
        4,
    )


def dedup_items(items: list[CollectedItem]) -> list[CollectedItem]:
    """Exact URL canonical match, then title similarity with version guard."""
    by_canonical: dict[str, CollectedItem] = {}
    ordered: list[CollectedItem] = []

    for item in sorted(items, key=lambda i: compute_score(i), reverse=True):
        canon = item.url_canonical
        if canon and canon in by_canonical:
            continue

        merged = False
        for existing in ordered:
            if _version_conflict(item.title, existing.title):
                continue
            if title_similarity(item.title, existing.title) >= 0.88:
                merged = True
                break
        if merged:
            continue

        if canon:
            by_canonical[canon] = item
        ordered.append(item)

    return ordered


def assign_cluster_ids(items: list[CollectedItem]) -> dict[str, uuid.UUID]:
    """Map url_canonical to cluster_id for near-duplicate titles."""
    clusters: dict[str, uuid.UUID] = {}
    representatives: list[tuple[str, uuid.UUID]] = []

    for item in items:
        canon = item.url_canonical or item.url
        cluster_id = uuid.uuid4()
        for rep_title, rep_id in representatives:
            if _version_conflict(item.title, rep_title):
                continue
            if title_similarity(item.title, rep_title) >= 0.88:
                cluster_id = rep_id
                break
        else:
            representatives.append((item.title, cluster_id))
        clusters[canon] = cluster_id

    return clusters
