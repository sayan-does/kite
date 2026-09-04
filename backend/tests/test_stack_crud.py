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
def user_a():
    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users"
    admin_headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    email = f"crud-a-{uuid.uuid4().hex[:8]}@example.com"
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


@pytest.fixture(scope="module")
def user_b():
    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users"
    admin_headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    email = f"crud-b-{uuid.uuid4().hex[:8]}@example.com"
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


def test_add_dependency_returns_201(user_a):
    _counts.pop(user_a["id"], None)
    headers = {"Authorization": f"Bearer {user_a['access_token']}"}
    response = client.post(
        "/stack",
        json={
            "project_name": "demo",
            "ecosystem": "npm",
            "package_name": "lodash",
            "version": "4.17.21",
        },
        headers=headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["package_name"] == "lodash"
    assert data["version"] == "4.17.21"
    assert data["source"] == "manual"
    assert data["project_name"] == "demo"


def test_duplicate_add_returns_409(user_a):
    _counts.pop(user_a["id"], None)
    headers = {"Authorization": f"Bearer {user_a['access_token']}"}
    response = client.post(
        "/stack",
        json={
            "project_name": "demo",
            "ecosystem": "npm",
            "package_name": "lodash",
            "version": "4.17.21",
        },
        headers=headers,
    )
    assert response.status_code == 409


def test_list_returns_own_deps(user_a, user_b):
    headers_a = {"Authorization": f"Bearer {user_a['access_token']}"}
    headers_b = {"Authorization": f"Bearer {user_b['access_token']}"}

    # user_b adds their own dep
    _counts.pop(user_b["id"], None)
    client.post(
        "/stack",
        json={
            "project_name": "web",
            "ecosystem": "pip",
            "package_name": "django",
            "version": "5.0",
        },
        headers=headers_b,
    )

    resp_a = client.get("/stack", headers=headers_a)
    assert resp_a.status_code == 200
    names_a = [d["package_name"] for d in resp_a.json()["dependencies"]]
    assert "lodash" in names_a
    assert "django" not in names_a


def test_patch_updates_version(user_a):
    headers = {"Authorization": f"Bearer {user_a['access_token']}"}
    deps = client.get("/stack", headers=headers).json()["dependencies"]
    dep_id = deps[0]["id"]

    response = client.patch(
        f"/stack/{dep_id}",
        json={
            "project_name": "demo",
            "ecosystem": "npm",
            "package_name": "lodash",
            "version": "5.0.0",
        },
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["version"] == "5.0.0"

    updated = client.get("/stack", headers=headers).json()["dependencies"]
    updated_dep = next(d for d in updated if d["id"] == dep_id)
    assert updated_dep["version"] == "5.0.0"


def test_delete_removes_dep(user_a):
    headers = {"Authorization": f"Bearer {user_a['access_token']}"}
    deps = client.get("/stack", headers=headers).json()["dependencies"]
    dep_id = deps[0]["id"]

    response = client.delete(f"/stack/{dep_id}", headers=headers)
    assert response.status_code == 204

    deps_after = client.get("/stack", headers=headers).json()["dependencies"]
    ids_after = [d["id"] for d in deps_after]
    assert dep_id not in ids_after


def test_delete_another_users_dep_returns_404(user_a, user_b):
    headers_a = {"Authorization": f"Bearer {user_a['access_token']}"}
    headers_b = {"Authorization": f"Bearer {user_b['access_token']}"}

    deps_b = client.get("/stack", headers=headers_b).json()["dependencies"]
    dep_b_id = deps_b[0]["id"]

    response = client.delete(f"/stack/{dep_b_id}", headers=headers_a)
    assert response.status_code == 404
