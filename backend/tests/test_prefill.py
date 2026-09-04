"""Prefill selects the categories that are empty or stale, and skips the rest."""

from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.services import prefill


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


@pytest.fixture
def prefill_thresholds(monkeypatch):
    monkeypatch.setattr(settings, "PREFILL_TARGET_ARTICLES", 3)
    monkeypatch.setattr(settings, "PREFILL_STALE_HOURS", 12)


def _stub_articles(monkeypatch, rows: list[dict]):
    class _Query:
        def select(self, *_a, **_k):
            return self

        def eq(self, *_a, **_k):
            return self

        def in_(self, *_a, **_k):
            return self

        def order(self, *_a, **_k):
            return self

        def execute(self):
            return type("Resp", (), {"data": rows})()

    monkeypatch.setattr(prefill.supabase, "table", lambda _name: _Query())


def test_all_categories_returns_the_seeded_names():
    names = prefill.all_category_names()
    assert set(names) == {
        "Frontend",
        "Backend",
        "AI/ML",
        "DevOps",
        "Security",
        "Automation",
        "Programming Languages",
    }


def test_no_categories_needs_nothing():
    assert prefill.categories_needing_fill([]) == []


def test_thin_category_needs_filling(monkeypatch, prefill_thresholds):
    _stub_articles(monkeypatch, [
        {"topic": "Frontend", "collected_at": _iso(1)},
        {"topic": "Frontend", "collected_at": _iso(2)},
    ])
    assert prefill.categories_needing_fill(["Frontend"]) == ["Frontend"]


def test_empty_category_needs_filling(monkeypatch, prefill_thresholds):
    _stub_articles(monkeypatch, [])
    assert prefill.categories_needing_fill(["Automation"]) == ["Automation"]


def test_warm_recent_category_is_skipped(monkeypatch, prefill_thresholds):
    _stub_articles(monkeypatch, [
        {"topic": "Frontend", "collected_at": _iso(1)},
        {"topic": "Frontend", "collected_at": _iso(2)},
        {"topic": "Frontend", "collected_at": _iso(3)},
    ])
    assert prefill.categories_needing_fill(["Frontend"]) == []


def test_stale_category_needs_filling_despite_enough_articles(monkeypatch, prefill_thresholds):
    # Volume alone is not freshness: a category nobody has collected for in a
    # day is still a cold start for the reader.
    _stub_articles(monkeypatch, [
        {"topic": "DevOps", "collected_at": _iso(40)},
        {"topic": "DevOps", "collected_at": _iso(50)},
        {"topic": "DevOps", "collected_at": _iso(60)},
    ])
    assert prefill.categories_needing_fill(["DevOps"]) == ["DevOps"]


def test_fetched_at_is_used_when_collected_at_is_missing(monkeypatch, prefill_thresholds):
    _stub_articles(monkeypatch, [
        {"topic": "Security", "collected_at": None, "fetched_at": _iso(1)},
        {"topic": "Security", "collected_at": None, "fetched_at": _iso(2)},
        {"topic": "Security", "collected_at": None, "fetched_at": _iso(3)},
    ])
    assert prefill.categories_needing_fill(["Security"]) == []


def test_untimestamped_rows_count_as_stale(monkeypatch, prefill_thresholds):
    _stub_articles(monkeypatch, [
        {"topic": "Backend", "collected_at": None, "fetched_at": None},
        {"topic": "Backend", "collected_at": None, "fetched_at": None},
        {"topic": "Backend", "collected_at": None, "fetched_at": None},
    ])
    assert prefill.categories_needing_fill(["Backend"]) == ["Backend"]


def test_only_thin_categories_are_selected(monkeypatch, prefill_thresholds):
    _stub_articles(monkeypatch, [
        {"topic": "Frontend", "collected_at": _iso(1)},
        {"topic": "Frontend", "collected_at": _iso(1)},
        {"topic": "Frontend", "collected_at": _iso(1)},
        {"topic": "Automation", "collected_at": _iso(1)},
    ])
    assert prefill.categories_needing_fill(["Frontend", "Automation"]) == ["Automation"]


@pytest.mark.asyncio
async def test_prefill_is_a_no_op_when_feed_v3_is_off(monkeypatch):
    monkeypatch.setattr(settings, "FEED_V3", False)
    result = await prefill.prefill_all_categories()
    assert result["filled"] == []
    assert "skipped" in result


@pytest.mark.asyncio
@pytest.mark.enable_feed_v3
async def test_prefill_runs_each_needed_category_separately(monkeypatch):
    monkeypatch.setattr(settings, "FEED_V3", True)
    monkeypatch.setattr(prefill, "all_category_names", lambda: ["Frontend", "Automation"])
    monkeypatch.setattr(prefill, "categories_needing_fill", lambda names: ["Automation"])

    fast_calls: list[dict] = []
    slow_calls: list[dict] = []

    async def fake_fast(*, topics=None, force=False, allow_search_backfill=False, job_id=None):
        fast_calls.append({"topics": topics, "force": force, "backfill": allow_search_backfill})
        return {"inserted": 2}

    async def fake_slow(*, topics=None, job_id=None):
        slow_calls.append({"topics": topics})
        return {"reviewed": 2}

    monkeypatch.setattr("app.services.feed_pipeline.run_fast_cycle", fake_fast)
    monkeypatch.setattr("app.services.feed_pipeline.run_slow_cycle", fake_slow)

    result = await prefill.prefill_all_categories()

    assert result["filled"] == ["Automation"]
    assert fast_calls == [{"topics": ["Automation"], "force": True, "backfill": True}]
    assert slow_calls == [{"topics": ["Automation"]}]


@pytest.mark.asyncio
@pytest.mark.enable_feed_v3
async def test_prefill_force_ignores_the_freshness_check(monkeypatch):
    monkeypatch.setattr(settings, "FEED_V3", True)
    monkeypatch.setattr(prefill, "all_category_names", lambda: ["Frontend", "Automation"])

    async def fake_fast(*, topics=None, **_kwargs):
        return {"inserted": 1}

    async def fake_slow(**_kwargs):
        return {"reviewed": 1}

    monkeypatch.setattr("app.services.feed_pipeline.run_fast_cycle", fake_fast)
    monkeypatch.setattr("app.services.feed_pipeline.run_slow_cycle", fake_slow)

    result = await prefill.prefill_all_categories(force=True)
    assert result["filled"] == ["Frontend", "Automation"]


@pytest.mark.asyncio
@pytest.mark.enable_feed_v3
async def test_one_failing_category_does_not_starve_the_others(monkeypatch):
    monkeypatch.setattr(settings, "FEED_V3", True)
    monkeypatch.setattr(prefill, "all_category_names", lambda: ["Frontend", "Automation"])
    monkeypatch.setattr(
        prefill, "categories_needing_fill", lambda names: ["Frontend", "Automation"]
    )

    async def fake_fast(*, topics=None, **_kwargs):
        if topics == ["Frontend"]:
            raise RuntimeError("source unreachable")
        return {"inserted": 1}

    async def fake_slow(**_kwargs):
        return {"reviewed": 1}

    monkeypatch.setattr("app.services.feed_pipeline.run_fast_cycle", fake_fast)
    monkeypatch.setattr("app.services.feed_pipeline.run_slow_cycle", fake_slow)

    result = await prefill.prefill_all_categories()
    assert result["failed"] == ["Frontend"]
    assert result["filled"] == ["Automation"]
