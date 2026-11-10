"""Tests for TinyFish Search integration."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.collectors.search import collect_search_backfill, _build_collected_items
from app.collectors.base import CollectedItem


def test_build_collected_items():
    """Test building CollectedItem list from search results."""
    results = [
        {"title": "Article 1", "url": "https://example.com/1", "snippet": "Summary 1"},
        {"title": "Article 2", "url": "https://example.com/2", "snippet": "Summary 2"},
    ]
    feed = {"topic": "Frontend", "tag_id": 1, "id": "feed-1", "weight": 1.0}
    
    items = _build_collected_items(results, feed, "Frontend")
    
    assert len(items) == 2
    assert items[0].title == "Article 1"
    assert items[0].topic == "Frontend"
    assert items[0].tag_id == 1
    assert items[0].source_adapter == "search"


def test_build_collected_items_filters_empty():
    """Test that empty results are filtered out."""
    results = [
        {"title": "", "url": "https://example.com/1", "snippet": "Summary"},
        {"title": "Article 2", "url": "", "snippet": "Summary"},
    ]
    feed = {"topic": "Frontend", "tag_id": 1}
    
    items = _build_collected_items(results, feed, "Frontend")
    
    assert len(items) == 0


@pytest.mark.asyncio
async def test_collect_search_backfill_tinyfish_enabled():
    """Test TinyFish search when enabled."""
    with patch('app.collectors.search.settings') as mock_settings, \
         patch('app.collectors.search.tinyfish_budget') as mock_budget, \
         patch('app.collectors.search._tinyfish_search') as mock_tinyfish:
        
        mock_settings.TINYFISH_ENABLED = True
        mock_settings.TINYFISH_API_KEY = "test-key"
        mock_budget.try_spend_search.return_value = True
        
        # TinyFish returns results
        mock_tinyfish.return_value = [
            {"title": "TinyFish Result", "url": "https://example.com/tf", "snippet": "TF Summary"}
        ]
        
        feed = {"topic": "Frontend", "tag_id": 1, "id": "feed-1", "weight": 0.8}
        items, poll = await collect_search_backfill(feed, query="Frontend")
        
        assert len(items) == 1
        assert items[0].title == "TinyFish Result"
        assert poll["last_status"] == 200
        mock_budget.try_spend_search.assert_called_once()


@pytest.mark.asyncio
async def test_collect_search_backfall_to_searxng():
    """Test fallback to SearXNG/DDG when TinyFish fails."""
    with patch('app.collectors.search.settings') as mock_settings, \
         patch('app.collectors.search.tinyfish_budget') as mock_budget, \
         patch('app.collectors.search._tinyfish_search') as mock_tinyfish, \
         patch('app.collectors.search.search') as mock_search:
        
        mock_settings.TINYFISH_ENABLED = True
        mock_settings.TINYFISH_API_KEY = "test-key"
        mock_budget.try_spend_search.return_value = True
        
        # TinyFish fails
        mock_tinyfish.return_value = None
        
        # SearXNG/DDG succeeds
        mock_search.return_value = [
            {"title": "SearXNG Result", "url": "https://example.com/sx", "snippet": "SX Summary"}
        ]
        
        feed = {"topic": "Frontend", "tag_id": 1, "id": "feed-1", "weight": 0.8}
        items, poll = await collect_search_backfill(feed, query="Frontend")
        
        assert len(items) == 1
        assert items[0].title == "SearXNG Result"
        mock_search.assert_called_once()


@pytest.mark.asyncio
async def test_collect_search_disabled_tinyfish():
    """Test when TinyFish is disabled - uses SearXNG/DDG directly."""
    with patch('app.collectors.search.settings') as mock_settings, \
         patch('app.collectors.search.tinyfish_budget') as mock_budget, \
         patch('app.collectors.search._tinyfish_search') as mock_tinyfish, \
         patch('app.collectors.search.search') as mock_search:
        
        mock_settings.TINYFISH_ENABLED = False
        mock_settings.TINYFISH_API_KEY = ""
        
        # SearXNG/DDG succeeds
        mock_search.return_value = [
            {"title": "DDG Result", "url": "https://example.com/ddg", "snippet": "DDG Summary"}
        ]
        
        feed = {"topic": "Frontend", "tag_id": 1, "id": "feed-1", "weight": 0.8}
        items, poll = await collect_search_backfill(feed, query="Frontend")
        
        assert len(items) == 1
        assert items[0].title == "DDG Result"
        mock_tinyfish.assert_not_called()


@pytest.mark.asyncio
async def test_collect_search_rate_limit_fallback():
    """Test fallback when TinyFish rate limited."""
    with patch('app.collectors.search.settings') as mock_settings, \
         patch('app.collectors.search.tinyfish_budget') as mock_budget, \
         patch('app.collectors.search._tinyfish_search') as mock_tinyfish, \
         patch('app.collectors.search.search') as mock_search:
        
        mock_settings.TINYFISH_ENABLED = True
        mock_settings.TINYFISH_API_KEY = "test-key"
        
        # Rate limited
        mock_budget.try_spend_search.return_value = False
        
        # SearXNG/DDG succeeds
        mock_search.return_value = [
            {"title": "Fallback Result", "url": "https://example.com/fb", "snippet": "FB Summary"}
        ]
        
        feed = {"topic": "Frontend", "tag_id": 1, "id": "feed-1", "weight": 0.8}
        items, poll = await collect_search_backfill(feed, query="Frontend")
        
        assert len(items) == 1
        assert items[0].title == "Fallback Result"
        mock_tinyfish.assert_not_called()  # Never called due to rate limit