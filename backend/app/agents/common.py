import asyncio
import logging

from langchain_groq import ChatGroq

from app.config import settings

logger = logging.getLogger(__name__)
groq_client = ChatGroq(model=settings.GROQ_MODEL, api_key=settings.GROQ_API_KEY)


async def search(query: str) -> list[dict]:
    results = await _search_searxng(query)
    if results:
        return results
    logger.warning("SearxNG unavailable, falling back to DuckDuckGo")
    return await _search_duckduckgo(query)


async def _search_searxng(query: str) -> list[dict] | None:
    import httpx

    searx_url = settings.SEARX_URL.rstrip("/")
    params = {"q": query, "format": "json", "language": "en", "categories": "news"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{searx_url}/search", params=params)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            return [
                {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
                for r in results
            ]
    except Exception as e:
        logger.debug("SearxNG failed: %s", e)
        return None


async def _search_duckduckgo(query: str) -> list[dict]:
    from duckduckgo_search import DDGS

    def sync_search(q: str) -> list[dict]:
        ddgs = DDGS()
        results = list(ddgs.text(q, max_results=10))
        return [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in results
        ]

    try:
        return await asyncio.to_thread(sync_search, query)
    except Exception as e:
        logger.warning("DuckDuckGo search failed: %s", e)
        return []


MAX_ARTICLE_TEXT = 10_000


async def fetch_article_text(url: str) -> str | None:
    import httpx
    from bs4 import BeautifulSoup
    from readability import Document

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
        doc = Document(html)
        soup = BeautifulSoup(doc.summary(), "html.parser")
        text = soup.get_text(separator="\n", strip=True)
        if not text:
            return None
        return text[:MAX_ARTICLE_TEXT]
    except Exception as e:
        logger.debug("fetch_article_text failed for %s: %s", url, e)
        return None
