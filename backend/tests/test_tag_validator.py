"""Tests for LLM tag validation worker."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.tag_validator import validate_untagged_articles, MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_tag_validator_no_client():
    with patch("app.services.tag_validator.for_role", return_value=None):
        result = await validate_untagged_articles()
        assert result == {"validated": 0, "retries": 0, "rejected": 0}


@pytest.mark.asyncio
async def test_tag_validator_no_pending_articles():
    mock_supabase = MagicMock()
    mock_select = MagicMock()
    mock_select.select.return_value.eq.return_value.eq.return_value.or_.return_value.limit.return_value.execute.return_value.data = []
    mock_supabase.table.return_value = mock_select

    with patch("app.services.tag_validator.for_role", return_value=MagicMock()), \
         patch("app.services.tag_validator._get_articles_table", return_value="kb_articles_partitioned"), \
         patch("app.services.tag_validator.supabase", mock_supabase):
        result = await validate_untagged_articles()
        assert result == {"validated": 0, "retries": 0, "rejected": 0}


@pytest.mark.asyncio
async def test_tag_validator_successful_validation():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = '{"tag_id": 1, "confidence": "high", "reason": "Frontend topic"}'
    mock_client.ainvoke = AsyncMock(return_value=mock_response)

    articles = [{
        "id": "art-1",
        "title": "React 19 overview",
        "one_liner": "A React post",
        "validation_attempts": 0,
        "url": "https://example.com/react",
    }]

    tags = [{"id": 1, "name": "Frontend"}, {"id": 2, "name": "Backend"}]

    mock_table = MagicMock()
    # Query pending articles
    mock_table.select.return_value.eq.return_value.eq.return_value.or_.return_value.limit.return_value.execute.return_value.data = articles
    # Query tags
    mock_table.select.return_value.execute.return_value.data = tags

    with patch("app.services.tag_validator.for_role", return_value=mock_client), \
         patch("app.services.tag_validator._get_articles_table", return_value="kb_articles_partitioned"), \
         patch("app.services.tag_validator.supabase.table", return_value=mock_table), \
         patch("app.services.tag_validator.fetch_single_article", new_callable=AsyncMock, return_value="React 19 markdown"):
        
        result = await validate_untagged_articles()
        assert result["validated"] == 1
        assert result["retries"] == 0
        assert result["rejected"] == 0


@pytest.mark.asyncio
async def test_tag_validator_low_confidence_retries():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = '{"tag_id": 1, "confidence": "low", "reason": "Unsure"}'
    mock_client.ainvoke = AsyncMock(return_value=mock_response)

    articles = [{
        "id": "art-2",
        "title": "Vague blog title",
        "one_liner": "Something tech",
        "validation_attempts": 1,
        "url": "https://example.com/vague",
    }]

    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.eq.return_value.or_.return_value.limit.return_value.execute.return_value.data = articles
    mock_table.select.return_value.execute.return_value.data = [{"id": 1, "name": "Frontend"}]

    with patch("app.services.tag_validator.for_role", return_value=mock_client), \
         patch("app.services.tag_validator._get_articles_table", return_value="kb_articles_partitioned"), \
         patch("app.services.tag_validator.supabase.table", return_value=mock_table), \
         patch("app.services.tag_validator.fetch_single_article", new_callable=AsyncMock, return_value=None):
        
        result = await validate_untagged_articles()
        assert result["validated"] == 0
        assert result["retries"] == 1
        assert result["rejected"] == 0


@pytest.mark.asyncio
async def test_tag_validator_max_attempts_rejected():
    mock_client = MagicMock()

    articles = [{
        "id": "art-3",
        "title": "Unclassifiable post",
        "validation_attempts": MAX_ATTEMPTS,
        "url": "https://example.com/lost",
    }]

    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.eq.return_value.or_.return_value.limit.return_value.execute.return_value.data = articles

    with patch("app.services.tag_validator.for_role", return_value=mock_client), \
         patch("app.services.tag_validator._get_articles_table", return_value="kb_articles_partitioned"), \
         patch("app.services.tag_validator.supabase.table", return_value=mock_table):
        
        result = await validate_untagged_articles()
        assert result["validated"] == 0
        assert result["retries"] == 0
        assert result["rejected"] == 1
