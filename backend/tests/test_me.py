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
    email = f"me-test-{uuid.uuid4().hex[:8]}@example.com"
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

    yield {"id": user_id, "access_token": access_token}

    try:
        httpx.delete(f"{url}/{user_id}", headers=admin_headers)
    except Exception:
        pass


def test_get_me_no_token():
    response = client.get("/me")
    assert response.status_code == 401


def test_callback_creates_profile(test_user):
    response = client.post(
        "/auth/callback",
        json={"access_token": test_user["access_token"]},
    )
    assert response.status_code == 200
    assert response.json()["id"] == test_user["id"]


def test_callback_idempotent(test_user):
    response = client.post(
        "/auth/callback",
        json={"access_token": test_user["access_token"]},
    )
    assert response.status_code == 200

    profiles = supabase.table("profiles").select("id", count="exact").eq("id", test_user["id"]).execute()
    assert profiles.count == 1


def test_get_me_returns_profile(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    response = client.get("/me", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == test_user["id"]
    assert "created_at" in data
