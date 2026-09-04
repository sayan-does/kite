"""YouTube search helpers — per-article matching with strict relevance."""

from __future__ import annotations

import logging
import re

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_query_cache: dict[str, str | None] = {}
_MAX_QUERY_LEN = 100
_MAX_CANDIDATES = 8
_MIN_TITLE_OVERLAP = 0.35
_MIN_TOPIC_OVERLAP = 0.25
_MIN_SHARED_TITLE_TOKENS = 2


def _normalize_query(text: str) -> str:
    return " ".join(text.split())[:_MAX_QUERY_LEN]


def _significant_tokens(text: str) -> set[str]:
    stop = {"the", "and", "for", "with", "from", "this", "that", "your", "what", "how", "new"}
    return {
        w.lower()
        for w in re.split(r"\W+", text)
        if len(w) > 2 and w.lower() not in stop
    }


def _keyword_overlap(text: str, topic: str) -> float:
    topic_words = _significant_tokens(topic)
    if not topic_words:
        return 0.0
    text_words = _significant_tokens(text)
    return len(topic_words & text_words) / len(topic_words)


def _title_overlap(article_title: str, video_text: str) -> float:
    title_tokens = _significant_tokens(article_title)
    if not title_tokens:
        return 0.0
    video_tokens = _significant_tokens(video_text)
    return len(title_tokens & video_tokens) / len(title_tokens)


def _video_relevance(article: dict, video_title: str, video_description: str) -> float:
    article_title = (article.get("title") or "").strip()
    one_liner = (article.get("one_liner") or article.get("summary") or "").strip()
    topic = (article.get("topic") or "").strip()
    context = f"{article_title} {one_liner} {topic}"
    video_text = f"{video_title} {video_description}"

    title_overlap = _title_overlap(article_title, video_text)
    topic_overlap = _keyword_overlap(video_text, topic) if topic else 0.0
    context_overlap = _keyword_overlap(video_text, context)

    shared_title_tokens = len(_significant_tokens(article_title) & _significant_tokens(video_text))

    if title_overlap >= _MIN_TITLE_OVERLAP:
        return max(title_overlap, context_overlap)
    if topic_overlap >= _MIN_TOPIC_OVERLAP and shared_title_tokens >= _MIN_SHARED_TITLE_TOKENS:
        return max(topic_overlap, context_overlap)
    return max(title_overlap, topic_overlap, context_overlap * 0.8)


def _pick_best_video(article: dict, items: list[dict]) -> str | None:
    best_score = 0.0
    best_url: str | None = None
    article_title = (article.get("title") or "").strip()

    for item in items:
        snippet = item.get("snippet") or {}
        video_title = snippet.get("title") or ""
        video_description = snippet.get("description") or ""
        score = _video_relevance(article, video_title, video_description)

        title_overlap = _title_overlap(article_title, f"{video_title} {video_description}")
        topic = (article.get("topic") or "").strip()
        topic_overlap = _keyword_overlap(f"{video_title} {video_description}", topic) if topic else 0.0
        shared_title_tokens = len(
            _significant_tokens(article_title) & _significant_tokens(f"{video_title} {video_description}")
        )

        passes = (
            title_overlap >= _MIN_TITLE_OVERLAP
            or (topic_overlap >= _MIN_TOPIC_OVERLAP and shared_title_tokens >= _MIN_SHARED_TITLE_TOKENS)
        )
        if not passes:
            continue
        if score > best_score:
            vid = item.get("id", {}).get("videoId")
            if vid:
                best_score = score
                best_url = f"https://www.youtube.com/watch?v={vid}"

    return best_url


async def search_youtube(query: str, max_results: int = _MAX_CANDIDATES) -> list[dict]:
    """Search YouTube Data API and return raw item dicts."""
    api_key = settings.YOUTUBE_API_KEY
    if not api_key or api_key in ("placeholder", ""):
        return []

    normalized = _normalize_query(query)
    if not normalized:
        return []

    params = {
        "part": "snippet",
        "q": normalized,
        "maxResults": max_results,
        "type": "video",
        "key": api_key,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get("https://www.googleapis.com/youtube/v3/search", params=params)
            if resp.status_code == 200:
                return resp.json().get("items", [])
    except Exception as exc:
        logger.warning("YouTube search failed for %r: %s", normalized, exc)

    return []


async def youtube_for_article(article: dict) -> str | None:
    """Find a strictly on-topic video for this article."""
    title = (article.get("title") or "").strip()
    one_liner = (article.get("one_liner") or article.get("summary") or "").strip()
    topic = (article.get("topic") or "").strip()
    parts = [p for p in (title, one_liner, topic) if p]
    if not parts:
        return None

    query = _normalize_query(" ".join(parts))
    cache_key = query
    if cache_key in _query_cache:
        cached = _query_cache[cache_key]
        return cached or None

    items = await search_youtube(query)
    url = _pick_best_video(article, items)
    _query_cache[cache_key] = url or ""
    return url


async def resolve_youtube_url(article: dict) -> str | None:
    """Article-specific search only — no generic topic fallback."""
    return await youtube_for_article(article)


def clear_query_cache() -> None:
    """Test helper."""
    _query_cache.clear()
