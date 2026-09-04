import os
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import supabase
from app.main import app

client = TestClient(app)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture(scope="module")
def test_user():
    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users"
    admin_headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    email = f"stack-upload-{uuid.uuid4().hex[:8]}@example.com"
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


def _read_fixture(name: str) -> bytes:
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


def _upload(headers, filename: str, raw: bytes, project_name: str = "demo-app", content_type: str = "text/plain"):
    return client.post(
        "/stack/upload",
        files={"file": (filename, raw, content_type)},
        data={"project_name": project_name},
        headers=headers,
    )


def test_upload_requires_project_name(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    raw = _read_fixture("package.json")
    response = client.post(
        "/stack/upload",
        files={"file": ("package.json", raw, "application/json")},
        headers=headers,
    )
    assert response.status_code == 422


def test_upload_package_json_creates_rows(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    supabase.table("tracked_dependencies").delete().eq("user_id", test_user["id"]).execute()

    raw = _read_fixture("package.json")
    response = _upload(headers, "package.json", raw, "frontend", "application/json")
    assert response.status_code == 201
    data = response.json()
    assert data["count"] == 4
    assert data["project_name"] == "frontend"
    assert len(data["dependencies"]) == 4

    deps = (
        supabase.table("tracked_dependencies")
        .select("ecosystem, package_name, version, project_name")
        .eq("user_id", test_user["id"])
        .execute()
    )
    names = [(d["ecosystem"], d["package_name"]) for d in deps.data]
    assert ("npm", "react") in names
    assert ("npm", "typescript") in names
    assert all(d["project_name"] == "frontend" for d in deps.data)


def test_re_upload_no_duplicates(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    raw = _read_fixture("package.json")

    response = _upload(headers, "package.json", raw, "frontend", "application/json")
    assert response.status_code == 201

    deps = (
        supabase.table("tracked_dependencies")
        .select("id")
        .eq("user_id", test_user["id"])
        .eq("project_name", "frontend")
        .eq("ecosystem", "npm")
        .eq("package_name", "react")
        .execute()
    )
    assert len(deps.data) == 1


def test_upload_requirements_txt_creates_rows(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    raw = _read_fixture("requirements.txt")
    response = _upload(headers, "requirements.txt", raw, "backend")
    assert response.status_code == 201
    data = response.json()
    assert data["count"] == 3
    assert data["project_name"] == "backend"


def test_upload_pyproject_toml_creates_rows(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    raw = _read_fixture("pyproject.toml")
    response = _upload(headers, "pyproject.toml", raw, "backend", "application/octet-stream")
    assert response.status_code == 201
    data = response.json()
    assert data["count"] == 2


def test_upload_empty_valid_file_returns_ok(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    response = _upload(headers, "requirements.txt", b"# just a comment\n", "empty-proj")
    assert response.status_code == 201
    assert response.json()["count"] == 0


def test_upload_duplicate_entries_deduplicated(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    content = b"requests==2.31.0\nrequests==2.31.0\nflask==2.3.0"
    response = _upload(headers, "requirements.txt", content, "dedupe-proj")
    assert response.status_code == 201
    data = response.json()
    assert data["count"] == 2
    assert len(data["dependencies"]) == 2


def test_upload_invalid_file_returns_422(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    response = _upload(headers, "corrupt.json", _read_fixture("corrupt.json"), "bad", "application/json")
    assert response.status_code == 422


def test_upload_unsupported_file_returns_422(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    response = _upload(headers, "Gemfile", b"source 'https://rubygems.org'", "bad")
    assert response.status_code == 422
