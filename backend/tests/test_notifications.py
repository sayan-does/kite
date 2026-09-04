import uuid
from unittest.mock import AsyncMock, patch

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
    email = f"notif-{uuid.uuid4().hex[:8]}@example.com"
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

    yield {"id": user_id, "access_token": access_token, "email": email}

    try:
        supabase.table("notification_settings").delete().eq("user_id", user_id).execute()
        supabase.table("tracked_dependencies").delete().eq("user_id", user_id).execute()
        httpx.delete(f"{url}/{user_id}", headers=admin_headers)
    except Exception:
        pass


def test_get_defaults_returns_all_enabled(test_user):
    _counts.pop(test_user["id"], None)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    response = client.get("/me/notification-settings", headers=headers)
    assert response.status_code == 200
    data = response.json()
    s = data["settings"]
    assert s["discovery"]["in_app"] is True
    assert s["discovery"]["email"] is True
    assert s["dependency"]["in_app"] is True
    assert s["dependency"]["email"] is True


def test_disable_dependency_email_persists(test_user):
    _counts.pop(test_user["id"], None)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    response = client.put(
        "/me/notification-settings",
        json={
            "discovery": {"in_app": True, "email": True},
            "dependency": {"in_app": True, "email": False},
        },
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["settings"]["dependency"]["email"] is False
    assert data["settings"]["dependency"]["in_app"] is True
    assert data["settings"]["discovery"]["email"] is True

    get_resp = client.get("/me/notification-settings", headers=headers)
    assert get_resp.json()["settings"]["dependency"]["email"] is False


def test_disabling_dependency_email_excludes_from_digest(test_user):
    _counts.pop(test_user["id"], None)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}

    # Disable dependency/email
    client.put(
        "/me/notification-settings",
        json={
            "discovery": {"in_app": True, "email": True},
            "dependency": {"in_app": True, "email": False},
        },
        headers=headers,
    )

    # Seed a dependency update
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
    supabase.table("dependency_updates").upsert({
        "ecosystem": "npm",
        "package_name": "react",
        "version": "19.0.0",
        "update_type": "release",
        "summary": "React 19 is out.",
        "citations": [],
    }, on_conflict="ecosystem, package_name, version, update_type").execute()

    with (
        patch("app.services.scheduler.send_digest", new_callable=AsyncMock) as mock_email,
        patch("app.services.scheduler.run_discovery_for_tag", new_callable=AsyncMock),
        patch("app.services.scheduler.run_discovery_for_user", new_callable=AsyncMock),
        patch("app.services.scheduler.run_dependency_update", new_callable=AsyncMock),
        patch("app.services.scheduler.refresh_knowledgebase", new_callable=AsyncMock),
        patch("app.services.scheduler.cleanup_knowledgebase"),
        patch("app.services.scheduler._collect_user_ids", return_value={test_user["id"]}),
        patch("app.services.scheduler.settings") as mock_settings,
    ):
        mock_settings.KB_FEED = False
        mock_settings.DISCOVERY_V2 = False
        from app.services.scheduler import run_daily
        import asyncio
        asyncio.run(run_daily())

        # send_digest should NOT be called because dependency/email is disabled
        assert mock_email.call_count == 0

    supabase.table("tracked_dependencies").delete().eq("user_id", test_user["id"]).execute()
    supabase.table("dependency_updates").delete().eq("package_name", "react").execute()
