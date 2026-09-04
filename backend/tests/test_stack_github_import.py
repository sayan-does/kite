import os
import uuid
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import supabase
from app.main import app
from app.services.github_client import GitHubError

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
    email = f"stack-github-{uuid.uuid4().hex[:8]}@example.com"
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


def _auth(test_user, github_token: str | None = "gh-test-token"):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    if github_token is not None:
        headers["X-GitHub-Token"] = github_token
    return headers


def test_github_repos_requires_token(test_user):
    response = client.get("/stack/github/repos", headers=_auth(test_user, github_token=None))
    assert response.status_code == 401


def test_github_repos_lists(test_user):
    fake = [
        {
            "full_name": "acme/api",
            "private": False,
            "default_branch": "main",
            "description": None,
        }
    ]
    with patch("app.routers.stack.github_client.list_repos", return_value=fake):
        response = client.get("/stack/github/repos", headers=_auth(test_user))
    assert response.status_code == 200
    assert response.json()["repos"][0]["full_name"] == "acme/api"


def test_github_tree_lists_path(test_user):
    fake = [
        {
            "name": "requirements.txt",
            "path": "backend/requirements.txt",
            "type": "file",
            "is_manifest": True,
        }
    ]
    with patch("app.routers.stack.github_client.list_directory", return_value=fake):
        response = client.get(
            "/stack/github/tree",
            params={"repo": "acme/api", "path": "backend"},
            headers=_auth(test_user),
        )
    assert response.status_code == 200
    data = response.json()
    assert data["path"] == "backend"
    assert data["entries"][0]["is_manifest"] is True


def test_github_import_upserts_with_source_github(test_user):
    headers = _auth(test_user)
    supabase.table("tracked_dependencies").delete().eq("user_id", test_user["id"]).execute()

    with open(os.path.join(FIXTURES, "requirements.txt"), "rb") as f:
        raw = f.read()

    with patch("app.routers.stack.github_client.get_file_content", return_value=raw):
        response = client.post(
            "/stack/github/import",
            headers=headers,
            json={"repo": "acme/api", "path": "backend", "filename": "requirements.txt"},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["count"] == 3
    assert data["path"] == "backend/requirements.txt"
    assert data["project_name"] == "api"

    deps = (
        supabase.table("tracked_dependencies")
        .select("source, github_repo, github_path, package_name, project_name")
        .eq("user_id", test_user["id"])
        .execute()
    )
    assert len(deps.data) >= 3
    assert all(d["source"] == "github" for d in deps.data)
    assert all(d["github_repo"] == "acme/api" for d in deps.data)
    assert all(d["github_path"] == "backend/requirements.txt" for d in deps.data)
    assert all(d["project_name"] == "api" for d in deps.data)


def test_github_import_unsupported_filename(test_user):
    response = client.post(
        "/stack/github/import",
        headers=_auth(test_user),
        json={"repo": "acme/api", "path": "", "filename": "Gemfile"},
    )
    assert response.status_code == 422


def test_github_import_propagates_not_found(test_user):
    with patch(
        "app.routers.stack.github_client.get_file_content",
        side_effect=GitHubError(404, "File not found: missing.txt"),
    ):
        response = client.post(
            "/stack/github/import",
            headers=_auth(test_user),
            json={"repo": "acme/api", "path": "", "filename": "requirements.txt"},
        )
    assert response.status_code == 404
