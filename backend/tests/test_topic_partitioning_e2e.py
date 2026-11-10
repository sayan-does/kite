"""End-to-end verification tests for Topic-Isolated Feeds and Partitioning."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.auth import get_current_user_id
from app.collectors.base import CollectedItem
from app.config import settings
from app.main import app
from app.services.ranking import get_min_relevance_for_adapter, topic_relevance, compute_score
from app.services.feed_pipeline import _persist_items
from app.services.tag_validator import validate_untagged_articles
from scripts.backfill_partitions import backfill_partitions


@pytest.fixture(autouse=True)
def override_auth():
    app.dependency_overrides[get_current_user_id] = lambda: "test-user-e2e"
    yield
    app.dependency_overrides.pop(get_current_user_id, None)


def test_e2e_collector_relevance_thresholds():
    """Verify collector-specific relevance thresholds."""
    assert get_min_relevance_for_adapter("hn") == 0.6
    assert get_min_relevance_for_adapter("search") == 0.6
    assert get_min_relevance_for_adapter("rss") == 0.4
    assert get_min_relevance_for_adapter("papers") == 0.3


@pytest.mark.asyncio
async def test_e2e_relevance_filtering_in_persistence():
    """Verify items below collector-specific thresholds are dropped."""
    # Item for HN collector with marginal relevance (< 0.6)
    hn_item = CollectedItem(
        title="General discussion on engineering culture",
        snippet="teamwork and meetings",
        topic="Frontend",
        source_adapter="hn",
        url="https://news.ycombinator.com/item?id=1",
    )
    # Item for Papers collector with low relevance (0.3 threshold)
    paper_item = CollectedItem(
        title="Deep neural networks for vision transformers",
        snippet="benchmarking transformer models",
        topic="AI/ML",
        source_adapter="papers",
        url="https://arxiv.org/abs/2601.12345",
    )

    with patch("app.services.feed_pipeline.supabase") as mock_sb:
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        mock_sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "1"}]

        # topic_relevance for hn_item on "Frontend" is low (< 0.6)
        res = await _persist_items([hn_item, paper_item])
        # hn_item should be skipped due to relevance threshold (0.6)
        # paper_item has relevant keywords ("neural", "transformer", "models") for AI/ML and passes
        assert res["skipped_irrelevant"] >= 1


def test_e2e_feed_api_topic_enforcement():
    """Verify /feed rejects empty tag and returns single or multi-topic feeds."""
    client = TestClient(app, raise_server_exceptions=False)

    # 1. Calling /feed without tag returns 400
    r_empty = client.get("/feed")
    assert r_empty.status_code == 400
    assert "select one or multiple topics" in r_empty.json()["detail"]

    # 2. Calling with single tag returns single feed articles
    with patch("app.routers.feed._disabled_citation_types", return_value=set()), \
         patch("app.routers.feed._kb_feed_page") as mock_page:
        mock_page.return_value = {
            "articles": [{"id": "a1", "title": "React 19", "topic": "Frontend"}],
            "page": 1,
            "has_next": False,
        }
        r_single = client.get("/feed?tag=Frontend")
        assert r_single.status_code == 200
        assert "articles" in r_single.json()
        assert r_single.json()["articles"][0]["title"] == "React 19"

    # 3. Calling with multiple topics returns grouped feeds structure
    with patch("app.routers.feed._disabled_citation_types", return_value=set()), \
         patch("app.routers.feed._kb_feed_page") as mock_page:
        def side_effect(uid, topic, page, disabled, include_body=False):
            return {
                "articles": [{"id": f"{topic}-1", "title": f"Top article for {topic}", "topic": topic}],
                "page": page,
                "has_next": False,
            }
        mock_page.side_effect = side_effect

        r_multi = client.get("/feed?tag=Frontend,AI/ML")
        assert r_multi.status_code == 200
        data = r_multi.json()
        assert "feeds" in data
        assert len(data["feeds"]) == 2
        assert data["feeds"][0]["topic"] == "Frontend"
        assert data["feeds"][1]["topic"] == "AI/ML"


@pytest.mark.asyncio
async def test_e2e_tag_validator_flow():
    """Verify untagged NULL articles are classified and assigned tag_id."""
    mock_client = MagicMock()
    mock_client.ainvoke = AsyncMock(return_value=MagicMock(
        content='{"tag_id": 3, "confidence": "high", "reason": "Machine learning paper"}'
    ))

    pending_article = {
        "id": "unvalidated-1",
        "title": "Scaling Vision Transformers",
        "topic": "General",
        "topic_kind": "interest",
        "validation_attempts": 0,
        "url": "https://example.com/vit",
    }

    mock_table = MagicMock()
    # Query pending articles
    mock_table.select.return_value.eq.return_value.eq.return_value.or_.return_value.limit.return_value.execute.return_value.data = [pending_article]
    # Query tags
    mock_table.select.return_value.execute.return_value.data = [
        {"id": 1, "name": "Frontend"},
        {"id": 3, "name": "AI/ML"},
    ]

    updated_rows = []
    def fake_update(data):
        updated_rows.append(data)
        return MagicMock(eq=lambda col, val: MagicMock(execute=lambda: MagicMock(data=[data])))
    mock_table.update = fake_update

    with patch("app.services.tag_validator.for_role", return_value=mock_client), \
         patch("app.services.tag_validator._get_articles_table", return_value="kb_articles_partitioned"), \
         patch("app.services.tag_validator.supabase.table", return_value=mock_table), \
         patch("app.services.tag_validator.fetch_single_article", new_callable=AsyncMock, return_value="ViT paper content"):

        res = await validate_untagged_articles()
        assert res["validated"] == 1
        assert res["retries"] == 0
        assert res["rejected"] == 0
        assert len(updated_rows) == 1
        assert updated_rows[0]["tag_id"] == 3
        assert updated_rows[0]["validation_status"] == "validated"


@pytest.mark.asyncio
async def test_e2e_backfill_partitions_logic():
    """Verify backfill partition logic sets validation_status properly."""
    raw_articles = [
        {"id": "a-null-interest", "tag_id": None, "topic_kind": "interest", "title": "Untagged"},
        {"id": "a-tagged", "tag_id": 1, "topic_kind": "interest", "title": "Frontend Post"},
        {"id": "a-stack", "tag_id": None, "topic_kind": "stack", "title": "React 19"},
    ]

    mock_supabase = MagicMock()
    # First batch returns articles, second returns empty list to terminate loop
    mock_supabase.table.return_value.select.return_value.order.return_value.range.return_value.execute.side_effect = [
        MagicMock(data=raw_articles),
        MagicMock(data=[]),
    ]

    inserted_rows = []
    def fake_insert(row):
        inserted_rows.append(row)
        return MagicMock(execute=lambda: MagicMock(data=[row]))
    mock_supabase.table.return_value.insert = fake_insert

    with patch("scripts.backfill_partitions.supabase", mock_supabase):
        result = await backfill_partitions(batch_size=10)
        assert result["total"] == 3
        assert result["errors"] == 0
        # Untagged interest article marked pending_validation
        assert inserted_rows[0]["validation_status"] == "pending_validation"
        # Tagged article marked validated
        assert inserted_rows[1]["validation_status"] == "validated"
        # Stack article marked validated
        assert inserted_rows[2]["validation_status"] == "validated"
