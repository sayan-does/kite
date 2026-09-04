"""Phase 7 gate: DISCOVERY_V2 dry run — verify per-user feed capped at 10."""
import asyncio
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
os.environ["DISCOVERY_V2"] = "true"

from app.agents.discovery.graph import run_discovery_for_user
from app.config import settings
from app.db import supabase


def _create_test_user() -> str:
    import httpx

    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users"
    headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    email = f"phase7-dry-{uuid.uuid4().hex[:8]}@example.com"
    password = uuid.uuid4().hex
    resp = httpx.post(url, headers=headers, json={"email": email, "password": password, "email_confirm": True})
    resp.raise_for_status()
    return resp.json()["id"]


async def main():
    user_id = _create_test_user()
    supabase.table("profiles").upsert({"id": user_id}, on_conflict="id").execute()
    supabase.table("user_interests").insert({"user_id": user_id, "tag_id": 1}).execute()
    supabase.table("tracked_dependencies").insert({
        "user_id": user_id,
        "ecosystem": "npm",
        "package_name": "react",
        "version": "18.0.0",
        "source": "manual",
    }).execute()

    fake_results = [
        {
            "title": f"Article {i}",
            "url": f"https://dev.to/react-news-{i}",
            "snippet": f"React frontend framework news 2026 update number {i}",
        }
        for i in range(15)
    ]
    call_idx = {"n": 0}

    async def rotating_search(query):
        call_idx["n"] += 1
        return [fake_results[call_idx["n"] % len(fake_results)]]

    fake_llm = MagicMock()
    fake_llm.content = (
        '{"one_liner": "React ships updates.", '
        '"full_summary": "A detailed summary of the latest React release.", '
        '"source_type": "blog"}'
    )

    with (
        patch("app.agents.discovery.nodes.search", side_effect=rotating_search),
        patch("app.agents.discovery.nodes.fetch_article_text", AsyncMock(return_value="Long article about React framework updates in 2026.")),
        patch("app.agents.discovery.nodes.groq_client") as mock_groq,
        patch("app.agents.discovery.nodes._owned_urls", return_value=set()),
    ):
        mock_groq.invoke = MagicMock(return_value=fake_llm)
        await run_discovery_for_user(user_id)

    articles = (
        supabase.table("articles")
        .select("id, one_liner, source, topic, source_type")
        .eq("user_id", user_id)
        .order("fetched_at", desc=True)
        .execute()
        .data
        or []
    )

    print(f"User {user_id}: {len(articles)} cards (cap=10)")
    for a in articles[:3]:
        print(f"  - source={a.get('source')} topic={a.get('topic')} one_liner={a.get('one_liner')[:40]}...")

    # cleanup
    supabase.table("articles").delete().eq("user_id", user_id).execute()
    supabase.table("tracked_dependencies").delete().eq("user_id", user_id).execute()
    supabase.table("user_interests").delete().eq("user_id", user_id).execute()
    supabase.table("profiles").delete().eq("id", user_id).execute()
    import httpx
    httpx.delete(
        f"{settings.SUPABASE_URL}/auth/v1/admin/users/{user_id}",
        headers={
            "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        },
        timeout=10,
    )

    assert len(articles) <= 10, f"Expected <=10 cards, got {len(articles)}"
    assert all(a.get("one_liner") for a in articles)
    assert all(a.get("source") in ("interest", "stack") for a in articles)
    print("DISCOVERY_V2 dry run: PASS")


if __name__ == "__main__":
    asyncio.run(main())
