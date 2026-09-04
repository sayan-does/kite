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
    email = f"del-test-{uuid.uuid4().hex[:8]}@example.com"
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
        for tbl in ["tracked_dependencies", "user_interests", "notification_settings", "citation_prefs"]:
            supabase.table(tbl).delete().eq("user_id", user_id).execute()
        supabase.table("profiles").delete().eq("id", user_id).execute()
        httpx.delete(f"{url}/{user_id}", headers=admin_headers)
    except Exception:
        pass


@pytest.fixture(scope="module")
def second_user():
    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users"
    admin_headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    email = f"del-other-{uuid.uuid4().hex[:8]}@example.com"
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
        for tbl in ["tracked_dependencies", "user_interests", "notification_settings", "citation_prefs"]:
            supabase.table(tbl).delete().eq("user_id", user_id).execute()
        supabase.table("profiles").delete().eq("id", user_id).execute()
        httpx.delete(f"{url}/{user_id}", headers=admin_headers)
    except Exception:
        pass


def _seed_user_data(user_id: str):
    supabase.table("user_interests").insert([
        {"user_id": user_id, "tag_id": 1},
        {"user_id": user_id, "tag_id": 2},
    ]).execute()

    supabase.table("notification_settings").insert([
        {"user_id": user_id, "category": "discovery", "channel": "in_app", "enabled": True},
        {"user_id": user_id, "category": "discovery", "channel": "email", "enabled": True},
        {"user_id": user_id, "category": "dependency", "channel": "in_app", "enabled": True},
        {"user_id": user_id, "category": "dependency", "channel": "email", "enabled": True},
    ]).execute()

    supabase.table("citation_prefs").insert([
        {"user_id": user_id, "source_type": "official_docs", "enabled": True},
        {"user_id": user_id, "source_type": "github", "enabled": True},
        {"user_id": user_id, "source_type": "blog", "enabled": False},
        {"user_id": user_id, "source_type": "youtube", "enabled": True},
    ]).execute()

    supabase.table("tracked_dependencies").insert([
        {
            "user_id": user_id,
            "project_name": "demo",
            "ecosystem": "npm",
            "package_name": "react",
            "version": "18.0.0",
            "source": "manual",
        },
    ]).execute()


def test_delete_me_removes_all_user_data(test_user, second_user):
    _seed_user_data(test_user["id"])

    supabase.table("tracked_dependencies").insert([
        {
            "user_id": second_user["id"],
            "project_name": "demo",
            "ecosystem": "npm",
            "package_name": "react",
            "version": "18.0.0",
            "source": "manual",
        },
    ]).execute()

    supabase.table("dependency_updates").upsert({
        "ecosystem": "npm",
        "package_name": "react",
        "version": "19.0.0",
        "update_type": "release",
        "summary": "React 19 is out.",
        "citations": [],
    }, on_conflict="ecosystem, package_name, version, update_type").execute()

    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    response = client.delete("/me", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"status": "deleted"}

    for table in ["tracked_dependencies", "user_interests", "notification_settings", "citation_prefs"]:
        rows = supabase.table(table).select("*", count="exact").eq("user_id", test_user["id"]).execute()
        assert rows.count == 0, f"{table} still has rows for deleted user"

    profile = supabase.table("profiles").select("*", count="exact").eq("id", test_user["id"]).execute()
    assert profile.count == 0, "profile still exists for deleted user"

    du = supabase.table("dependency_updates").select("*", count="exact").eq("package_name", "react").execute()
    assert du.count >= 1, "dependency_updates row should remain (shared cache)"

    other_deps = supabase.table("tracked_dependencies").select("*", count="exact").eq("user_id", second_user["id"]).execute()
    assert other_deps.count >= 1, "second user's deps should survive"


def test_delete_me_no_auth_returns_401():
    response = client.delete("/me")
    assert response.status_code == 401
