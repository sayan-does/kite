import uuid

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
    email = f"stack-projects-{uuid.uuid4().hex[:8]}@example.com"
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
        httpx.delete(f"{url}/{user_id}", headers=admin_headers)
    except Exception:
        pass


def test_list_projects_empty(test_user):
    _counts.pop(test_user["id"], None)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    supabase.table("tracked_dependencies").delete().eq("user_id", test_user["id"]).execute()

    response = client.get("/stack/projects", headers=headers)
    assert response.status_code == 200
    assert response.json()["projects"] == []


def test_list_projects_aggregates_counts(test_user):
    _counts.pop(test_user["id"], None)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    supabase.table("tracked_dependencies").delete().eq("user_id", test_user["id"]).execute()

    client.post(
        "/stack",
        json={
            "project_name": "frontend",
            "ecosystem": "npm",
            "package_name": "react",
            "version": "18.0.0",
        },
        headers=headers,
    )
    client.post(
        "/stack",
        json={
            "project_name": "backend",
            "ecosystem": "pip",
            "package_name": "flask",
            "version": "2.0.0",
        },
        headers=headers,
    )

    response = client.get("/stack/projects", headers=headers)
    assert response.status_code == 200
    projects = response.json()["projects"]
    names = [p["project_name"] for p in projects]
    assert "backend" in names
    assert "frontend" in names
    assert names.index("backend") < names.index("frontend")

    frontend = next(p for p in projects if p["project_name"] == "frontend")
    assert frontend["dep_count"] == 1
    assert sum(frontend["counts"].values()) == 1


def test_project_digest_scopes_to_project(test_user):
    _counts.pop(test_user["id"], None)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}

    response = client.get("/stack/projects/frontend/digest", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["project_name"] == "frontend"
    assert all(i["project_name"] == "frontend" for i in data["items"])
    assert any(i["package_name"] == "react" for i in data["items"])
    assert not any(i["package_name"] == "flask" for i in data["items"])


def test_project_digest_unknown_returns_empty(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    response = client.get("/stack/projects/does-not-exist/digest", headers=headers)
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_rename_project(test_user):
    _counts.pop(test_user["id"], None)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}

    response = client.patch(
        "/stack/projects/rename",
        json={"old_name": "frontend", "new_name": "web-app"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["project_name"] == "web-app"
    assert response.json()["renamed"] == 1

    projects = client.get("/stack/projects", headers=headers).json()["projects"]
    names = [p["project_name"] for p in projects]
    assert "web-app" in names
    assert "frontend" not in names


def test_rename_project_conflict_returns_409(test_user):
    _counts.pop(test_user["id"], None)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}

    client.post(
        "/stack",
        json={
            "project_name": "other",
            "ecosystem": "npm",
            "package_name": "react",
            "version": "17.0.0",
        },
        headers=headers,
    )

    response = client.patch(
        "/stack/projects/rename",
        json={"old_name": "web-app", "new_name": "other"},
        headers=headers,
    )
    assert response.status_code == 409


def test_delete_project(test_user):
    _counts.pop(test_user["id"], None)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}

    response = client.delete(
        "/stack/projects/by-name",
        params={"project_name": "backend"},
        headers=headers,
    )
    assert response.status_code == 204

    projects = client.get("/stack/projects", headers=headers).json()["projects"]
    names = [p["project_name"] for p in projects]
    assert "backend" not in names


def test_delete_project_not_found(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    response = client.delete(
        "/stack/projects/by-name",
        params={"project_name": "missing-project"},
        headers=headers,
    )
    assert response.status_code == 404
