import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
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
    email = f"cp-test-{uuid.uuid4().hex[:8]}@example.com"
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
        httpx.delete(f"{url}/{user_id}", headers=admin_headers)
    except Exception:
        pass


def test_first_get_returns_all_enabled(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    response = client.get("/me/citation-prefs", headers=headers)
    assert response.status_code == 200
    prefs = response.json()["prefs"]
    for st in ("official_docs", "github", "blog", "youtube"):
        assert prefs[st] is True


def test_put_disabling_blog_persists(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    put_resp = client.put("/me/citation-prefs", json={"prefs": {"blog": False}}, headers=headers)
    assert put_resp.status_code == 200
    assert put_resp.json()["prefs"]["blog"] is False

    get_resp = client.get("/me/citation-prefs", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["prefs"]["blog"] is False
    assert get_resp.json()["prefs"]["official_docs"] is True


def test_put_invalid_source_type_returns_422(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    response = client.put(
        "/me/citation-prefs",
        json={"prefs": {"unknown_type": False}},
        headers=headers,
    )
    assert response.status_code == 422
