"""TinyFish Fetch API integration for batch article fetching."""

import asyncio
import logging
from typing import Dict, Optional

from app.config import settings
from app.services.tinyfish_budget import tinyfish_budget
from app.agents.common import fetch_article_text

logger = logging.getLogger(__name__)


async def batch_fetch_articles(urls: list[str]) -> Dict[str, Optional[str]]:
    """Fetch multiple URLs via TinyFish, with fallback to fetch_article_text."""
    if not urls:
        return {}
    
    # Check if TinyFish is enabled
    if not settings.TINYFISH_ENABLED or not settings.TINYFISH_API_KEY:
        return await _fallback_fetch_all(urls)
    
    results = {}
    chunks = [urls[i:i+10] for i in range(0, len(urls), 10)]
    sem = asyncio.Semaphore(settings.TINYFISH_BATCH_CONCURRENCY)
    
    async def _fetch_chunk(chunk: list[str]) -> Dict[str, Optional[str]]:
        async with sem:
            if not tinyfish_budget.try_spend_fetch(len(chunk)):
                logger.info(f"TinyFish budget exhausted, falling back for {len(chunk)} URLs")
                return await _fallback_fetch_chunk(chunk)
            
            try:
                from tinyfish import TinyFish
                client = TinyFish(api_key=settings.TINYFISH_API_KEY)
                response = await asyncio.to_thread(
                    client.fetch.get_contents,
                    urls=chunk,
                    format="markdown"
                )
                chunk_results = {}
                for result in response.results:
                    chunk_results[result.url] = result.text
                for error in response.errors:
                    logger.warning(f"TinyFish fetch failed for {error.url}: {error.error}")
                    chunk_results[error.url] = await fetch_article_text(error.url)
                return chunk_results
            except Exception as exc:
                logger.exception(f"TinyFish batch request failed: {exc}")
                return await _fallback_fetch_chunk(chunk)
    
    async def _fallback_fetch_chunk(chunk: list[str]) -> Dict[str, Optional[str]]:
        tasks = [fetch_article_text(url) for url in chunk]
        contents = await asyncio.gather(*tasks)
        return dict(zip(chunk, contents))
    
    async def _fallback_fetch_all(urls: list[str]) -> Dict[str, Optional[str]]:
        tasks = [fetch_article_text(url) for url in urls]
        contents = await asyncio.gather(*tasks)
        return dict(zip(urls, contents))
    
    # Process all chunks concurrently
    chunk_results = await asyncio.gather(*[_fetch_chunk(chunk) for chunk in chunks])
    for chunk_result in chunk_results:
        results.update(chunk_result)
    
    return results


async def fetch_single_article(url: str) -> Optional[str]:
    """Fetch a single article URL using TinyFish or fallback."""
    results = await batch_fetch_articles([url])
    return results.get(url)