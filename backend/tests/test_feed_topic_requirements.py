"""Tests for feed API topic requirements."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.auth import get_current_user_id


@pytest.fixture(autouse=True)
def override_auth():
    from app.main import app
    app.dependency_overrides[get_current_user_id] = lambda: "test-user-id"
    yield
    app.dependency_overrides.pop(get_current_user_id, None)


def test_get_feed_without_tag_returns_400():
    """Test that /feed without tag parameter returns 400."""
    from app.main import app
    
    with patch('app.routers.feed._disabled_citation_types', return_value=set()):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/feed")
        
        assert response.status_code == 400
        assert "select one or multiple topics" in response.json()["detail"]


def test_get_feed_with_single_topic_returns_articles():
    """Test that /feed?tag=Frontend returns articles."""
    from app.main import app
    
    with patch('app.routers.feed._disabled_citation_types', return_value=set()), \
         patch('app.routers.feed._kb_feed_page') as mock_page:
        
        mock_page.return_value = {
            "articles": [{"id": "1", "title": "Test"}],
            "page": 1,
            "has_next": False
        }
        
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/feed?tag=Frontend")
        
        assert response.status_code == 200
        data = response.json()
        assert "articles" in data
        mock_page.assert_called_once()


def test_get_feed_with_multiple_topics_returns_grouped():
    """Test that /feed?tag=Frontend,Backend returns grouped feeds."""
    from app.main import app
    
    with patch('app.routers.feed._disabled_citation_types', return_value=set()), \
         patch('app.routers.feed._kb_feed_page') as mock_page:
        
        # Mock returns different articles for each topic
        def side_effect(user_id, tag, page, disabled, include_body=False):
            return {
                "articles": [{"id": f"{tag}-1", "title": f"Article for {tag}"}],
                "page": page,
                "has_next": False
            }
        mock_page.side_effect = side_effect
        
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/feed?tag=Frontend,Backend")
        
        assert response.status_code == 200
        data = response.json()
        assert "feeds" in data
        assert len(data["feeds"]) == 2
        assert data["feeds"][0]["topic"] == "Frontend"
        assert data["feeds"][1]["topic"] == "Backend"


def test_get_feed_with_unknown_topic():
    """Test that /feed?tag=InvalidTopic returns appropriate response."""
    from app.main import app
    
    with patch('app.routers.feed._disabled_citation_types', return_value=set()), \
         patch('app.routers.feed._kb_feed_page') as mock_page:
        
        # Return empty articles for unknown topic
        mock_page.return_value = {
            "articles": [],
            "page": 1,
            "has_next": False
        }
        
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/feed?tag=InvalidTopic")
        
        # Should return empty articles, not 404 (topic might just have no articles)
        assert response.status_code == 200
        assert response.json()["articles"] == []


def test_article_payload_includes_key_links():
    """Test that _article_payload includes key_links."""
    from app.routers.feed import _article_payload
    
    article = {
        "id": "test-1",
        "title": "Test Article",
        "summary": "Summary",
        "url": "https://example.com",
        "key_links": [{"title": "Link", "url": "https://example.com/link"}],
        "tier": "reviewed",
    }
    
    with patch('app.routers.feed.settings') as mock_settings:
        mock_settings.DISCOVERY_V2 = False
        mock_settings.KB_FEED = True
        
        payload = _article_payload(article, set(), include_body=False)
        
        assert "key_links" in payload
        assert len(payload["key_links"]) == 1
        assert payload["key_links"][0]["title"] == "Link"


def test_article_payload_defaults_key_links_to_empty():
    """Test that key_links defaults to empty list."""
    from app.routers.feed import _article_payload
    
    article = {
        "id": "test-1",
        "title": "Test Article",
        "summary": "Summary",
        "url": "https://example.com",
        # No key_links field
        "tier": "raw",
    }
    
    with patch('app.routers.feed.settings') as mock_settings:
        mock_settings.DISCOVERY_V2 = False
        mock_settings.KB_FEED = True
        
        payload = _article_payload(article, set(), include_body=False)
        
        assert "key_links" in payload
        assert payload["key_links"] == []