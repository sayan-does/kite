from app.collectors.base import CollectedItem
from app.services.feed_pipeline import MIN_RELEVANCE
from app.services.ranking import (
    _TOPIC_ALIASES,
    compute_score,
    dedup_items,
    title_similarity,
    topic_relevance,
)


def test_title_similarity_high_for_near_duplicates():
    assert title_similarity("React 19 ships", "React 19 ships today") > 0.7


def test_dedup_merges_similar_titles():
    a = CollectedItem(title="React 19 released", url="https://a.com/1", topic="Frontend", source_weight=1.0)
    b = CollectedItem(title="React 19 released", url="https://b.com/2", topic="Frontend", source_weight=1.0)
    out = dedup_items([a, b])
    assert len(out) == 1


def test_version_conflict_not_deduped():
    a = CollectedItem(title="React 19.1 patch", url="https://a.com/1", topic="Frontend", source_weight=1.0)
    b = CollectedItem(title="React 19.2 release", url="https://b.com/2", topic="Frontend", source_weight=1.0)
    out = dedup_items([a, b])
    assert len(out) == 2


def test_topic_relevance_filters_off_topic():
    item = CollectedItem(title="Random cooking tips", url="https://x.com", snippet="pasta", topic="Frontend")
    assert topic_relevance(item) < 0.2
    assert compute_score(item) == 0.0


def test_topic_aliases_cover_exactly_the_seven_categories():
    assert set(_TOPIC_ALIASES) == {
        "frontend",
        "backend",
        "ai/ml",
        "devops",
        "security",
        "automation",
        "programming languages",
    }


def test_automation_items_pass_relevance_without_the_literal_word():
    # Most n8n and Playwright headlines never say "automation", so the aliases
    # are what keeps them above MIN_RELEVANCE.
    for title in (
        "Building a Playwright test suite from scratch",
        "New n8n nodes for webhook triggers",
        "Scraping product data at scale",
    ):
        item = CollectedItem(title=title, url="https://x.com", topic="Automation")
        assert topic_relevance(item) >= MIN_RELEVANCE, title
        assert compute_score(item) > 0.0, title


def test_every_category_clears_min_relevance_on_a_single_alias_hit():
    """A one-word match must be enough, or a category collects almost nothing.

    topic_relevance divides by the alias count, so adding aliases to one
    category silently raises its bar. This pins that invariant for all seven.
    """
    for topic, aliases in _TOPIC_ALIASES.items():
        alias = sorted(aliases)[0]
        item = CollectedItem(title=f"A post about {alias}", url="https://x.com", topic=topic)
        assert topic_relevance(item) >= MIN_RELEVANCE, f"{topic} via {alias}"


def test_off_topic_item_still_rejected_for_automation():
    item = CollectedItem(
        title="Random cooking tips", url="https://x.com", snippet="pasta", topic="Automation"
    )
    assert compute_score(item) == 0.0
