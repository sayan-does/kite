import asyncio
import uuid
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import supabase
from app.main import app

client = TestClient(app)


@pytest.fixture(scope="module")
def test_user():
    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users"
    admin_headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    email = f"feed-test-{uuid.uuid4().hex[:8]}@example.com"
    password = uuid.uuid4().hex
    body = {"email": email, "password": password, "email_confirm": True}
    resp = httpx.post(url, headers=admin_headers, json=body)
    resp.raise_for_status()
    user_id = resp.json()["id"]

    sign_in_resp = httpx.post(
        f"{settings.SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": settings.SUPABASE_ANON_KEY, "Content-Type": "application/json"},
        json={"email": email, "password": password},
    )
    sign_in_resp.raise_for_status()
    access_token = sign_in_resp.json()["access_token"]

    client.post("/auth/callback", json={"access_token": access_token})

    yield {"id": user_id, "access_token": access_token}

    try:
        # Cleanup: remove test article and user data
        supabase.table("articles").delete().eq("tag_id", 1).eq("title", "Test Article Frontend").execute()
        httpx.delete(f"{url}/{user_id}", headers=admin_headers)
    except Exception:
        pass


@pytest.fixture(scope="module", autouse=True)
def seed_article():
    supabase.table("articles").insert({
        "tag_id": 1,
        "title": "Test Article Frontend",
        "summary": "A test article about frontend",
        "body": "Full body text",
        "citations": [
            {"type": "blog", "url": "https://example.com/blog", "title": "Blog Post"},
            {"type": "youtube", "url": "https://youtube.com/watch?v=test", "title": "Video"},
        ],
        "youtube_url": "https://youtube.com/watch?v=test",
    }).execute()
    yield
    supabase.table("articles").delete().eq("tag_id", 1).eq("title", "Test Article Frontend").execute()


def test_feed_shows_article_for_followed_tag(monkeypatch, test_user):
    monkeypatch.setattr("app.routers.feed.settings.DISCOVERY_V2", False)
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", False)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)

    response = client.get("/feed", headers=headers)
    assert response.status_code == 200
    articles = response.json()["articles"]
    assert len(articles) >= 1
    titles = [a["title"] for a in articles]
    assert "Test Article Frontend" in titles


def test_feed_filters_by_tag(monkeypatch, test_user):
    monkeypatch.setattr("app.routers.feed.settings.DISCOVERY_V2", False)
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", False)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)

    response = client.get("/feed?tag=Frontend", headers=headers)
    assert response.status_code == 200
    articles = response.json()["articles"]
    assert len(articles) >= 1
    assert articles[0]["title"] == "Test Article Frontend"


def test_disabling_youtube_keeps_article_removes_youtube_citations(monkeypatch, test_user):
    monkeypatch.setattr("app.routers.feed.settings.DISCOVERY_V2", False)
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", False)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)
    client.put("/me/citation-prefs", json={"prefs": {"youtube": False}}, headers=headers)

    response = client.get("/feed", headers=headers)
    assert response.status_code == 200
    articles = response.json()["articles"]
    frontend_article = next(a for a in articles if a["title"] == "Test Article Frontend")
    citation_types = [c["type"] for c in frontend_article["citations"]]
    assert "youtube" not in citation_types
    assert "blog" in citation_types
    # Article still present
    assert frontend_article["title"] == "Test Article Frontend"

    # Reset prefs
    client.put("/me/citation-prefs", json={"prefs": {"youtube": True}}, headers=headers)


def test_pagination_returns_next_slice(monkeypatch, test_user):
    monkeypatch.setattr("app.routers.feed.settings.DISCOVERY_V2", False)
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", False)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)
    # Page 1 is the main test, page 2 should exist or have has_next false
    # Since we only have 1 article, has_next should be false
    response = client.get("/feed?page=1", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["page"] == 1
    # has_next depends on total articles, but page is always returned
    assert "has_next" in data


def test_feed_v2_returns_user_owned_cards(monkeypatch, test_user):
    monkeypatch.setattr("app.routers.feed.settings.DISCOVERY_V2", True)
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", False)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}

    supabase.table("articles").insert({
        "user_id": test_user["id"],
        "title": "V2 Card",
        "one_liner": "Short one liner",
        "summary": "Short one liner",
        "body": "Full summary body",
        "source_type": "blog",
        "source": "stack",
        "topic": "react",
        "citations": [{"type": "blog", "url": "https://example.com", "title": "Src"}],
    }).execute()

    response = client.get("/feed", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["articles"]) <= 10
    card = next((a for a in data["articles"] if a["title"] == "V2 Card"), None)
    assert card is not None
    assert card["one_liner"] == "Short one liner"
    assert card["source"] == "stack"
    assert card["topic"] == "react"

    supabase.table("articles").delete().eq("user_id", test_user["id"]).execute()


def test_feed_v2_filters_disabled_source_type(monkeypatch, test_user):
    monkeypatch.setattr("app.routers.feed.settings.DISCOVERY_V2", True)
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", False)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    client.put("/me/citation-prefs", json={"prefs": {"blog": False}}, headers=headers)

    supabase.table("articles").insert({
        "user_id": test_user["id"],
        "title": "Blog Card",
        "one_liner": "Blog one liner",
        "summary": "Blog one liner",
        "body": "Body",
        "source_type": "blog",
        "source": "interest",
        "topic": "Frontend",
        "citations": [{"type": "blog", "url": "https://example.com", "title": "Src"}],
    }).execute()

    response = client.get("/feed", headers=headers)
    card = next((a for a in response.json()["articles"] if a["title"] == "Blog Card"), None)
    assert card is not None
    assert card["source_type"] is None
    assert card["citations"] == []

    supabase.table("articles").delete().eq("user_id", test_user["id"]).execute()
    client.put("/me/citation-prefs", json={"prefs": {"blog": True}}, headers=headers)


def _insert_kb_article(**kwargs):
    defaults = {
        "topic": "Frontend",
        "topic_kind": "interest",
        "tag_id": 1,
        "title": "KB Article",
        "one_liner": "KB one liner",
        "summary": "KB summary",
        "body": "KB body",
        "source_type": "blog",
        "citations": [{"type": "blog", "url": "https://example.com", "title": "Src"}],
        "url": f"https://example.com/kb-{uuid.uuid4().hex[:8]}",
        # get_user_feed ranks by score and pages at 20, so a default-score row
        # falls off page one as soon as the live pipeline has collected enough
        # for the topic. Outranking it keeps these assertions deterministic.
        "score": 9999,
    }
    defaults.update(kwargs)
    result = supabase.table("kb_articles").insert(defaults).execute()
    return result.data[0]


@pytest.fixture
def kb_article_ids():
    """Track inserted KB rows and delete only those IDs on teardown (never wipe the table)."""
    ids: list[str] = []
    yield ids
    for article_id in ids:
        supabase.table("user_article_state").delete().eq("kb_article_id", article_id).execute()
        supabase.table("kb_articles").delete().eq("id", article_id).execute()


def test_kb_feed_returns_matching_articles(monkeypatch, test_user, kb_article_ids):
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", True)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)

    article = _insert_kb_article(title="KB Feed Match")
    kb_article_ids.append(article["id"])

    response = client.get("/feed", headers=headers)
    assert response.status_code == 200
    data = response.json()
    titles = [a["title"] for a in data["articles"]]
    assert "KB Feed Match" in titles
    card = next(a for a in data["articles"] if a["title"] == "KB Feed Match")
    assert card["one_liner"] == "KB one liner"
    assert card["source"] == "interest"
    assert card["topic"] == "Frontend"
    assert "fetched_at" in card
    assert card["is_research"] is False

    supabase.table("kb_articles").delete().eq("id", article["id"]).execute()


def test_kb_feed_exposes_is_research(monkeypatch, test_user, kb_article_ids):
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", True)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)

    article = _insert_kb_article(
        title="KB Research Card",
        topic="AI/ML",
        is_research=True,
        citations=[
            {"type": "blog", "url": "https://huggingface.co/blog/x", "title": "Post"},
            {"type": "blog", "url": "https://arxiv.org/abs/1", "title": "Paper"},
        ],
        url=f"https://huggingface.co/blog/x-{uuid.uuid4().hex[:8]}",
    )
    kb_article_ids.append(article["id"])

    response = client.get("/feed", headers=headers)
    assert response.status_code == 200
    card = next(
        (a for a in response.json()["articles"] if a["title"] == "KB Research Card"),
        None,
    )
    assert card is not None
    assert card["is_research"] is True
    assert isinstance(card["is_research"], bool)


def test_kb_feed_excludes_dismissed(monkeypatch, test_user, kb_article_ids):
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", True)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)

    article = _insert_kb_article(title="KB Dismissed")
    kb_article_ids.append(article["id"])
    supabase.table("user_article_state").insert({
        "user_id": test_user["id"],
        "kb_article_id": article["id"],
        "dismissed": True,
    }).execute()

    response = client.get("/feed", headers=headers)
    titles = [a["title"] for a in response.json()["articles"]]
    assert "KB Dismissed" not in titles

    supabase.table("kb_articles").delete().eq("id", article["id"]).execute()


def test_kb_feed_pagination_has_next(monkeypatch, test_user, kb_article_ids):
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", True)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)

    created = []
    for i in range(21):
        article = _insert_kb_article(
            title=f"KB Page {i}",
            url=f"https://example.com/kb-page-{uuid.uuid4().hex}",
        )
        created.append(article["id"])
        kb_article_ids.append(article["id"])

    response = client.get("/feed?page=1", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["page"] == 1
    assert len(data["articles"]) == 20
    assert data["has_next"] is True

    page2 = client.get("/feed?page=2", headers=headers)
    assert page2.status_code == 200
    assert len(page2.json()["articles"]) >= 1

    for article_id in created:
        supabase.table("kb_articles").delete().eq("id", article_id).execute()


def test_kb_feed_filters_by_topic_at_database(monkeypatch, test_user, kb_article_ids):
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", True)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    client.put("/me/interests", json={"tag_ids": [1, 3]}, headers=headers)

    frontend_article = _insert_kb_article(
        title="Topic Filter Frontend",
        topic="Frontend",
        tag_id=1,
        url=f"https://example.com/topic-fe-{uuid.uuid4().hex[:8]}",
    )
    aiml_article = _insert_kb_article(
        title="Topic Filter AIML",
        topic="AI/ML",
        tag_id=3,
        url=f"https://example.com/topic-ai-{uuid.uuid4().hex[:8]}",
    )
    kb_article_ids.extend([frontend_article["id"], aiml_article["id"]])

    response = client.get("/feed?tag=Frontend", headers=headers)
    assert response.status_code == 200
    titles = [a["title"] for a in response.json()["articles"]]
    assert "Topic Filter Frontend" in titles
    assert "Topic Filter AIML" not in titles
    for article in response.json()["articles"]:
        assert article["topic"] == "Frontend"


def test_kb_feed_topic_pagination(monkeypatch, test_user, kb_article_ids):
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", True)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)

    created = []
    for i in range(21):
        article = _insert_kb_article(
            title=f"Frontend Only {i}",
            topic="Frontend",
            tag_id=1,
            url=f"https://example.com/fe-only-{uuid.uuid4().hex}",
        )
        created.append(article["id"])
        kb_article_ids.append(article["id"])

    # High-score AI/ML rows should not consume Frontend page budget.
    for i in range(5):
        other = _insert_kb_article(
            title=f"AI/ML High Score {i}",
            topic="AI/ML",
            tag_id=3,
            score=9999,
            url=f"https://example.com/ai-high-{uuid.uuid4().hex}",
        )
        kb_article_ids.append(other["id"])

    response = client.get("/feed?tag=Frontend&page=1", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["articles"]) == 20
    assert data["has_next"] is True
    assert all(a["topic"] == "Frontend" for a in data["articles"])

    page2 = client.get("/feed?tag=Frontend&page=2", headers=headers)
    assert page2.status_code == 200
    assert len(page2.json()["articles"]) >= 1
    assert all(a["topic"] == "Frontend" for a in page2.json()["articles"])

    for article_id in created:
        supabase.table("kb_articles").delete().eq("id", article_id).execute()


def test_kb_feed_filters_disabled_source_type(monkeypatch, test_user, kb_article_ids):
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", True)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)
    client.put("/me/citation-prefs", json={"prefs": {"blog": False}}, headers=headers)

    article = _insert_kb_article(title="KB Blog Card")
    kb_article_ids.append(article["id"])

    response = client.get("/feed", headers=headers)
    card = next((a for a in response.json()["articles"] if a["title"] == "KB Blog Card"), None)
    assert card is not None
    assert card["source_type"] is None
    assert card["citations"] == []

    supabase.table("kb_articles").delete().eq("id", article["id"]).execute()
    client.put("/me/citation-prefs", json={"prefs": {"blog": True}}, headers=headers)


def test_kb_feed_list_view_omits_body(monkeypatch, test_user, kb_article_ids):
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", True)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)

    article = _insert_kb_article(title="KB List View", body="Full body should be hidden")
    kb_article_ids.append(article["id"])

    list_resp = client.get("/feed?view=list", headers=headers)
    assert list_resp.status_code == 200
    card = next(a for a in list_resp.json()["articles"] if a["title"] == "KB List View")
    assert "body" not in card

    detail_resp = client.get("/feed?view=detail", headers=headers)
    assert detail_resp.status_code == 200
    detail_card = next(a for a in detail_resp.json()["articles"] if a["title"] == "KB List View")
    assert detail_card.get("body") == "Full body should be hidden"

    supabase.table("kb_articles").delete().eq("id", article["id"]).execute()


def test_kb_feed_article_detail_returns_body(monkeypatch, test_user, kb_article_ids):
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", True)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)

    article = _insert_kb_article(
        title="KB Detail Article",
        body="This is the articulated full summary for the reader.",
        tier="reviewed",
    )
    kb_article_ids.append(article["id"])

    resp = client.get(f"/feed/articles/{article['id']}", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["article"]["body"] == "This is the articulated full summary for the reader."
    assert data["generating"] is False


def test_kb_feed_article_detail_enriches_raw(monkeypatch, test_user, kb_article_ids):
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", True)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)

    article = _insert_kb_article(
        title="KB Raw Detail",
        body="Short",
        tier="raw",
    )
    kb_article_ids.append(article["id"])

    summary = {
        "one_liner": "Polished one liner",
        "body": "A much longer articulated summary that explains the story in depth.",
        "summary": "Polished one liner",
        "source_type": "blog",
    }

    with patch("app.routers.feed.summarize_article", return_value=summary):
        resp = client.get(f"/feed/articles/{article['id']}", headers=headers)

    assert resp.status_code == 200
    data = resp.json()
    assert "articulated summary" in data["article"]["body"]
    assert data["article"]["tier"] == "reviewed"
    assert data["generating"] is False


def test_kb_feed_hides_youtube_url_when_disabled(monkeypatch, test_user, kb_article_ids):
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", True)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)
    client.put("/me/citation-prefs", json={"prefs": {"youtube": False}}, headers=headers)

    article = _insert_kb_article(
        title="KB YouTube Hidden",
        youtube_url="https://www.youtube.com/watch?v=abc123",
    )
    kb_article_ids.append(article["id"])

    response = client.get("/feed", headers=headers)
    card = next(a for a in response.json()["articles"] if a["title"] == "KB YouTube Hidden")
    assert card.get("youtube_url") is None

    client.put("/me/citation-prefs", json={"prefs": {"youtube": True}}, headers=headers)


def test_feed_prefetch_returns_all_interest_tags(monkeypatch, test_user, kb_article_ids):
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", True)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    client.put("/me/interests", json={"tag_ids": [1, 3]}, headers=headers)

    # Score high enough to outrank whatever the live pipeline has collected,
    # so the __all__ page assertions test prefetch and not ranking.
    fe_article = _insert_kb_article(
        title="Prefetch Frontend",
        topic="Frontend",
        tag_id=1,
        score=9999,
        url=f"https://example.com/prefetch-fe-{uuid.uuid4().hex[:8]}",
    )
    ai_article = _insert_kb_article(
        title="Prefetch AIML",
        topic="AI/ML",
        tag_id=3,
        score=9999,
        url=f"https://example.com/prefetch-ai-{uuid.uuid4().hex[:8]}",
    )
    kb_article_ids.extend([fe_article["id"], ai_article["id"]])

    response = client.get("/feed/prefetch?view=list", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "fetched_at" in data
    feeds = data["feeds"]
    assert "__all__" in feeds
    assert "Frontend" in feeds
    assert "AI/ML" in feeds

    all_titles = [a["title"] for a in feeds["__all__"]["articles"]]
    assert "Prefetch Frontend" in all_titles
    assert "Prefetch AIML" in all_titles

    fe_titles = [a["title"] for a in feeds["Frontend"]["articles"]]
    assert "Prefetch Frontend" in fe_titles
    assert "Prefetch AIML" not in fe_titles

    for feed in feeds.values():
        for article in feed["articles"]:
            assert "body" not in article

    supabase.table("kb_articles").delete().eq("id", fe_article["id"]).execute()
    supabase.table("kb_articles").delete().eq("id", ai_article["id"]).execute()


def test_feed_refresh_requires_auth():
    response = client.post("/feed/refresh?tag=Frontend")
    assert response.status_code in (401, 403)


def test_feed_refresh_unknown_tag_returns_404(monkeypatch, test_user):
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", True)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}

    response = client.post("/feed/refresh?tag=NotARealCategory", headers=headers)
    assert response.status_code == 404


def test_feed_refresh_forces_collect_and_returns_page(monkeypatch, test_user, kb_article_ids):
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", True)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)

    article = _insert_kb_article(
        title="Refresh Frontend Card",
        url=f"https://example.com/refresh-fe-{uuid.uuid4().hex[:8]}",
    )
    kb_article_ids.append(article["id"])

    called: dict = {}

    async def fake_fast_cycle(*, topics=None, force=False, allow_search_backfill=False):
        called.update(
            {"topics": topics, "force": force, "allow_search_backfill": allow_search_backfill}
        )
        return {"mode": "fast", "inserted": 1}

    monkeypatch.setattr("app.routers.feed.run_fast_cycle", fake_fast_cycle)

    response = client.post("/feed/refresh?tag=Frontend", headers=headers)
    assert response.status_code == 200
    data = response.json()

    assert called == {
        "topics": ["Frontend"],
        "force": True,
        "allow_search_backfill": True,
    }
    assert data["timed_out"] is False
    assert data["inserted"] == 1
    assert "Refresh Frontend Card" in [a["title"] for a in data["articles"]]
    for card in data["articles"]:
        assert "body" not in card


def test_feed_refresh_hands_off_slow_collect(monkeypatch, test_user):
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", True)
    monkeypatch.setattr("app.routers.feed.REFRESH_WAIT_SECONDS", 0.05)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}

    async def slow_cycle(*, topics=None, force=False, allow_search_backfill=False):
        await asyncio.sleep(5)
        return {"inserted": 3}

    monkeypatch.setattr("app.routers.feed.run_fast_cycle", slow_cycle)

    response = client.post("/feed/refresh?tag=Frontend", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["timed_out"] is True
    assert data["inserted"] == 0
    assert "articles" in data


def test_kb_feed_includes_stack_topic(monkeypatch, test_user, kb_article_ids):
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", True)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}

    client.post(
        "/stack",
        json={
            "project_name": "demo",
            "ecosystem": "npm",
            "package_name": "react",
            "version": "18.0.0",
        },
        headers=headers,
    )

    article = _insert_kb_article(
        title="KB Stack Article",
        topic="react",
        topic_kind="stack",
        tag_id=None,
    )
    kb_article_ids.append(article["id"])

    response = client.get("/feed", headers=headers)
    titles = [a["title"] for a in response.json()["articles"]]
    assert "KB Stack Article" in titles

    supabase.table("kb_articles").delete().eq("id", article["id"]).execute()
    supabase.table("tracked_dependencies").delete().eq("user_id", test_user["id"]).execute()
