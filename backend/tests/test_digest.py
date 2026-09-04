import uuid
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import supabase
from app.main import app
from app.services.rate_limit import _counts

client = TestClient(app)


@pytest.fixture(scope="module")
def test_user():
    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users"
    admin_headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    email = f"digest-{uuid.uuid4().hex[:8]}@example.com"
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
        supabase.table("tracked_dependencies").delete().eq("user_id", user_id).execute()
        supabase.table("dependency_updates").delete().eq("package_name", "react").execute()
        supabase.table("dependency_updates").delete().eq("package_name", "lodash").execute()
        httpx.delete(f"{url}/{user_id}", headers=admin_headers)
    except Exception:
        pass


@pytest.fixture(scope="module", autouse=True)
def seed_react_update():
    supabase.table("dependency_updates").upsert({
        "ecosystem": "npm",
        "package_name": "react",
        "version": "19.0.0",
        "update_type": "release",
        "summary": "React 19 is out with new compiler optimizations.",
        "citations": [{"type": "blog", "url": "https://react.dev/blog", "title": "React Blog"}],
    }, on_conflict="ecosystem, package_name, version, update_type").execute()
    supabase.table("package_registry_cache").upsert({
        "ecosystem": "npm",
        "package_name": "react",
        "latest_version": "19.0.0",
    }, on_conflict="ecosystem, package_name").execute()
    yield
    supabase.table("dependency_updates").delete().eq("package_name", "react").execute()


def test_digest_shows_update_for_tracked_dep(test_user):
    _counts.pop(test_user["id"], None)
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

    response = client.get("/stack/digest", headers=headers)
    assert response.status_code == 200
    data = response.json()
    items = data["items"]
    assert len(items) >= 1
    react_item = next(i for i in items if i["package_name"] == "react")
    assert react_item["project_name"] == "demo"
    assert react_item["tracked_version"] == "18.0.0"
    assert react_item["update"] is not None
    assert react_item["update"]["version"] == "19.0.0"
    assert react_item["update"]["update_type"] == "release"


def test_digest_respects_citation_prefs(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}

    client.put("/me/citation-prefs", json={"prefs": {"blog": False}}, headers=headers)

    response = client.get("/stack/digest", headers=headers)
    assert response.status_code == 200
    data = response.json()
    react_item = next(i for i in data["items"] if i["package_name"] == "react")
    citation_types = [c["type"] for c in react_item["update"]["citations"]]
    assert "blog" not in citation_types

    client.put("/me/citation-prefs", json={"prefs": {"blog": True}}, headers=headers)


@pytest.fixture(scope="module")
def kb_digest_user():
    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users"
    admin_headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    email = f"kb-digest-{uuid.uuid4().hex[:8]}@example.com"
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
    client.put(
        "/me/interests",
        json={"tag_ids": [1]},
        headers={"Authorization": f"Bearer {access_token}"},
    )

    yield {"id": user_id, "email": email, "access_token": access_token}

    try:
        supabase.table("user_article_state").delete().eq("user_id", user_id).execute()
        supabase.table("kb_articles").delete().eq("topic", "Frontend").like("title", "KB Digest%").execute()
        supabase.table("profiles").update({"last_digest_at": None}).eq("id", user_id).execute()
        httpx.delete(f"{url}/{user_id}", headers=admin_headers)
    except Exception:
        pass


def _insert_kb_digest_article(title: str, fetched_at: str):
    return supabase.table("kb_articles").insert({
        "topic": "Frontend",
        "topic_kind": "interest",
        "tag_id": 1,
        "title": title,
        "one_liner": "Digest one liner",
        "summary": "Digest summary",
        "source_type": "blog",
        "url": f"https://example.com/digest-{uuid.uuid4().hex[:8]}",
        "fetched_at": fetched_at,
    }).execute().data[0]


@pytest.mark.asyncio
async def test_kb_digest_sends_only_new_since_last_digest(kb_digest_user):
    from datetime import datetime, timedelta, timezone
    from unittest.mock import AsyncMock, patch

    user_id = kb_digest_user["id"]
    supabase.table("profiles").update({"last_digest_at": None}).eq("id", user_id).execute()

    old_time = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    new_time = datetime.now(timezone.utc).isoformat()
    old_article = _insert_kb_digest_article("KB Digest Old", old_time)
    new_article = _insert_kb_digest_article("KB Digest New", new_time)

    supabase.table("profiles").update({"last_digest_at": old_time}).eq("id", user_id).execute()

    with (
        patch("app.services.scheduler.settings") as mock_settings,
        patch("app.services.scheduler.send_digest", new_callable=AsyncMock) as mock_email,
        patch("app.services.scheduler._get_user_email", return_value=kb_digest_user["email"]),
        patch("app.services.scheduler._collect_user_ids", return_value={user_id}),
    ):
        mock_settings.KB_FEED = True
        from app.services.scheduler import _send_digests
        await _send_digests()

    assert mock_email.call_count == 1
    items = mock_email.call_args[0][1]
    article_titles = [i["title"] for i in items if i["type"] == "article"]
    assert "KB Digest New" in article_titles
    assert "KB Digest Old" not in article_titles

    profile = supabase.table("profiles").select("last_digest_at").eq("id", user_id).single().execute()
    assert profile.data["last_digest_at"] is not None

    supabase.table("kb_articles").delete().eq("id", old_article["id"]).execute()
    supabase.table("kb_articles").delete().eq("id", new_article["id"]).execute()


@pytest.mark.asyncio
async def test_kb_digest_second_run_sends_nothing(kb_digest_user):
    from unittest.mock import AsyncMock, patch

    user_id = kb_digest_user["id"]
    now = datetime.now(timezone.utc).isoformat()
    supabase.table("profiles").update({"last_digest_at": now}).eq("id", user_id).execute()

    with (
        patch("app.services.scheduler.settings") as mock_settings,
        patch("app.services.scheduler.send_digest", new_callable=AsyncMock) as mock_email,
        patch("app.services.scheduler._get_user_email", return_value=kb_digest_user["email"]),
        patch("app.services.scheduler._collect_user_ids", return_value={user_id}),
    ):
        mock_settings.KB_FEED = True
        from app.services.scheduler import _send_digests
        await _send_digests()

    mock_email.assert_not_called()

    profile = supabase.table("profiles").select("last_digest_at").eq("id", user_id).single().execute()
    assert profile.data["last_digest_at"] is not None
    assert profile.data["last_digest_at"] >= now


@pytest.mark.asyncio
async def test_kb_digest_respects_notification_settings(kb_digest_user):
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock, patch

    user_id = kb_digest_user["id"]
    supabase.table("profiles").update({"last_digest_at": None}).eq("id", user_id).execute()
    article = _insert_kb_digest_article(
        "KB Digest Blocked",
        datetime.now(timezone.utc).isoformat(),
    )

    supabase.table("notification_settings").upsert({
        "user_id": user_id,
        "category": "discovery",
        "channel": "email",
        "enabled": False,
    }, on_conflict="user_id, category, channel").execute()

    with (
        patch("app.services.scheduler.settings") as mock_settings,
        patch("app.services.scheduler.send_digest", new_callable=AsyncMock) as mock_email,
        patch("app.services.scheduler._get_user_email", return_value=kb_digest_user["email"]),
        patch("app.services.scheduler._collect_user_ids", return_value={user_id}),
    ):
        mock_settings.KB_FEED = True
        from app.services.scheduler import _send_digests
        await _send_digests()

    mock_email.assert_not_called()

    supabase.table("notification_settings").delete().eq("user_id", user_id).execute()
    supabase.table("kb_articles").delete().eq("id", article["id"]).execute()
