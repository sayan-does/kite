"""Deterministic collector primitives: canonical URLs and conditional GET."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

# Tracking params stripped during canonicalization. Keep in sync with
# migrations/0009_feed_v3.sql canonicalize_url_sql().
STRIP_QUERY_KEYS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_name", "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid",
    "igshid", "ref", "ref_src", "source", "amp", "spm", "yclid", "_hsenc",
    "_hsmi", "vero_id", "wt_mc", "at_medium", "at_campaign",
})

_domain_last_request: dict[str, float] = {}
_domain_lock = asyncio.Lock()
MIN_DOMAIN_INTERVAL = 1.0


@dataclass
class CollectedItem:
    title: str
    url: str
    snippet: str = ""
    published_at: datetime | None = None
    topic: str | None = None
    tag_id: int | None = None
    topic_kind: str = "interest"
    source_adapter: str = ""
    source_weight: float = 1.0
    feed_id: str | None = None
    signals: dict[str, Any] = field(default_factory=dict)

    @property
    def url_canonical(self) -> str | None:
        return canonicalize_url(self.url)


@dataclass
class ConditionalResponse:
    status: int
    body: bytes | None = None
    etag: str | None = None
    last_modified: str | None = None
    cache_max_age: int | None = None
    not_modified: bool = False


def canonicalize_url(raw: str | None) -> str | None:
    if not raw or not raw.strip():
        return None

    parsed = urlparse(raw.strip())
    scheme = (parsed.scheme or "https").lower()
    netloc = (parsed.hostname or "").lower()
    if not netloc:
        return None
    if netloc.startswith("www."):
        netloc = netloc[4:]

    path = parsed.path or ""
    path = re.sub(r"/amp/?$", "", path, flags=re.IGNORECASE)
    path = re.sub(r"\.amp$", "", path, flags=re.IGNORECASE)
    path = path.rstrip("/") or ""

    kept = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in STRIP_QUERY_KEYS
    ]
    query = urlencode(kept, doseq=True)

    return urlunparse((scheme, netloc, path, "", query, "")).removeprefix(f"{scheme}://")


async def _wait_for_domain(domain: str) -> None:
    async with _domain_lock:
        now = time.monotonic()
        last = _domain_last_request.get(domain, 0.0)
        wait = MIN_DOMAIN_INTERVAL - (now - last)
        if wait > 0:
            await asyncio.sleep(wait)
        _domain_last_request[domain] = time.monotonic()


def _parse_cache_control(value: str | None) -> int | None:
    if not value:
        return None
    for part in value.split(","):
        part = part.strip()
        if part.startswith("max-age="):
            try:
                return int(part.split("=", 1)[1])
            except ValueError:
                return None
    return None


async def conditional_get(
    url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    timeout: float = 20.0,
) -> ConditionalResponse:
    """GET with If-None-Match / If-Modified-Since. Honors 304 and backs off on 429."""
    parsed = urlparse(url)
    domain = (parsed.hostname or "unknown").lower()
    await _wait_for_domain(domain)

    headers = {
        "User-Agent": "KiteFeedBot/1.0 (+https://github.com/kite)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    }
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    backoff = 2.0
    for attempt in range(4):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
        except httpx.HTTPError:
            if attempt == 3:
                return ConditionalResponse(status=0)
            await asyncio.sleep(backoff)
            backoff *= 2
            continue

        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", backoff))
            await asyncio.sleep(retry_after)
            backoff *= 2
            continue

        if resp.status_code == 304:
            return ConditionalResponse(
                status=304,
                etag=resp.headers.get("ETag") or etag,
                last_modified=resp.headers.get("Last-Modified") or last_modified,
                not_modified=True,
            )

        return ConditionalResponse(
            status=resp.status_code,
            body=resp.content if resp.status_code == 200 else None,
            etag=resp.headers.get("ETag"),
            last_modified=resp.headers.get("Last-Modified"),
            cache_max_age=_parse_cache_control(resp.headers.get("Cache-Control")),
        )

    return ConditionalResponse(status=0)


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(value.replace("Z", "+0000"), fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


async def url_is_reachable(url: str, timeout: float = 12.0) -> bool:
    """HEAD then GET fallback — used to drop dead links before persisting."""
    if not url:
        return False
    headers = {"User-Agent": "KiteFeedBot/1.0"}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            head = await client.head(url, headers=headers)
            if head.status_code < 400:
                return True
            get = await client.get(url, headers=headers)
            return get.status_code < 400
    except httpx.HTTPError:
        return False
