"""LLM-based tag validation worker for NULL tag_id articles."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from langchain_core.messages import HumanMessage

from app.config import settings
from app.db import supabase
from app.services.llm import for_role, parse_json_response
from app.services.tinyfish_fetch import fetch_single_article

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
RETRY_DELAY_HOURS = 5  # Retry every 5 hours


def _get_articles_table() -> str:
    """Determine whether to use kb_articles_partitioned or kb_articles (post-swap)."""
    try:
        supabase.table("kb_articles_partitioned").select("id").limit(1).execute()
        return "kb_articles_partitioned"
    except Exception:
        return "kb_articles"


async def validate_untagged_articles(batch_size: int = 10) -> dict:
    """Query NULL partition, assign tag_id via LLM, move to correct partition.
    
    Returns dict with validated, retries, rejected counts.
    """
    client = for_role("triage")
    if not client:
        logger.warning("LLM client unavailable for tag validation")
        return {"validated": 0, "retries": 0, "rejected": 0}
    
    table_name = _get_articles_table()
    
    # Fetch pending articles from NULL partition
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RETRY_DELAY_HOURS)
    try:
        rows = (
            supabase.table(table_name)
            .select("id, title, one_liner, summary, body, url, validation_attempts, topic_kind, topic")
            .eq("validation_status", "pending_validation")
            .eq("topic_kind", "interest")
            .or_(f"last_validation_attempt.is.null,last_validation_attempt.lt.{cutoff.isoformat()}")
            .limit(batch_size)
            .execute()
            .data or []
        )
    except Exception as exc:
        logger.warning("Could not query unvalidated articles from %s: %s", table_name, exc)
        return {"validated": 0, "retries": 0, "rejected": 0}
    
    if not rows:
        logger.debug("No pending validation articles found")
        return {"validated": 0, "retries": 0, "rejected": 0}
    
    # Fetch available interest_tags
    tags = supabase.table("interest_tags").select("id, name").execute().data or []
    tag_options = ", ".join([f"{t['name']} (id={t['id']})" for t in tags])
    
    validated = 0
    retries = 0
    rejected = 0
    
    for article in rows:
        attempts = article.get("validation_attempts", 0)
        
        # Check if max attempts reached
        if attempts >= MAX_ATTEMPTS:
            try:
                supabase.table(table_name).update({
                    "validation_status": "rejected",
                    "status": "rejected",
                }).eq("id", article["id"]).execute()
            except Exception as exc:
                logger.warning("Failed to mark article %s as rejected: %s", article["id"], exc)
            rejected += 1
            logger.info(f"Article {article['id']} rejected after {MAX_ATTEMPTS} failed validation attempts")
            continue
        
        # Fetch full content for better context
        try:
            full_content = None
            if article.get("url"):
                full_content = await fetch_single_article(article.get("url"))
        except Exception:
            pass
        
        content = full_content or article.get("body") or article.get("summary") or article.get("one_liner") or ""
        
        # Build LLM prompt with all context
        prompt = (
            f"Assign this article to ONE topic from: {tag_options}\n\n"
            f"Title: {article.get('title')}\n"
            f"URL: {article.get('url')}\n"
            f"Topic: {article.get('topic')}\n"
            f"Snippet: {article.get('one_liner')}\n"
            f"Content: {content[:3000]}\n\n"
            'Respond JSON only: {"tag_id": <int>, "confidence": "high|medium|low", "reason": "<brief reason>"}'
        )
        
        try:
            resp = await client.ainvoke([HumanMessage(content=prompt)])
            parsed = parse_json_response(resp.content or "")
            
            if not parsed or parsed.get("confidence") == "low":
                # Retry later
                supabase.table(table_name).update({
                    "validation_attempts": attempts + 1,
                    "last_validation_attempt": datetime.now(timezone.utc).isoformat(),
                }).eq("id", article["id"]).execute()
                retries += 1
                logger.debug(f"Article {article['id']} low confidence, will retry")
                continue
            
            tag_id = parsed.get("tag_id")
            # Validate tag_id exists in interest_tags
            if not tag_id or not any(t["id"] == tag_id for t in tags):
                raise ValueError(f"Invalid tag_id: {tag_id}")
            
            # Update tag_id - PostgreSQL auto-moves to correct partition
            supabase.table(table_name).update({
                "tag_id": tag_id,
                "validation_status": "validated",
                "validation_attempts": attempts + 1,
                "last_validation_attempt": datetime.now(timezone.utc).isoformat(),
            }).eq("id", article["id"]).execute()
            validated += 1
            logger.info(f"Validated article {article['id']} → tag_id={tag_id}")
            
        except Exception as exc:
            logger.exception(f"Validation failed for {article['id']}: {exc}")
            try:
                supabase.table(table_name).update({
                    "validation_attempts": attempts + 1,
                    "last_validation_attempt": datetime.now(timezone.utc).isoformat(),
                }).eq("id", article["id"]).execute()
            except Exception:
                pass
            retries += 1
    
    result = {"validated": validated, "retries": retries, "rejected": rejected}
    logger.info(f"Tag validation complete: {result}")
    return result


if __name__ == "__main__":
    # For testing/standalone execution
    asyncio.run(validate_untagged_articles(batch_size=20))