"""Tests for per-article YouTube resolution with strict relevance."""

from unittest.mock import patch

import pytest

from app.services import youtube as yt


def _video_item(video_id: str, title: str, description: str = "") -> dict:
    return {
        "id": {"videoId": video_id},
        "snippet": {"title": title, "description": description},
    }


@pytest.fixture(autouse=True)
def clear_cache():
    yt.clear_query_cache()
    yield
    yt.clear_query_cache()


@pytest.mark.asyncio
async def test_resolve_youtube_accepts_on_topic_first_result():
    items = [
        _video_item("good", "React 19 release notes explained", "What's new in React 19"),
        _video_item("bad", "Learn JavaScript in 2026", "Beginner tutorial"),
    ]

    with patch.object(yt, "search_youtube", return_value=items):
        url = await yt.resolve_youtube_url({
            "title": "React 19 release notes",
            "one_liner": "What's new in React 19",
            "topic": "Frontend",
        })

    assert url == "https://www.youtube.com/watch?v=good"


@pytest.mark.asyncio
async def test_resolve_youtube_rejects_off_topic_first_result():
    items = [
        _video_item("bad", "Learn JavaScript in 2026", "Beginner tutorial"),
        _video_item("good", "React 19 release notes explained", "What's new in React 19"),
    ]

    with patch.object(yt, "search_youtube", return_value=items):
        url = await yt.resolve_youtube_url({
            "title": "React 19 release notes",
            "one_liner": "What's new in React 19",
            "topic": "Frontend",
        })

    assert url == "https://www.youtube.com/watch?v=good"


@pytest.mark.asyncio
async def test_resolve_youtube_returns_none_when_no_candidate_passes():
    items = [
        _video_item("bad1", "Learn JavaScript in 2026", "Beginner tutorial"),
        _video_item("bad2", "Python basics for everyone", "Intro course"),
    ]

    with patch.object(yt, "search_youtube", return_value=items):
        url = await yt.resolve_youtube_url({
            "title": "React 19 release notes",
            "one_liner": "What's new in React 19",
            "topic": "Frontend",
        })

    assert url is None


@pytest.mark.asyncio
async def test_resolve_youtube_no_topic_fallback():
    calls: list[str] = []

    async def fake_search(query: str, max_results: int = 8) -> list[dict]:
        calls.append(query)
        return []

    with patch.object(yt, "search_youtube", side_effect=fake_search):
        url = await yt.resolve_youtube_url({
            "title": "x",
            "one_liner": "y",
            "topic": "Frontend",
        })

    assert url is None
    assert len(calls) == 1
    assert "tutorial explainer" not in calls[0]


@pytest.mark.asyncio
async def test_different_articles_same_topic_get_different_queries():
    queries: list[str] = []

    async def fake_search(query: str, max_results: int = 8) -> list[dict]:
        queries.append(query)
        if "Article A" in query:
            return [_video_item("vid_a", "Article A title deep dive", "Article A summary")]
        if "Article B" in query:
            return [_video_item("vid_b", "Article B title deep dive", "Article B summary")]
        return []

    with patch.object(yt, "search_youtube", side_effect=fake_search):
        url_a = await yt.youtube_for_article({
            "title": "Article A title",
            "one_liner": "Summary A",
            "topic": "Frontend",
        })
        url_b = await yt.youtube_for_article({
            "title": "Article B title",
            "one_liner": "Summary B",
            "topic": "Frontend",
        })

    assert url_a == "https://www.youtube.com/watch?v=vid_a"
    assert url_b == "https://www.youtube.com/watch?v=vid_b"
    assert queries[0] != queries[1]


@pytest.mark.asyncio
async def test_review_cycle_assigns_per_article_youtube():
    from app.agents import review_graph

    row_a = {
        "id": "aaa",
        "title": "Article A",
        "topic": "Frontend",
        "url": "https://example.com/a",
        "body": "Content A " * 10,
        "summary": "Summary A",
    }
    row_b = {
        "id": "bbb",
        "title": "Article B",
        "topic": "Frontend",
        "url": "https://example.com/b",
        "body": "Content B " * 10,
        "summary": "Summary B",
    }

    async def fake_resolve(article: dict) -> str | None:
        if article.get("title") == "Article A":
            return "https://www.youtube.com/watch?v=vid_a"
        if article.get("title") == "Article B":
            return "https://www.youtube.com/watch?v=vid_b"
        return None

    summary = {
        "one_liner": "ol",
        "body": "body",
        "summary": "ol",
        "source_type": "blog",
    }

    updates: list[dict] = []
    with patch.object(review_graph, "resolve_youtube_url", side_effect=fake_resolve):
        for row in [row_a, row_b]:
            merged = {**row, **summary}
            yt_url = await review_graph.resolve_youtube_url(merged)
            updates.append({"id": row["id"], "youtube_url": yt_url})

    assert updates[0]["youtube_url"] == "https://www.youtube.com/watch?v=vid_a"
    assert updates[1]["youtube_url"] == "https://www.youtube.com/watch?v=vid_b"
    assert updates[0]["youtube_url"] != updates[1]["youtube_url"]
