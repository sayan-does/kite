"""Tests for Saved / read-later (feature 4). Live Supabase."""

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
    h = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    email = f"saved-{uuid.uuid4().hex[:8]}@example.com"
    pw = uuid.uuid4().hex
    r = httpx.post(url, headers=h, json={"email": email, "password": pw, "email_confirm": True})
    r.raise_for_status()
    uid = r.json()["id"]
    s = httpx.post(
        f"{settings.SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": settings.SUPABASE_ANON_KEY, "Content-Type": "application/json"},
        json={"email": email, "password": pw},
    )
    s.raise_for_status()
    # A user who can reach the feed has onboarded, so a profiles row exists
    # (user_article_state FKs to profiles). Mirror that here.
    supabase.table("profiles").upsert({"id": uid}, on_conflict="id").execute()
    yield {"id": uid, "access_token": s.json()["access_token"]}
    try:
        httpx.delete(f"{url}/{uid}", headers=h)
    except Exception:
        pass


@pytest.fixture
def kb_article():
    row = supabase.table("kb_articles").insert({
        "topic": "Frontend",
        "topic_kind": "interest",
        "tag_id": 1,
        "title": "Saved Test Article",
        "one_liner": "one liner",
        "summary": "summary",
        "body": "body",
        "source_type": "blog",
        "citations": [{"type": "blog", "url": "https://example.com", "title": "Src"}],
        "url": f"https://example.com/saved-{uuid.uuid4().hex[:8]}",
        "score": 123,
    }).execute().data[0]
    yield row
    supabase.table("user_article_state").delete().eq("kb_article_id", row["id"]).execute()
    supabase.table("kb_articles").delete().eq("id", row["id"]).execute()


def test_save_then_appears_in_saved_then_unsave(test_user, kb_article):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    aid = kb_article["id"]

    # Initially not saved.
    resp = client.get("/feed/saved", headers=headers)
    assert resp.status_code == 200
    assert aid not in [a["id"] for a in resp.json()["articles"]]

    # Save it.
    r = client.post(f"/feed/{aid}/state", json={"saved": True}, headers=headers)
    assert r.status_code == 200
    saved = client.get("/feed/saved", headers=headers).json()["articles"]
    assert aid in [a["id"] for a in saved]

    # Un-save it.
    client.post(f"/feed/{aid}/state", json={"saved": False}, headers=headers)
    after = client.get("/feed/saved", headers=headers).json()["articles"]
    assert aid not in [a["id"] for a in after]


def test_state_requires_a_field(test_user, kb_article):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    r = client.post(f"/feed/{kb_article['id']}/state", json={}, headers=headers)
    assert r.status_code == 400


def test_saving_preserves_other_state(test_user, kb_article):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    aid = kb_article["id"]
    client.post(f"/feed/{aid}/state", json={"read": True}, headers=headers)
    client.post(f"/feed/{aid}/state", json={"saved": True}, headers=headers)
    row = (
        supabase.table("user_article_state")
        .select("read, saved")
        .eq("user_id", test_user["id"])
        .eq("kb_article_id", aid)
        .execute()
        .data[0]
    )
    assert row["read"] is True and row["saved"] is True
