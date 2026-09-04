"""Shared article enrichment: scrape + LLM summarize for feed cards."""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage

from app.agents.common import fetch_article_text
from app.agents.discovery.nodes import _classify_url
from app.services.extractive import clean_snippet, extractive_one_liner
from app.services.llm import BudgetExhausted, budget, for_role, parse_json_response

logger = logging.getLogger(__name__)

MIN_ARTICULATED_LEN = 100


def needs_enrichment(article: dict) -> bool:
    """True when the card lacks a substantive AI-written body."""
    tier = article.get("tier") or "raw"
    body = (article.get("body") or "").strip()
    one_liner = (article.get("one_liner") or article.get("summary") or "").strip()
    if tier == "raw":
        return True
    if len(body) < MIN_ARTICULATED_LEN:
        return True
    if body == one_liner:
        return True
    return False


async def summarize_article(article: dict, *, use_budget: bool = True) -> dict | None:
    """Fetch page text and produce one_liner + full_summary body."""
    client = for_role("summarize")
    url = article.get("url") or ""
    content = await fetch_article_text(url) if url else None
    raw_body = clean_snippet(article.get("body") or "")
    content = content or raw_body or clean_snippet(article.get("summary") or "")
    if len(content.strip()) < 20:
        return None

    source_type = article.get("source_type") or _classify_url(url)
    prompt = (
        f"Summarize for topic '{article.get('topic')}'.\n\n"
        f"Title: {article.get('title')}\nURL: {url}\n\nContent:\n{content[:8000]}\n\n"
        'JSON only: {"one_liner":"...","full_summary":"...","source_type":"blog|github|official_docs|youtube"}'
    )
    if use_budget and not budget.try_spend(1200):
        raise BudgetExhausted("summarize budget exhausted")

    if client is None:
        return None
    try:
        resp = await client.ainvoke([HumanMessage(content=prompt)])
        parsed = parse_json_response(resp.content or "")
        if not parsed:
            return None
        one_liner = parsed.get("one_liner", "")
        full_summary = parsed.get("full_summary", "")
        if not one_liner or not full_summary:
            return None
        st = parsed.get("source_type", source_type)
        if st not in ("official_docs", "github", "blog", "youtube"):
            st = source_type
        return {"one_liner": one_liner, "body": full_summary, "summary": one_liner, "source_type": st}
    except BudgetExhausted:
        raise
    except Exception as exc:
        logger.warning("summarize failed: %s", exc)
        return None


def fallback_payload(article: dict) -> dict:
    """Best-effort body when LLM is unavailable."""
    title = (article.get("title") or "").strip()
    snippet = clean_snippet(article.get("body") or article.get("summary") or "")
    one_liner = extractive_one_liner(title, snippet)
    body = snippet or one_liner
    return {
        "one_liner": one_liner,
        "summary": one_liner,
        "body": body,
    }
