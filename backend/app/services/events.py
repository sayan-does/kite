"""Tech-events source: fetch + parse upcoming conferences/events.

Kept out of the kb_articles feed pipeline on purpose — events are calendar
entities, not articles. Served on-demand via /events with a small in-process
TTL cache, so the feature needs no DB migration. parse_events() is pure and
unit-tested; fetch_tech_events() wraps it with HTTP + caching.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import httpx

# developers.events publishes a free, no-auth JSON of tech conferences.
DEFAULT_EVENTS_URL = "https://developers.events/all-events.json"
_CACHE_TTL = 3600.0
_cache: dict[str, tuple[float, list[dict]]] = {}


def _coerce_date(value: Any) -> str | None:
    """Return an ISO-8601 UTC string, accepting epoch, ISO, or [start, end]."""
    if value is None or value == "":
        return None
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            return None
    return None


def _location(ev: dict) -> str:
    if ev.get("online") or ev.get("isOnline"):
        return "Online"
    bits = [str(ev.get(k)) for k in ("city", "country", "location") if ev.get(k)]
    return ", ".join(dict.fromkeys(bits)) if bits else ""


def parse_events(data: Any, *, now: datetime | None = None, limit: int = 100) -> list[dict]:
    """Normalize varied conference-JSON shapes into sorted upcoming events.

    Tolerant of key variants: name/title, url/hyperlink, startDate/start/date,
    endDate/end. Drops events already past (end < now) and those missing a start.
    """
    now = now or datetime.now(timezone.utc)
    raw = data if isinstance(data, list) else (data.get("events") if isinstance(data, dict) else [])
    out: list[dict] = []
    for ev in raw or []:
        if not isinstance(ev, dict):
            continue
        title = (ev.get("name") or ev.get("title") or "").strip()
        url = (ev.get("url") or ev.get("hyperlink") or ev.get("link") or "").strip()
        start = _coerce_date(ev.get("startDate") or ev.get("start") or ev.get("date"))
        if not title or not start:
            continue
        end = _coerce_date(ev.get("endDate") or ev.get("end")) or start
        # Skip events that already ended.
        try:
            if datetime.fromisoformat(end) < now:
                continue
        except ValueError:
            pass
        out.append(
            {
                "title": title,
                "url": url,
                "start": start,
                "end": end,
                "location": _location(ev),
                "online": bool(ev.get("online") or ev.get("isOnline")),
            }
        )
    out.sort(key=lambda e: e["start"])
    return out[:limit]


async def fetch_tech_events(
    *, url: str = DEFAULT_EVENTS_URL, limit: int = 50, force: bool = False
) -> list[dict]:
    """Fetch + parse upcoming events, cached in-process for _CACHE_TTL seconds."""
    hit = _cache.get(url)
    if hit and not force and (time.monotonic() - hit[0]) < _CACHE_TTL:
        return hit[1][:limit]
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "KiteFeedBot/1.0"})
            resp.raise_for_status()
            events = parse_events(resp.json(), limit=200)
    except (httpx.HTTPError, ValueError):
        # On failure serve stale cache if present, else empty.
        return hit[1][:limit] if hit else []
    _cache[url] = (time.monotonic(), events)
    return events[:limit]
