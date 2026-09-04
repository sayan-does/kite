from unittest.mock import AsyncMock, patch

import pytest

from app.agents.discovery.nodes import _search_aiml_three_pass, search_node


@pytest.mark.asyncio
async def test_non_aiml_uses_single_general_query():
    fake = [{"title": "React", "url": "https://example.com/r", "snippet": "news"}]
    with patch("app.agents.discovery.nodes.search", AsyncMock(return_value=fake)) as mock_search:
        result = await search_node({"topic": "React"})
    assert result["results"] == fake
    mock_search.assert_awaited_once()
    assert "React" in mock_search.await_args.args[0]
    assert "site:" not in mock_search.await_args.args[0]


@pytest.mark.asyncio
async def test_aiml_three_pass_order_and_dedupe():
    curated_hit = {
        "title": "HF paper blog",
        "url": "https://huggingface.co/blog/cool-paper",
        "snippet": "New model release",
    }
    biased_hit = {
        "title": "Arxiv explained",
        "url": "https://techcrunch.com/ai-paper",
        "snippet": "Discusses https://arxiv.org/abs/2401.1 breakthrough",
    }
    # Duplicate of curated — should appear only once, in curated position
    general_dup = {
        "title": "HF again",
        "url": "https://huggingface.co/blog/cool-paper",
        "snippet": "same",
    }
    general_hit = {
        "title": "General AI news",
        "url": "https://example.com/ai-news",
        "snippet": "plain AI/ML news 2026",
    }
    noise = {
        "title": "Unrelated biased miss",
        "url": "https://example.com/unrelated",
        "snippet": "stock market update",
    }

    async def fake_search(query: str):
        if "site:" in query:
            return [curated_hit, {"title": "Off", "url": "https://spam.com/x", "snippet": "x"}]
        if "preprint" in query or "arxiv" in query.lower():
            return [biased_hit, noise, curated_hit]
        return [general_dup, general_hit]

    with patch("app.agents.discovery.nodes.search", AsyncMock(side_effect=fake_search)) as mock_search:
        results = await _search_aiml_three_pass()

    assert mock_search.await_count == 3
    urls = [r["url"] for r in results]
    assert urls == [
        "https://huggingface.co/blog/cool-paper",
        "https://techcrunch.com/ai-paper",
        "https://example.com/ai-news",
    ]
    # noise dropped from biased pass (no paper/curated signal)
    assert "https://example.com/unrelated" not in urls


@pytest.mark.asyncio
async def test_search_node_aiml_uses_three_pass():
    with patch(
        "app.agents.discovery.nodes._search_aiml_three_pass",
        AsyncMock(return_value=[{"title": "R", "url": "https://huggingface.co/a", "snippet": "s"}]),
    ) as mock_three:
        with patch("app.agents.discovery.nodes.search", AsyncMock()) as mock_search:
            result = await search_node({"topic": "AI/ML"})
    mock_three.assert_awaited_once()
    mock_search.assert_not_awaited()
    assert result["results"][0]["url"] == "https://huggingface.co/a"
