import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import supabase
from app.main import app
from app.services.rate_limit import _counts
from app.services.scheduler import prune_package_version_timeline

client = TestClient(app)

PKG = f"timeline-pkg-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def test_user():
    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users"
    admin_headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    email = f"timeline-{uuid.uuid4().hex[:8]}@example.com"
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
        supabase.table("dependency_updates").delete().eq("package_name", PKG).execute()
        supabase.table("package_registry_cache").delete().eq("package_name", PKG).execute()
        supabase.table("package_version_timeline").delete().eq("package_name", PKG).execute()
        httpx.delete(f"{url}/{user_id}", headers=admin_headers)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def seed_package_data(test_user):
    now = datetime.now(timezone.utc)
    supabase.table("package_registry_cache").upsert({
        "ecosystem": "npm",
        "package_name": PKG,
        "latest_version": "2.1.0",
        "last_checked_at": now.isoformat(),
    }, on_conflict="ecosystem, package_name").execute()

    supabase.table("dependency_updates").upsert({
        "ecosystem": "npm",
        "package_name": PKG,
        "version": "2.1.0",
        "update_type": "breaking",
        "summary": "Breaking API rename in 2.x",
        "citations": [],
    }, on_conflict="ecosystem, package_name, version, update_type").execute()

    supabase.table("package_version_timeline").upsert([
        {
            "ecosystem": "npm",
            "package_name": PKG,
            "version": "2.1.0",
            "published_at": now.isoformat(),
            "summary": "Breaking API rename",
            "is_security": False,
            "is_breaking": True,
            "citations": [],
        },
        {
            "ecosystem": "npm",
            "package_name": PKG,
            "version": "2.0.1",
            "published_at": (now - timedelta(days=10)).isoformat(),
            "summary": "Patch fix",
            "is_security": False,
            "is_breaking": False,
            "citations": [],
        },
        {
            "ecosystem": "npm",
            "package_name": PKG,
            "version": "2.0.0",
            "published_at": (now - timedelta(days=20)).isoformat(),
            "summary": "Security fix for XSS",
            "is_security": True,
            "is_breaking": False,
            "citations": [{"type": "official_docs", "url": "https://osv.dev/GHSA-test", "title": "GHSA-test"}],
        },
    ], on_conflict="ecosystem, package_name, version").execute()

    yield

    supabase.table("dependency_updates").delete().eq("package_name", PKG).execute()
    supabase.table("package_registry_cache").delete().eq("package_name", PKG).execute()
    supabase.table("package_version_timeline").delete().eq("package_name", PKG).execute()


def test_digest_includes_status_and_version_gap(test_user):
    _counts.pop(test_user["id"], None)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}

    client.post(
        "/stack",
        json={
            "project_name": "demo",
            "ecosystem": "npm",
            "package_name": PKG,
            "version": "1.0.0",
        },
        headers=headers,
    )

    response = client.get("/stack/digest", headers=headers)
    assert response.status_code == 200
    item = next(i for i in response.json()["items"] if i["package_name"] == PKG)
    assert item["project_name"] == "demo"
    assert item["latest_version"] == "2.1.0"
    assert item["status"] == "security"
    assert item["version_gap"]["kind"] == "major"
    assert item["version_gap"]["tracked"] == "1.0.0"
    assert item["version_gap"]["latest"] == "2.1.0"


def test_digest_update_available_without_update_row(test_user):
    _counts.pop(test_user["id"], None)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    plain = f"plain-{uuid.uuid4().hex[:8]}"

    supabase.table("package_registry_cache").upsert({
        "ecosystem": "npm",
        "package_name": plain,
        "latest_version": "3.0.0",
    }, on_conflict="ecosystem, package_name").execute()

    client.post(
        "/stack",
        json={
            "project_name": "demo",
            "ecosystem": "npm",
            "package_name": plain,
            "version": "2.0.0",
        },
        headers=headers,
    )

    response = client.get("/stack/digest", headers=headers)
    item = next(i for i in response.json()["items"] if i["package_name"] == plain)
    assert item["status"] == "update_available"
    assert item["version_gap"]["kind"] == "major"

    supabase.table("tracked_dependencies").delete().eq("package_name", plain).execute()
    supabase.table("package_registry_cache").delete().eq("package_name", plain).execute()


def test_package_detail_returns_timeline(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    client.post(
        "/stack",
        json={
            "project_name": "demo",
            "ecosystem": "npm",
            "package_name": PKG,
            "version": "1.0.0",
        },
        headers=headers,
    )

    response = client.get(f"/stack/packages/npm/{PKG}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["tracked_version"] == "1.0.0"
    assert data["latest_version"] == "2.1.0"
    assert data["status"] == "security"
    versions = {t["version"] for t in data["timeline"]}
    assert "2.1.0" in versions
    assert "2.0.0" in versions
    security = next(t for t in data["timeline"] if t["version"] == "2.0.0")
    assert security["is_security"] is True
    assert data["summary"] == "Breaking API rename in 2.x"


def test_package_detail_whats_new_from_timeline_when_no_headline(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    pkg = f"notes-only-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    supabase.table("package_registry_cache").upsert({
        "ecosystem": "npm",
        "package_name": pkg,
        "latest_version": "2.0.0",
        "last_checked_at": now.isoformat(),
    }, on_conflict="ecosystem, package_name").execute()
    supabase.table("package_version_timeline").upsert([
        {
            "ecosystem": "npm",
            "package_name": pkg,
            "version": "2.0.0",
            "published_at": now.isoformat(),
            "summary": "Breaking API rename",
            "is_security": False,
            "is_breaking": True,
            "citations": [],
        },
        {
            "ecosystem": "npm",
            "package_name": pkg,
            "version": "1.9.0",
            "published_at": (now - timedelta(days=5)).isoformat(),
            "summary": "<p>Security fix for XSS</p>",
            "is_security": True,
            "is_breaking": False,
            "citations": [],
        },
    ], on_conflict="ecosystem, package_name, version").execute()

    client.post(
        "/stack",
        json={
            "project_name": "demo",
            "ecosystem": "npm",
            "package_name": pkg,
            "version": "1.0.0",
        },
        headers=headers,
    )

    try:
        response = client.get(f"/stack/packages/npm/{pkg}", headers=headers)
        assert response.status_code == 200
        summary = response.json()["summary"]
        assert "Security fix for XSS" in summary
        assert "<p>" not in summary
        assert "Breaking API rename" in summary
    finally:
        supabase.table("tracked_dependencies").delete().eq("package_name", pkg).execute()
        supabase.table("package_registry_cache").delete().eq("package_name", pkg).execute()
        supabase.table("package_version_timeline").delete().eq("package_name", pkg).execute()


def test_package_detail_whats_new_fallback_without_notes(test_user):
    _counts.pop(test_user["id"], None)
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    pkg = f"no-notes-{uuid.uuid4().hex[:8]}"

    supabase.table("package_registry_cache").upsert({
        "ecosystem": "npm",
        "package_name": pkg,
        "latest_version": "3.0.0",
    }, on_conflict="ecosystem, package_name").execute()

    client.post(
        "/stack",
        json={
            "project_name": "demo",
            "ecosystem": "npm",
            "package_name": pkg,
            "version": "2.0.0",
        },
        headers=headers,
    )

    try:
        response = client.get(f"/stack/packages/npm/{pkg}", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "update_available"
        assert data["summary"] == (
            "Update available: 2.0.0 → 3.0.0 (major). Release notes are not available yet."
        )
    finally:
        supabase.table("tracked_dependencies").delete().eq("package_name", pkg).execute()
        supabase.table("package_registry_cache").delete().eq("package_name", pkg).execute()


def test_package_detail_404_for_untracked(test_user):
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    response = client.get("/stack/packages/npm/not-tracked-ever-xyz", headers=headers)
    assert response.status_code == 404


def test_prune_removes_old_timeline_rows():
    old_pkg = f"old-timeline-{uuid.uuid4().hex[:8]}"
    old_ts = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    recent_ts = datetime.now(timezone.utc).isoformat()

    supabase.table("package_version_timeline").upsert([
        {
            "ecosystem": "npm",
            "package_name": old_pkg,
            "version": "0.1.0",
            "published_at": old_ts,
            "summary": "old",
            "is_security": False,
            "is_breaking": False,
            "citations": [],
            "ingested_at": old_ts,
        },
        {
            "ecosystem": "npm",
            "package_name": old_pkg,
            "version": "0.2.0",
            "published_at": recent_ts,
            "summary": "recent",
            "is_security": False,
            "is_breaking": False,
            "citations": [],
            "ingested_at": recent_ts,
        },
    ], on_conflict="ecosystem, package_name, version").execute()

    deleted = prune_package_version_timeline(retention_days=90)
    assert deleted >= 1

    remaining = (
        supabase.table("package_version_timeline")
        .select("version")
        .eq("package_name", old_pkg)
        .execute()
        .data
        or []
    )
    versions = {r["version"] for r in remaining}
    assert "0.1.0" not in versions
    assert "0.2.0" in versions

    supabase.table("package_version_timeline").delete().eq("package_name", old_pkg).execute()
