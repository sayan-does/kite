import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import supabase
from app.main import app

client = TestClient(app)


@pytest.fixture(scope="module")
def users():
    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users"
    admin_headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }

    created = []
    for i in range(2):
        email = f"sched-{uuid.uuid4().hex[:8]}@example.com"
        password = uuid.uuid4().hex
        body = {"email": email, "password": password, "email_confirm": True}
        resp = httpx.post(url, headers=admin_headers, json=body)
        resp.raise_for_status()
        user_id = resp.json()["id"]

        sign_in = httpx.post(
            f"{settings.SUPABASE_URL}/auth/v1/token?grant_type=password",
            headers={"apikey": settings.SUPABASE_ANON_KEY, "Content-Type": "application/json"},
            json={"email": email, "password": password},
        )
        sign_in.raise_for_status()
        access_token = sign_in.json()["access_token"]
        client.post("/auth/callback", json={"access_token": access_token})

        created.append({"id": user_id, "access_token": access_token, "email": email})

    yield created

    for u in created:
        try:
            supabase.table("tracked_dependencies").delete().eq("user_id", u["id"]).execute()
            supabase.table("user_interests").delete().eq("user_id", u["id"]).execute()
            supabase.table("notification_settings").delete().eq("user_id", u["id"]).execute()
            httpx.delete(f"{url}/{u['id']}", headers=admin_headers)
        except Exception:
            pass


@pytest.fixture(scope="module", autouse=True)
def seed_dep_updates():
    supabase.table("dependency_updates").upsert({
        "ecosystem": "npm",
        "package_name": "react",
        "version": "19.0.0",
        "update_type": "release",
        "summary": "React 19 is out.",
        "citations": [],
    }, on_conflict="ecosystem, package_name, version, update_type").execute()
    yield
    supabase.table("dependency_updates").delete().eq("package_name", "react").execute()


@pytest.fixture(scope="module", autouse=True)
def seed_articles():
    tag_result = supabase.table("interest_tags").select("id").execute()
    if tag_result.data:
        tag_id = tag_result.data[0]["id"]
        existing = supabase.table("articles").select("id").eq("tag_id", tag_id).execute()
        if not existing.data:
            supabase.table("articles").insert({
                "tag_id": tag_id,
                "title": "Test Article",
                "summary": "Summary text",
                "citations": [],
            }).execute()


@pytest.mark.asyncio
async def test_scheduler_once_per_package_and_digest_only_with_email(users):
    user_a = users[0]
    user_b = users[1]

    headers_a = {"Authorization": f"Bearer {user_a['access_token']}"}
    headers_b = {"Authorization": f"Bearer {user_b['access_token']}"}

    # Both users track the same package
    client.post(
        "/stack",
        json={"project_name": "demo", "ecosystem": "npm", "package_name": "react", "version": "18.0.0"},
        headers=headers_a,
    )
    client.post(
        "/stack",
        json={"project_name": "demo", "ecosystem": "npm", "package_name": "react", "version": "18.0.0"},
        headers=headers_b,
    )

    # User A: email enabled (default) for dependency
    # User B: email disabled for dependency — insert directly into DB
    for row in [
        {"user_id": user_b["id"], "category": "discovery", "channel": "in_app", "enabled": True},
        {"user_id": user_b["id"], "category": "discovery", "channel": "email", "enabled": True},
        {"user_id": user_b["id"], "category": "dependency", "channel": "in_app", "enabled": True},
        {"user_id": user_b["id"], "category": "dependency", "channel": "email", "enabled": False},
    ]:
        supabase.table("notification_settings").upsert(row, on_conflict="user_id, category, channel").execute()

    with (
        patch("app.services.scheduler.settings") as mock_settings,
        patch("app.services.scheduler.run_discovery_for_tag", new_callable=AsyncMock) as mock_discovery,
        patch("app.services.scheduler.run_dependency_update", new_callable=AsyncMock) as mock_dep,
        patch("app.services.scheduler.send_digest", new_callable=AsyncMock) as mock_email,
        patch("app.services.scheduler.refresh_knowledgebase", new_callable=AsyncMock),
        patch("app.services.scheduler.cleanup_knowledgebase"),
        patch(
            "app.services.scheduler._collect_user_ids",
            return_value={user_a["id"], user_b["id"]},
        ),
        patch(
            "app.services.scheduler._get_user_email",
            side_effect=lambda uid: user_a["email"] if uid == user_a["id"] else user_b["email"],
        ),
    ):
        mock_settings.KB_FEED = False
        mock_settings.DISCOVERY_V2 = False
        from app.services.scheduler import run_daily
        await run_daily()

        # react is tracked by both users but the graph runs once per package
        react_calls = [c for c in mock_dep.call_args_list if c.args == ("npm", "react")]
        assert len(react_calls) == 1

        # Discovery should run for each distinct tag in the database
        tag_result = supabase.table("user_interests").select("tag_id").execute()
        distinct_tags = {row["tag_id"] for row in (tag_result.data or [])}
        assert mock_discovery.call_count == len(distinct_tags)

        # Only user A should get a digest (email enabled + has new items)
        assert mock_email.call_count == 1
        call_args = mock_email.call_args[0]
        assert call_args[0] == user_a["email"]
        assert len(call_args[1]) > 0


@pytest.mark.asyncio
async def test_scheduler_v2_calls_run_discovery_for_user(users):
    user_a = users[0]
    headers = {"Authorization": f"Bearer {user_a['access_token']}"}
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)

    with (
        patch("app.services.scheduler.settings") as mock_settings,
        patch("app.services.scheduler.run_discovery_for_user", new_callable=AsyncMock) as mock_v2,
        patch("app.services.scheduler.run_discovery_for_tag", new_callable=AsyncMock) as mock_v1,
        patch("app.services.scheduler.run_dependency_update", new_callable=AsyncMock),
        patch("app.services.scheduler.send_digest", new_callable=AsyncMock),
    ):
        mock_settings.DISCOVERY_V2 = True
        mock_settings.KB_FEED = False
        from app.services.scheduler import run_daily
        await run_daily()

        assert mock_v2.call_count >= 1
        mock_v1.assert_not_called()


@pytest.mark.asyncio
async def test_scheduler_v1_unchanged_when_flag_off(users):
    with (
        patch("app.services.scheduler.settings") as mock_settings,
        patch("app.services.scheduler.run_discovery_for_user", new_callable=AsyncMock) as mock_v2,
        patch("app.services.scheduler.run_discovery_for_tag", new_callable=AsyncMock) as mock_v1,
        patch("app.services.scheduler.run_dependency_update", new_callable=AsyncMock),
        patch("app.services.scheduler.send_digest", new_callable=AsyncMock),
    ):
        mock_settings.DISCOVERY_V2 = False
        mock_settings.KB_FEED = False
        from app.services.scheduler import run_daily
        await run_daily()

        tag_result = supabase.table("user_interests").select("tag_id").execute()
        distinct_tags = {row["tag_id"] for row in (tag_result.data or [])}
        assert mock_v1.call_count == len(distinct_tags)
        mock_v2.assert_not_called()


@pytest.mark.asyncio
async def test_scheduler_kb_feed_calls_refresh_and_cleanup(users):
    with (
        patch("app.services.scheduler.settings") as mock_settings,
        patch("app.services.scheduler.refresh_knowledgebase", new_callable=AsyncMock) as mock_refresh,
        patch("app.services.scheduler.run_discovery_for_user", new_callable=AsyncMock) as mock_v2,
        patch("app.services.scheduler.run_discovery_for_tag", new_callable=AsyncMock) as mock_v1,
        patch("app.services.scheduler.run_dependency_update", new_callable=AsyncMock),
        patch("app.services.scheduler.send_digest", new_callable=AsyncMock),
        patch("app.services.scheduler.cleanup_knowledgebase") as mock_cleanup,
    ):
        mock_settings.KB_FEED = True
        mock_settings.DISCOVERY_V2 = True

        from app.services.scheduler import run_daily
        await run_daily()

        mock_refresh.assert_awaited_once()
        mock_v1.assert_not_called()
        mock_v2.assert_not_called()
        mock_cleanup.assert_called_once()


@pytest.mark.asyncio
async def test_refresh_knowledgebase_calls_each_topic():
    from app.services.kb import refresh_knowledgebase

    fake_topics = [
        MagicMock(topic="Frontend", topic_kind="interest", tag_id=1),
        MagicMock(topic="react", topic_kind="stack", tag_id=None),
    ]

    with (
        patch("app.services.kb.resolve_kb_topics", return_value=fake_topics),
        patch(
            "app.agents.discovery.kb_graph.run_kb_discovery_for_topic",
            new_callable=AsyncMock,
        ) as mock_run,
    ):
        await refresh_knowledgebase()

    assert mock_run.await_count == 2
    mock_run.assert_any_await("Frontend", "interest", 1)
    mock_run.assert_any_await("react", "stack", None)


@pytest.mark.asyncio
async def test_refresh_knowledgebase_isolates_topic_failures():
    from app.services.kb import refresh_knowledgebase

    fake_topics = [
        MagicMock(topic="Good", topic_kind="interest", tag_id=1),
        MagicMock(topic="Bad", topic_kind="interest", tag_id=2),
    ]

    async def side_effect(topic, topic_kind, tag_id):
        if topic == "Bad":
            raise RuntimeError("topic failed")

    with patch(
        "app.agents.discovery.kb_graph.run_kb_discovery_for_topic",
        new_callable=AsyncMock,
        side_effect=side_effect,
    ) as mock_run:
        with patch("app.services.kb.resolve_kb_topics", return_value=fake_topics):
            await refresh_knowledgebase()

    assert mock_run.await_count == 2
