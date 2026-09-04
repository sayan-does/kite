"""Slow-loop review: triage, summarize, promote raw → reviewed."""

from __future__ import annotations

import logging
from typing import Callable

from langchain_core.messages import HumanMessage

from app.db import supabase
from app.services.article_enrich import summarize_article
from app.services.llm import BudgetExhausted, budget, for_role, parse_json_response
from app.services.youtube import resolve_youtube_url

logger = logging.getLogger(__name__)

MAX_REVIEW_BATCH = 40


async def _triage(article: dict) -> bool:
    """Return True if article has substance (not filler/SEO)."""
    client = for_role("triage")
    if client is None:
        return True
    prompt = (
        f"Title: {article.get('title')}\nSnippet: {article.get('one_liner') or article.get('summary')}\n"
        f"Topic: {article.get('topic')}\n\n"
        'Reply JSON only: {"keep": true|false, "reason": "<short>"}'
    )
    if not budget.try_spend(200):
        raise BudgetExhausted("triage budget exhausted")
    try:
        resp = await client.ainvoke([HumanMessage(content=prompt)])
        parsed = parse_json_response(resp.content or "")
        return bool(parsed.get("keep", True)) if parsed else True
    except Exception:
        return True


async def run_review_cycle(
    *,
    topics: list[str] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict:
    budget.reset_cycle()
    query = (
        supabase.table("kb_articles")
        .select("*")
        .eq("tier", "raw")
        .eq("status", "active")
    )
    if topics:
        query = query.in_("topic", topics)
    rows = (
        query.order("score", desc=True)
        .limit(MAX_REVIEW_BATCH)
        .execute()
        .data
        or []
    )

    reviewed = 0
    rejected = 0

    if on_progress:
        on_progress(0, len(rows))

    for row in rows:
        try:
            if not await _triage(row):
                supabase.table("kb_articles").update({"status": "rejected"}).eq("id", row["id"]).execute()
                rejected += 1
                continue

            summary = await summarize_article(row)
            if not summary:
                continue

            merged = {**row, **summary}
            update = {
                **summary,
                "tier": "reviewed",
                "score": float(row.get("score") or 0) * 1.15,
            }
            if not row.get("youtube_url"):
                yt = await resolve_youtube_url(merged)
                if yt:
                    update["youtube_url"] = yt

            supabase.table("kb_articles").update(update).eq("id", row["id"]).execute()
            reviewed += 1
        except BudgetExhausted:
            break
        except Exception as exc:
            logger.exception("review failed for %s: %s", row.get("id"), exc)
        finally:
            if on_progress:
                on_progress(reviewed + rejected, len(rows))

    return {"mode": "slow", "reviewed": reviewed, "rejected": rejected, "candidates": len(rows)}
