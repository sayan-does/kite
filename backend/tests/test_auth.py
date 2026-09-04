import uuid

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from supabase import create_client

from app.config import settings

_supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

app = FastAPI()

from app.auth import get_current_user_id


@app.get("/_guard")
async def _guard(user_id: str = Depends(get_current_user_id)):
    return {"user_id": user_id}


guard_client = TestClient(app)


@pytest.fixture(scope="module")
def test_user_token():
    import httpx

    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users"
    headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    email = f"test-{uuid.uuid4().hex[:8]}@example.com"
    password = uuid.uuid4().hex
    body = {
        "email": email,
        "password": password,
        "email_confirm": True,
    }
    resp = httpx.post(url, headers=headers, json=body)
    resp.raise_for_status()
    user_data = resp.json()
    user_id = user_data["id"]

    sign_in_resp = httpx.post(
        f"{settings.SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": settings.SUPABASE_ANON_KEY, "Content-Type": "application/json"},
        json={"email": email, "password": password},
    )
    sign_in_resp.raise_for_status()
    access_token = sign_in_resp.json()["access_token"]

    yield access_token

    try:
        httpx.delete(
            f"{url}/{user_id}",
            headers=headers,
        )
    except Exception:
        pass


def test_no_header():
    response = guard_client.get("/_guard")
    assert response.status_code == 401


def test_tampered_token():
    headers = {"Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalid.tampered"}
    response = guard_client.get("/_guard", headers=headers)
    assert response.status_code == 401


def test_valid_token(test_user_token):
    headers = {"Authorization": f"Bearer {test_user_token}"}
    response = guard_client.get("/_guard", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert uuid.UUID(data["user_id"])
