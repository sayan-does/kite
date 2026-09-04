"""Cold-category first fill: validator bypass, HN topic queries, poll merging."""

import time
import uuid

import httpx
import pytest

from app.collectors.base import CollectedItem, ConditionalResponse
from app.collectors.hn import HN_SINCE_DAYS, collect_hn
from app.collectors.rss import collect_rss
from app.services.feed_pipeline import (
    _cold_topics,
    _collect_hn_for_topics,
    _update_feed_poll,
)

RSS_BODY = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>React Blog</title>
  <item>
    <title>React 19.3 released</title>
    <link>https://react.dev/blog/19-3</link>
    <description>A new React release for frontend apps.</description>
  </item>
</channel></rss>"""


def _rss_feed() -> dict:
    return {
        "id": "feed-1",
        "url": "https://react.dev/rss.xml",
        "topic": "Frontend",
        "tag_id": 1,
        "weight": 1.4,
        "etag": 'W/"cached-etag"',
        "last_modified": "Wed, 01 Jan 2025 00:00:00 GMT",
    }


@pytest.mark.asyncio
async def test_cold_topic_rss_fetch_drops_validators(monkeypatch):
    captured: dict = {}

    async def fake_conditional_get(url, *, etag=None, last_modified=None, timeout=20.0):
        captured["etag"] = etag
        captured["last_modified"] = last_modified
        return ConditionalResponse(status=200, body=RSS_BODY)

    monkeypatch.setattr("app.collectors.rss.conditional_get", fake_conditional_get)

    items, poll = await collect_rss(_rss_feed(), ignore_cache=True)

    assert captured == {"etag": None, "last_modified": None}
    assert [i.title for i in items] == ["React 19.3 released"]
    assert poll["last_status"] == 200


@pytest.mark.asyncio
async def test_warm_topic_rss_fetch_keeps_validators(monkeypatch):
    captured: dict = {}

    async def fake_conditional_get(url, *, etag=None, last_modified=None, timeout=20.0):
        captured["etag"] = etag
        captured["last_modified"] = last_modified
        return ConditionalResponse(status=304, not_modified=True)

    monkeypatch.setattr("app.collectors.rss.conditional_get", fake_conditional_get)

    items, _poll = await collect_rss(_rss_feed())

    assert captured["etag"] == 'W/"cached-etag"'
    assert captured["last_modified"] == "Wed, 01 Jan 2025 00:00:00 GMT"
    assert items == []


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, captured: dict, payload: dict):
        self._captured = captured
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False

    async def get(self, url, params=None):
        self._captured["url"] = url
        self._captured["params"] = params
        return _FakeResponse(self._payload)


def _patch_hn_http(monkeypatch, captured: dict, payload: dict) -> None:
    class _FakeHttpx:
        HTTPError = httpx.HTTPError

        @staticmethod
        def AsyncClient(**_kwargs):
            return _FakeAsyncClient(captured, payload)

    monkeypatch.setattr("app.collectors.hn.httpx", _FakeHttpx)


@pytest.mark.asyncio
async def test_hn_queries_topic_and_recent_window(monkeypatch):
    captured: dict = {}
    payload = {
        "hits": [
            {
                "title": "Vite 8 is out",
                "url": "https://example.com/vite-8",
                "created_at": "2026-09-01T00:00:00.000Z",
                "objectID": "1",
                "points": 240,
                "num_comments": 90,
            }
        ]
    }
    _patch_hn_http(monkeypatch, captured, payload)

    before = int(time.time())
    items, poll = await collect_hn(
        {"id": "hn-row", "kind": "hn", "topic": None, "tag_id": None, "weight": 1.0},
        topic_filter="Frontend",
        tag_id=1,
    )

    params = captured["params"]
    assert params["query"] == "Frontend"

    filters = params["numericFilters"].split(",")
    assert "points>20" in filters
    cutoff = int(next(f for f in filters if f.startswith("created_at_i>")).split(">")[1])
    expected = before - HN_SINCE_DAYS * 86400
    assert abs(cutoff - expected) <= 5

    assert poll["last_status"] == 200
    assert len(items) == 1
    assert items[0].topic == "Frontend"
    assert items[0].tag_id == 1


@pytest.mark.asyncio
async def test_hn_without_topic_omits_query(monkeypatch):
    captured: dict = {}
    _patch_hn_http(monkeypatch, captured, {"hits": []})

    await collect_hn({"id": "hn-row", "kind": "hn", "topic": None, "tag_id": None})

    assert "query" not in captured["params"]


@pytest.mark.asyncio
async def test_hn_expands_once_per_target_topic(monkeypatch):
    calls: list[tuple] = []

    async def fake_collect(feed, *, ignore_cache=False, topic_filter=None, tag_id=None):
        calls.append((topic_filter, tag_id))
        item = CollectedItem(
            title=f"{topic_filter} story",
            url=f"https://example.com/{topic_filter}",
            topic=topic_filter,
            tag_id=tag_id,
            source_adapter="hn",
        )
        return [item], {"last_polled_at": "now()", "last_status": 200}

    monkeypatch.setattr("app.services.feed_pipeline._collect_one_feed", fake_collect)

    items, poll = await _collect_hn_for_topics(
        {"id": "hn-row", "kind": "hn"},
        [("Frontend", 1), ("Automation", 11)],
    )

    assert calls == [("Frontend", 1), ("Automation", 11)]
    assert [i.topic for i in items] == ["Frontend", "Automation"]
    assert poll["last_status"] == 200
    assert poll["last_success_at"] == "now()"


@pytest.mark.asyncio
async def test_hn_expansion_reports_failure_when_all_topics_fail(monkeypatch):
    async def fake_collect(feed, *, ignore_cache=False, topic_filter=None, tag_id=None):
        return [], {"last_polled_at": "now()", "last_status": 0}

    monkeypatch.setattr("app.services.feed_pipeline._collect_one_feed", fake_collect)

    items, poll = await _collect_hn_for_topics(
        {"id": "hn-row", "kind": "hn", "consecutive_failures": 1},
        [("Frontend", 1)],
    )

    assert items == []
    assert poll["consecutive_failures"] == 2
    assert "last_success_at" not in poll


def test_cold_topics_reports_topic_with_no_active_articles():
    missing = f"zz-no-such-topic-{uuid.uuid4().hex[:8]}"
    assert _cold_topics([missing]) == {missing}


def test_cold_topics_empty_input_is_noop():
    assert _cold_topics([]) == set()


def test_update_feed_poll_skips_virtual_feeds():
    # Virtual search feeds carry no source_feeds row, so this must not write.
    _update_feed_poll(None, {"last_polled_at": "now()", "last_status": 200})
