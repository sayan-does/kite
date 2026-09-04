"""arXiv and Hugging Face papers collector."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from app.collectors.base import CollectedItem, conditional_get, parse_datetime

ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}


def _parse_arxiv_atom(body: bytes, feed: dict) -> list[CollectedItem]:
    root = ET.fromstring(body)
    items: list[CollectedItem] = []
    for entry in root.findall("a:entry", ATOM_NS):
        title = (entry.findtext("a:title", default="", namespaces=ATOM_NS) or "").strip()
        link_el = entry.find("a:link[@rel='alternate']", ATOM_NS) or entry.find("a:id", ATOM_NS)
        url = link_el.get("href") if link_el is not None and link_el.get("href") else (link_el.text if link_el is not None else "")
        summary = (entry.findtext("a:summary", default="", namespaces=ATOM_NS) or "")[:500]
        published = parse_datetime(entry.findtext("a:published", default="", namespaces=ATOM_NS))
        if title and url:
            items.append(
                CollectedItem(
                    title=title.replace("\n", " "),
                    url=url.strip(),
                    snippet=summary.replace("\n", " "),
                    published_at=published,
                    topic=feed.get("topic"),
                    tag_id=feed.get("tag_id"),
                    source_adapter="papers",
                    source_weight=float(feed.get("weight") or 1.0),
                    feed_id=feed.get("id"),
                    signals={"paper": True},
                )
            )
    return items


async def _parse_hf_daily(feed: dict) -> list[CollectedItem]:
    url = feed["url"]
    async with httpx.AsyncClient(timeout=25) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    items: list[CollectedItem] = []
    for paper in data if isinstance(data, list) else data.get("papers", []):
        p = paper.get("paper") or paper
        title = (p.get("title") or "").strip()
        paper_url = p.get("url") or p.get("id") or ""
        if paper_url and not paper_url.startswith("http"):
            paper_url = f"https://huggingface.co/papers/{paper_url}"
        if not title or not paper_url:
            continue
        items.append(
            CollectedItem(
                title=title,
                url=paper_url,
                snippet=(p.get("summary") or "")[:500],
                published_at=parse_datetime(p.get("publishedAt")),
                topic=feed.get("topic"),
                tag_id=feed.get("tag_id"),
                source_adapter="papers",
                source_weight=float(feed.get("weight") or 1.0),
                feed_id=feed.get("id"),
                signals={"paper": True, "hf": True},
            )
        )
    return items


async def collect_papers(feed: dict, *, ignore_cache: bool = False) -> tuple[list[CollectedItem], dict]:
    url = feed["url"]
    poll_update = {"last_polled_at": "now()", "last_status": 0}

    if "huggingface.co/api/daily_papers" in url:
        try:
            items = await _parse_hf_daily(feed)
            poll_update.update({"last_status": 200, "consecutive_failures": 0, "last_success_at": "now()"})
            return items, poll_update
        except Exception:
            poll_update["consecutive_failures"] = feed.get("consecutive_failures", 0) + 1
            return [], poll_update

    resp = await conditional_get(
        url,
        etag=None if ignore_cache else feed.get("etag"),
        last_modified=None if ignore_cache else feed.get("last_modified"),
    )
    poll_update["last_status"] = resp.status
    poll_update["etag"] = resp.etag
    poll_update["last_modified"] = resp.last_modified

    if resp.not_modified:
        poll_update["consecutive_not_modified"] = feed.get("consecutive_not_modified", 0) + 1
        return [], poll_update

    if resp.status != 200 or not resp.body:
        poll_update["consecutive_failures"] = feed.get("consecutive_failures", 0) + 1
        return [], poll_update

    items = _parse_arxiv_atom(resp.body, feed)
    poll_update.update({"consecutive_failures": 0, "last_success_at": "now()"})
    return items, poll_update
