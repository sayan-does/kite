"""Tests for the stack risk report (pure aggregation + empty-stack endpoint)."""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.routers.stack import summarize_risk

client = TestClient(app)


def _item(status, gap=0, pkg="p"):
    return {
        "project_name": "proj",
        "ecosystem": "npm",
        "package_name": pkg,
        "tracked_version": "1.0.0",
        "latest_version": "2.0.0",
        "status": status,
        "version_gap": gap,
        "update": {"summary": f"{status} update"},
    }


def test_summarize_counts_and_level_high():
    report = summarize_risk([_item("security"), _item("up_to_date"), _item("update_available")])
    assert report["total"] == 3
    assert report["counts"]["security"] == 1
    assert report["risk_level"] == "high"
    assert report["risk_score"] == 10 + 0 + 2
    # at_risk excludes up_to_date, security ranked first
    assert [i["status"] for i in report["at_risk"]] == ["security", "update_available"]


def test_summarize_level_medium_and_low():
    assert summarize_risk([_item("update_available"), _item("up_to_date")])["risk_level"] == "medium"
    assert summarize_risk([_item("up_to_date"), _item("up_to_date")])["risk_level"] == "low"


def test_summarize_orders_by_severity_then_gap():
    report = summarize_risk([
        _item("update_available", gap=5, pkg="a"),
        _item("breaking", gap=1, pkg="b"),
        _item("breaking", gap=9, pkg="c"),
    ])
    order = [(i["status"], i["package_name"]) for i in report["at_risk"]]
    assert order == [("breaking", "c"), ("breaking", "b"), ("update_available", "a")]


@pytest.fixture(scope="module")
def test_user():
    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users"
    h = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    email = f"risk-{uuid.uuid4().hex[:8]}@example.com"
    pw = uuid.uuid4().hex
    r = httpx.post(url, headers=h, json={"email": email, "password": pw, "email_confirm": True})
    r.raise_for_status()
    uid = r.json()["id"]
    s = httpx.post(
        f"{settings.SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": settings.SUPABASE_ANON_KEY, "Content-Type": "application/json"},
        json={"email": email, "password": pw},
    )
    s.raise_for_status()
    yield {"id": uid, "access_token": s.json()["access_token"]}
    try:
        httpx.delete(f"{url}/{uid}", headers=h)
    except Exception:
        pass


def test_risk_report_empty_stack(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    resp = client.get("/stack/risk-report", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["risk_level"] == "none"
    assert data["at_risk"] == []
