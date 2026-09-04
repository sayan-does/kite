import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

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
    email = f"int-test-{uuid.uuid4().hex[:8]}@example.com"
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

    # ensure profile exists
    client.post("/auth/callback", json={"access_token": access_token})

    yield {"id": user_id, "access_token": access_token}

    try:
        httpx.delete(f"{url}/{user_id}", headers=admin_headers)
    except Exception:
        pass


def test_get_interests_empty(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    response = client.get("/me/interests", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"tag_ids": []}


def test_put_interests_then_get(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}

    put_response = client.put("/me/interests", json={"tag_ids": [1, 2]}, headers=headers)
    assert put_response.status_code == 200
    assert put_response.json()["tag_ids"] == [1, 2]

    get_response = client.get("/me/interests", headers=headers)
    assert get_response.status_code == 200
    assert get_response.json() == {"tag_ids": [1, 2]}


def test_put_interests_returns_job_id_for_progress_polling(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    response = client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)
    assert response.status_code == 200
    assert "job_id" in response.json()


def test_put_unknown_tag_id_returns_400(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    response = client.put("/me/interests", json={"tag_ids": [999]}, headers=headers)
    assert response.status_code == 400


def test_put_duplicates_deduplicated(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    response = client.put("/me/interests", json={"tag_ids": [1, 1, 2, 2, 2]}, headers=headers)
    assert response.status_code == 200
    assert response.json()["tag_ids"] == [1, 2]


def test_put_returns_sorted_ids(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    response = client.put("/me/interests", json={"tag_ids": [3, 1, 2]}, headers=headers)
    assert response.status_code == 200
    assert response.json()["tag_ids"] == [1, 2, 3]


def test_put_accepts_exactly_three_tags(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    response = client.put("/me/interests", json={"tag_ids": [1, 2, 3]}, headers=headers)
    assert response.status_code == 200
    assert response.json()["tag_ids"] == [1, 2, 3]


def test_put_more_than_three_tags_returns_400(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    response = client.put("/me/interests", json={"tag_ids": [1, 2, 3, 4]}, headers=headers)
    assert response.status_code == 400
    assert "3" in response.json()["detail"]


def test_put_more_than_three_tags_leaves_selection_unchanged(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    client.put("/me/interests", json={"tag_ids": [1, 2]}, headers=headers)

    rejected = client.put("/me/interests", json={"tag_ids": [1, 2, 3, 4]}, headers=headers)
    assert rejected.status_code == 400

    assert client.get("/me/interests", headers=headers).json() == {"tag_ids": [1, 2]}


def test_put_empty_tag_ids_returns_400(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    response = client.put("/me/interests", json={"tag_ids": []}, headers=headers)
    assert response.status_code == 400


def test_put_no_auth_returns_401():
    response = client.put("/me/interests", json={"tag_ids": [1]})
    assert response.status_code == 401


def test_put_interests_v2_triggers_run_discovery_for_user(test_user):
    with patch("app.routers.me.settings") as mock_settings:
        mock_settings.DISCOVERY_V2 = True
        headers = {"Authorization": f"Bearer {test_user['access_token']}"}
        with patch("app.routers.me.run_discovery_for_user", new_callable=AsyncMock) as mock_v2:
            with patch("app.routers.me.asyncio.create_task", side_effect=lambda coro: asyncio.ensure_future(coro)):
                response = client.put("/me/interests", json={"tag_ids": [1, 2]}, headers=headers)
                assert response.status_code == 200
            import time
            time.sleep(0.3)
            mock_v2.assert_called_once_with(test_user["id"])


@pytest.mark.asyncio
async def test_trigger_discovery_v2_calls_run_discovery_for_user():
    from app.routers.me import _trigger_discovery

    with (
        patch("app.routers.me.settings") as mock_settings,
        patch("app.routers.me.run_discovery_for_user", new_callable=AsyncMock) as mock_v2,
        patch("app.routers.me.run_discovery_for_tag", new_callable=AsyncMock) as mock_v1,
    ):
        mock_settings.DISCOVERY_V2 = True
        await _trigger_discovery("user-id", [1, 2])
        mock_v2.assert_called_once_with("user-id")
        mock_v1.assert_not_called()


@pytest.mark.asyncio
async def test_trigger_discovery_v1_calls_per_tag():
    from app.routers.me import _trigger_discovery

    with (
        patch("app.routers.me.settings") as mock_settings,
        patch("app.routers.me.run_discovery_for_user", new_callable=AsyncMock) as mock_v2,
        patch("app.routers.me.run_discovery_for_tag", new_callable=AsyncMock) as mock_v1,
        patch("app.routers.me.supabase") as mock_sb,
    ):
        mock_settings.DISCOVERY_V2 = False
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.select.return_value.eq.return_value.gt.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"name": "Frontend"}])

        await _trigger_discovery("user-id", [1, 2])
        mock_v2.assert_not_called()
        assert mock_v1.call_count == 2
