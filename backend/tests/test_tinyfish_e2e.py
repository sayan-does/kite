"""End-to-end verification tests for TinyFish Integration."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import settings
from app.services.tinyfish_budget import TinyFishBudget
from app.services.tinyfish_fetch import batch_fetch_articles, fetch_single_article
from app.services.article_enrich import summarize_article
from app.collectors.search import collect_search_backfill
from app.routers.feed import _article_payload
from app.agents.review_graph import run_review_cycle


@pytest.mark.asyncio
async def test_tinyfish_e2e_batch_fetch_and_enrichment():
    """Verify batch fetching articles with TinyFish, enriching with LLM, and extracting key_links."""
    test_urls = [
        "https://example.com/article1",
        "https://example.com/article2",
    ]
    
    mock_tf_response = MagicMock()
    mock_res1 = MagicMock()
    mock_res1.url = test_urls[0]
    mock_res1.text = "# Article 1\nContent for article 1 with link: [Doc](https://docs.example.com/1)"
    mock_res2 = MagicMock()
    mock_res2.url = test_urls[1]
    mock_res2.text = "# Article 2\nContent for article 2 with link: [Repo](https://github.com/example/2)"
    mock_tf_response.results = [mock_res1, mock_res2]
    mock_tf_response.errors = []

    budget = TinyFishBudget()

    with patch("app.services.tinyfish_fetch.settings") as mock_settings, \
         patch("app.services.tinyfish_fetch.tinyfish_budget", budget), \
         patch("tinyfish.TinyFish") as mock_tf_class:
        
        mock_settings.TINYFISH_ENABLED = True
        mock_settings.TINYFISH_API_KEY = "tf-api-key-test"
        mock_settings.TINYFISH_BATCH_CONCURRENCY = 2
        mock_client = MagicMock()
        mock_client.fetch.get_contents.return_value = mock_tf_response
        mock_tf_class.return_value = mock_client

        # 1. Batch fetch articles
        results = await batch_fetch_articles(test_urls)
        assert len(results) == 2
        assert "Article 1" in results[test_urls[0]]
        assert "Article 2" in results[test_urls[1]]
        assert budget.daily_fetch_count == 2

        # 2. Enrich article with prefetched markdown
        article_row = {
            "id": "kb-art-1",
            "title": "Article 1 Title",
            "url": test_urls[0],
            "topic": "Frontend",
            "tier": "raw",
        }

        mock_llm_resp = MagicMock()
        mock_llm_resp.content = (
            '{"one_liner": "Summary 1", "full_summary": "In depth summary 1", '
            '"source_type": "official_docs", '
            '"key_links": [{"title": "Doc", "url": "https://docs.example.com/1"}]}'
        )

        with patch("app.services.article_enrich.for_role") as mock_for_role, \
             patch("app.services.article_enrich.budget") as mock_llm_budget:
            mock_llm_client = MagicMock()
            mock_llm_client.ainvoke = AsyncMock(return_value=mock_llm_resp)
            mock_for_role.return_value = mock_llm_client
            mock_llm_budget.try_spend.return_value = True

            summary = await summarize_article(article_row, prefetched_content=results[test_urls[0]])
            assert summary is not None
            assert summary["one_liner"] == "Summary 1"
            assert summary["body"] == "In depth summary 1"
            assert len(summary["key_links"]) == 1
            assert summary["key_links"][0]["title"] == "Doc"

            # 3. Payload formatting for client
            merged = {**article_row, **summary, "tier": "reviewed"}
            payload = _article_payload(merged, set(), include_body=True)
            assert payload["id"] == "kb-art-1"
            assert payload["body"] == "In depth summary 1"
            assert payload["key_links"] == [{"title": "Doc", "url": "https://docs.example.com/1"}]


@pytest.mark.asyncio
async def test_tinyfish_e2e_search_and_fallback():
    """Verify TinyFish search backfill and fallback to SearXNG/DDG when budget is exhausted."""
    budget = TinyFishBudget()
    # Exhaust search budget
    for _ in range(30):
        budget.try_spend_search()

    feed = {"id": "feed-test", "topic": "Frontend", "tag_id": 1, "weight": 0.8}

    with patch("app.collectors.search.settings") as mock_settings, \
         patch("app.collectors.search.tinyfish_budget", budget), \
         patch("app.collectors.search.search") as mock_searxng:

        mock_settings.TINYFISH_ENABLED = True
        mock_settings.TINYFISH_API_KEY = "test-key"

        mock_searxng.return_value = [
            {"title": "Fallback Result", "url": "https://example.com/fallback", "snippet": "SearXNG snippet"}
        ]

        # Since TinyFish search budget is exhausted (30/30), it should fallback to SearXNG gracefully
        items, poll = await collect_search_backfill(feed, query="Frontend")
        assert len(items) == 1
        assert items[0].title == "Fallback Result"
        assert items[0].source_adapter == "search"
        assert poll["last_status"] == 200
        mock_searxng.assert_called_once()


@pytest.mark.asyncio
async def test_tinyfish_e2e_slow_review_cycle():
    """Verify slow review cycle uses batch fetch for triage-passed candidates."""
    mock_candidates = [
        {"id": "c1", "title": "Good article", "topic": "Frontend", "url": "https://example.com/good", "score": 10},
        {"id": "c2", "title": "Spam article", "topic": "Frontend", "url": "https://example.com/spam", "score": 9},
    ]

    mock_supabase = MagicMock()
    mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = mock_candidates

    # c1 passes triage, c2 is rejected
    async def fake_triage(row):
        return row["id"] == "c1"

    batch_fetched_urls = []

    async def fake_batch_fetch(urls):
        batch_fetched_urls.extend(urls)
        return {urls[0]: "# Good Article Content"}

    async def fake_summarize(row, prefetched_content=None):
        return {
            "one_liner": "Good one-liner",
            "body": "Good summary body",
            "summary": "Good one-liner",
            "source_type": "blog",
            "key_links": [{"title": "Example", "url": "https://example.com"}],
        }

    with patch("app.agents.review_graph.supabase", mock_supabase), \
         patch("app.agents.review_graph._triage", side_effect=fake_triage), \
         patch("app.agents.review_graph.batch_fetch_articles", side_effect=fake_batch_fetch), \
         patch("app.agents.review_graph.summarize_article", side_effect=fake_summarize), \
         patch("app.agents.review_graph.resolve_youtube_url", return_value=None):

        result = await run_review_cycle()
        assert result["reviewed"] == 1
        assert result["rejected"] == 1
        assert result["candidates"] == 2
        # Only the triage-passed article URL should be batch-fetched
        assert batch_fetched_urls == ["https://example.com/good"]
