"""Feed build progress: monotonic percent and the /feed/progress endpoint."""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import supabase
from app.main import app
from app.services import feed_jobs

client = TestClient(app)


# ---------------------------------------------------------------------------
# Percent arithmetic
# ---------------------------------------------------------------------------


def test_percent_starts_visible_before_any_work():
    assert feed_jobs.compute_percent({}) == feed_jobs._MIN_VISIBLE_PERCENT


def test_percent_tracks_collect_progress():
    half_collect = feed_jobs.compute_percent({"feeds_total": 10, "feeds_done": 5})
    assert half_collect == feed_jobs.COLLECT_WEIGHT // 2


def test_percent_caps_collect_at_its_weight():
    full_collect = feed_jobs.compute_percent({"feeds_total": 4, "feeds_done": 4})
    assert full_collect == feed_jobs.COLLECT_WEIGHT


def test_percent_adds_review_progress_on_top_of_collect():
    percent = feed_jobs.compute_percent({
        "feeds_total": 4,
        "feeds_done": 4,
        "articles_inserted": 10,
        "articles_reviewed": 5,
    })
    assert percent == feed_jobs.COLLECT_WEIGHT + feed_jobs.REVIEW_WEIGHT // 2


def test_percent_never_decreases():
    # A later stage resetting a counter must not rewind the bar.
    percent = feed_jobs.compute_percent({
        "percent": 55,
        "feeds_total": 10,
        "feeds_done": 1,
    })
    assert percent == 55


def test_percent_stops_below_full_while_running():
    percent = feed_jobs.compute_percent({
        "feeds_total": 4,
        "feeds_done": 4,
        "articles_inserted": 4,
        "articles_reviewed": 4,
    })
    assert percent == 99


def test_percent_is_full_once_the_job_is_done():
    assert feed_jobs.compute_percent({"status": "done"}) == 100
    assert feed_jobs.compute_percent({"status": "failed"}) == 100
    assert feed_jobs.compute_percent({"stage": "done"}) == 100


def test_percent_ignores_counters_beyond_their_totals():
    percent = feed_jobs.compute_percent({"feeds_total": 3, "feeds_done": 99})
    assert percent == feed_jobs.COLLECT_WEIGHT


def test_percent_survives_a_zero_total():
    assert feed_jobs.compute_percent({"feeds_total": 0, "feeds_done": 5}) == (
        feed_jobs._MIN_VISIBLE_PERCENT
    )


def test_job_helpers_are_no_ops_without_a_job_id():
    # Progress tracking is best-effort and must never break a real build.
    feed_jobs.update(None, feeds_done=1)
    feed_jobs.increment(None, "feeds_done")
    feed_jobs.finish(None)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def progress_user():
    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users"
    admin_headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    email = f"progress-test-{uuid.uuid4().hex[:8]}@example.com"
    password = uuid.uuid4().hex
    resp = httpx.post(
        url,
        headers=admin_headers,
        json={"email": email, "password": password, "email_confirm": True},
    )
    resp.raise_for_status()
    user_id = resp.json()["id"]

    sign_in = httpx.post(
        f"{settings.SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": settings.SUPABASE_ANON_KEY, "Content-Type": "application/json"},
        json={"email": email, "password": password},
    )
    sign_in.raise_for_status()
    token = sign_in.json()["access_token"]
    client.post("/auth/callback", json={"access_token": token})

    yield {"id": user_id, "headers": {"Authorization": f"Bearer {token}"}}

    try:
        supabase.table("feed_build_jobs").delete().eq("user_id", user_id).execute()
        httpx.delete(f"{url}/{user_id}", headers=admin_headers)
    except Exception:
        pass


def test_progress_requires_auth():
    assert client.get("/feed/progress").status_code in (401, 403)


def test_progress_is_idle_for_a_user_with_no_job(progress_user):
    response = client.get("/feed/progress", headers=progress_user["headers"])
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "idle"
    assert data["percent"] == 0
    assert data["categories_total"] == 0


def test_progress_reports_a_created_job(progress_user):
    job_id = feed_jobs.create_job(progress_user["id"], ["Frontend", "Security"])
    assert job_id is not None

    response = client.get("/feed/progress", headers=progress_user["headers"])
    data = response.json()
    assert data["status"] == "pending"
    assert data["stage"] == "queued"
    assert data["topics"] == ["Frontend", "Security"]
    assert data["percent"] >= feed_jobs._MIN_VISIBLE_PERCENT


def test_progress_reflects_pipeline_updates(progress_user):
    job_id = feed_jobs.create_job(progress_user["id"], ["Frontend"])
    feed_jobs.update(job_id, status="running", stage="collecting", feeds_total=4)
    for _ in range(2):
        feed_jobs.increment(job_id, "feeds_done")

    data = client.get("/feed/progress", headers=progress_user["headers"]).json()
    assert data["stage"] == "collecting"
    assert data["feeds_done"] == 2
    assert data["percent"] == feed_jobs.COLLECT_WEIGHT // 2


def test_progress_percent_does_not_regress_across_updates(progress_user):
    job_id = feed_jobs.create_job(progress_user["id"], ["Frontend"])
    feed_jobs.update(job_id, feeds_total=4, feeds_done=4)
    high = client.get("/feed/progress", headers=progress_user["headers"]).json()["percent"]

    feed_jobs.update(job_id, feeds_total=100, feeds_done=1)
    after = client.get("/feed/progress", headers=progress_user["headers"]).json()["percent"]
    assert after >= high


def test_progress_is_complete_once_finished(progress_user):
    job_id = feed_jobs.create_job(progress_user["id"], ["Frontend"])
    feed_jobs.finish(job_id)

    data = client.get("/feed/progress", headers=progress_user["headers"]).json()
    assert data["status"] == "done"
    assert data["percent"] == 100
    assert data["error"] is None


def test_progress_surfaces_a_failure(progress_user):
    job_id = feed_jobs.create_job(progress_user["id"], ["Frontend"])
    feed_jobs.finish(job_id, error="collector exploded")

    data = client.get("/feed/progress", headers=progress_user["headers"]).json()
    assert data["status"] == "failed"
    assert data["error"] == "collector exploded"


def test_progress_reports_per_category_readiness(progress_user):
    headers = progress_user["headers"]
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)

    data = client.get("/feed/progress", headers=headers).json()
    assert data["categories_total"] == 1
    assert "Frontend" in data["per_category"]
    # The live knowledgebase already has Frontend articles, so this category
    # reads as ready even before the new job finishes.
    assert data["per_category"]["Frontend"] == data["articles_ready"]


def test_progress_returns_the_latest_job_only(progress_user):
    feed_jobs.create_job(progress_user["id"], ["Frontend"])
    newest = feed_jobs.create_job(progress_user["id"], ["Security", "DevOps"])
    feed_jobs.update(newest, status="running", stage="ranking")

    data = client.get("/feed/progress", headers=progress_user["headers"]).json()
    assert data["stage"] == "ranking"
    assert data["topics"] == ["Security", "DevOps"]
