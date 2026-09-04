import uuid

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
    email = f"feed-state-{uuid.uuid4().hex[:8]}@example.com"
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
        supabase.table("user_article_state").delete().eq("user_id", user_id).execute()
        httpx.delete(f"{url}/{user_id}", headers=admin_headers)
    except Exception:
        pass


@pytest.fixture
def kb_article():
    result = supabase.table("kb_articles").insert({
        "topic": "Frontend",
        "topic_kind": "interest",
        "tag_id": 1,
        "title": "State Test Article",
        "summary": "Summary",
        "source_type": "blog",
        "url": f"https://example.com/state-{uuid.uuid4().hex[:8]}",
        # Outrank the live pipeline's Frontend rows so this article is on the
        # first page of get_user_feed, which is what the assertions read.
        "score": 9999,
    }).execute()
    article = result.data[0]
    yield article
    supabase.table("user_article_state").delete().eq("kb_article_id", article["id"]).execute()
    supabase.table("kb_articles").delete().eq("id", article["id"]).execute()


def test_feed_state_upsert_seen_read_dismissed(monkeypatch, test_user, kb_article):
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", True)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    article_id = kb_article["id"]

    response = client.post(
        f"/feed/{article_id}/state",
        json={"seen": True, "read": True},
        headers=headers,
    )
    assert response.status_code == 200

    row = (
        supabase.table("user_article_state")
        .select("seen, read, dismissed")
        .eq("user_id", test_user["id"])
        .eq("kb_article_id", article_id)
        .single()
        .execute()
        .data
    )
    assert row["seen"] is True
    assert row["read"] is True
    assert row["dismissed"] is False


def test_dismissed_removes_from_kb_feed(monkeypatch, test_user, kb_article):
    monkeypatch.setattr("app.routers.feed.settings.KB_FEED", True)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    article_id = kb_article["id"]

    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)

    before = client.get("/feed", headers=headers)
    assert any(a["id"] == article_id for a in before.json()["articles"])

    client.post(f"/feed/{article_id}/state", json={"dismissed": True}, headers=headers)

    after = client.get("/feed", headers=headers)
    assert all(a["id"] != article_id for a in after.json()["articles"])


def test_feed_state_404_on_unknown_article(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    fake_id = "00000000-0000-0000-0000-000000000099"
    response = client.post(
        f"/feed/{fake_id}/state",
        json={"seen": True},
        headers=headers,
    )
    assert response.status_code == 404
