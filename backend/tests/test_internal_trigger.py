import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app


@pytest.mark.asyncio
async def test_internal_refresh_requires_secret():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/internal/refresh?mode=fast")
    assert resp.status_code in (401, 503)


@pytest.mark.asyncio
async def test_internal_refresh_accepts_valid_secret(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_TRIGGER_SECRET", "test-secret")

    async def fake_fast(**kwargs):
        return {"inserted": 0}

    monkeypatch.setattr("app.routers.internal.run_fast_cycle", fake_fast)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/refresh?mode=fast",
            headers={"X-Internal-Secret": "test-secret"},
        )
    assert resp.status_code == 200
    assert resp.json()["started"] is True


@pytest.mark.asyncio
async def test_internal_run_daily_requires_secret():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/internal/run-daily")
    assert resp.status_code in (401, 503)


@pytest.mark.asyncio
async def test_internal_run_daily_accepts_valid_secret(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_TRIGGER_SECRET", "test-secret")

    async def fake_daily():
        return None

    monkeypatch.setattr("app.routers.internal.run_daily", fake_daily)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/run-daily",
            headers={"X-Internal-Secret": "test-secret"},
        )
    assert resp.status_code == 200
    assert resp.json()["started"] is True
