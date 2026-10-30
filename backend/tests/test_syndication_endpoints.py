"""Endpoint tests for the personal token + RSS + OPML export (live Supabase)."""

import uuid
import xml.etree.ElementTree as ET

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.tokens import mint_token

client = TestClient(app)


@pytest.fixture(scope="module")
def test_user():
    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users"
    admin_headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    email = f"syn-test-{uuid.uuid4().hex[:8]}@example.com"
    password = uuid.uuid4().hex
    resp = httpx.post(url, headers=admin_headers, json={"email": email, "password": password, "email_confirm": True})
    resp.raise_for_status()
    user_id = resp.json()["id"]
    sign_in = httpx.post(
        f"{settings.SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": settings.SUPABASE_ANON_KEY, "Content-Type": "application/json"},
        json={"email": email, "password": password},
    )
    sign_in.raise_for_status()
    yield {"id": user_id, "access_token": sign_in.json()["access_token"]}
    try:
        httpx.delete(f"{url}/{user_id}", headers=admin_headers)
    except Exception:
        pass


def test_me_token_returns_usable_token(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    resp = client.get("/me/token", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["token"].startswith("kite_")
    assert data["token"] in data["rss_url"]
    # token resolves back to this user
    assert data["token"] == mint_token(test_user["id"])


def test_rss_requires_valid_token():
    assert client.get("/feed.rss").status_code == 422  # missing token
    assert client.get("/feed.rss?token=bogus").status_code == 401


def test_rss_returns_valid_xml(test_user):
    token = mint_token(test_user["id"])
    resp = client.get(f"/feed.rss?token={token}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/rss+xml")
    root = ET.fromstring(resp.text)  # must parse
    assert root.tag == "rss"
    assert root.find("./channel/title") is not None


def test_opml_requires_valid_token():
    assert client.get("/me/sources.opml?token=bogus").status_code == 401


def test_opml_returns_valid_xml(test_user):
    token = mint_token(test_user["id"])
    resp = client.get(f"/me/sources.opml?token={token}")
    assert resp.status_code == 200
    root = ET.fromstring(resp.text)
    assert root.tag == "opml"
