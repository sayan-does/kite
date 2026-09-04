import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.discovery.nodes import (
    citation_extract_node,
    filter_relevance_node,
    heuristic_filter_node,
    save_article_node,
    search_node,
    summarize_node,
    summarize_v2_node,
    youtube_embed_node,
)


@pytest.mark.asyncio
async def test_search():
    fake_results = [
        {"title": "Frontend News 1", "url": "https://example.com/1", "snippet": "Content about frontend"},
    ]
    with patch("app.agents.discovery.nodes.search", AsyncMock(return_value=fake_results)):
        state = {"tag": "Frontend"}
        result = await search_node(state)
        assert "results" in result
        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Frontend News 1"


def test_filter_removes_duplicates_and_off_topic():
    results = [
        {"title": "Valid", "url": "https://a.com", "snippet": "Real content here about topic"},
        {"title": "Duplicate", "url": "https://a.com", "snippet": "Duplicate url content"},
        {"title": "Empty snippet", "url": "https://b.com", "snippet": ""},
        {"title": "Short", "url": "https://c.com", "snippet": "ab"},
        {"title": "Off Topic", "url": "https://d.com", "snippet": "Some real content about something else entirely"},
    ]
    state = {"results": results}
    result = filter_relevance_node(state)
    assert len(result["results"]) == 2
    assert result["results"][0]["title"] == "Valid"


@pytest.mark.asyncio
async def test_summarize():
    fake_llm_response = MagicMock()
    fake_llm_response.content = (
        "TITLE: Frontend Framework Updates\n"
        "SUMMARY: New features in React and Vue.\n"
        "BODY: React 19 introduces new compiler optimizations."
    )
    with patch("app.agents.discovery.nodes.groq_client") as mock_groq:
        mock_groq.invoke = MagicMock(return_value=fake_llm_response)
        state = {
            "tag": "Frontend",
            "results": [
                {"title": "R1", "url": "https://a.com", "snippet": "Content about frontend frameworks updates 2026"}
            ],
        }
        result = await summarize_node(state)
        assert "article" in result
        assert result["article"]["title"] == "Frontend Framework Updates"
        assert result["article"]["summary"] == "New features in React and Vue."
        assert "compiler optimizations" in result["article"]["body"]


@pytest.mark.asyncio
async def test_summarize_empty_results():
    state = {"tag": "Frontend", "results": []}
    result = await summarize_node(state)
    assert result["article"]["title"] == ""
    assert result["article"]["summary"] == ""


def test_citations_classify_urls():
    results = [
        {"title": "Docs", "url": "https://docs.example.com/guide", "snippet": "docs"},
        {"title": "GitHub", "url": "https://github.com/user/repo", "snippet": "github"},
        {"title": "Blog", "url": "https://dev.to/article", "snippet": "devto"},
        {"title": "YouTube", "url": "https://youtube.com/watch?v=abc", "snippet": "video"},
    ]
    state = {"results": results, "article": {"title": "T", "summary": "S", "body": "B"}}
    result = citation_extract_node(state)
    citations = result["article"]["citations"]
    types = {c["type"] for c in citations}
    assert "official_docs" in types
    assert "github" in types
    assert "blog" in types
    assert "youtube" in types


@pytest.mark.asyncio
async def test_youtube_returns_url():
    async def fake_resolve(article: dict) -> str:
        return "https://www.youtube.com/watch?v=abc123"

    with patch("app.services.youtube.resolve_youtube_url", side_effect=fake_resolve):
        state = {"tag": "Frontend", "article": {"title": "T", "summary": "S", "body": "B", "citations": []}}
        result = await youtube_embed_node(state)
        assert "youtube.com/watch?v=abc123" in result["article"]["youtube_url"]


@pytest.mark.asyncio
async def test_youtube_no_key_skips():
    with patch("app.services.youtube.resolve_youtube_url", return_value=None):
        state = {"tag": "Frontend", "article": {"title": "T", "summary": "S", "body": "B"}}
        result = await youtube_embed_node(state)
        assert result == state
        assert "youtube_url" not in result.get("article", {})


def test_save_article():
    state = {
        "tag_id": 1,
        "article": {
            "title": "Test Article",
            "summary": "Test summary",
            "body": "Test body",
            "citations": [{"type": "blog", "url": "https://example.com", "title": "Example"}],
            "youtube_url": None,
        },
    }
    with patch("app.agents.discovery.nodes.supabase") as mock_supabase:
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table
        mock_upsert = MagicMock()
        mock_table.upsert.return_value = mock_upsert
        mock_upsert.execute.return_value = MagicMock()

        result = save_article_node(state)
        assert result == state
        mock_table.upsert.assert_called_once()
        call_kwargs = mock_table.upsert.call_args[0][0]
        assert call_kwargs["title"] == "Test Article"
        assert call_kwargs["tag_id"] == 1
        assert len(call_kwargs["citations"]) == 1


def test_heuristic_drops_owned_urls_from_state_dedup():
    state = {
        "topic": "React",
        "owned_urls": {"https://owned.com/react-post"},
        "results": [
            {"title": "Good", "url": "https://github.com/facebook/react", "snippet": "React 2026 release notes update"},
            {"title": "Owned", "url": "https://owned.com/react-post", "snippet": "React framework news 2026"},
        ],
    }
    result = heuristic_filter_node(state)
    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Good"


def test_heuristic_drops_off_domain_stale_low_overlap():
    state = {
        "user_id": "user-1",
        "topic": "React",
        "results": [
            {"title": "Good", "url": "https://github.com/facebook/react", "snippet": "React 2026 release notes update"},
            {"title": "Low overlap", "url": "https://dev.to/other", "snippet": "Unrelated cooking recipes entirely"},
            {"title": "Owned", "url": "https://medium.com/react-post", "snippet": "React framework news 2026"},
        ],
    }
    with patch("app.agents.discovery.nodes._owned_urls", return_value={"https://medium.com/react-post"}):
        result = heuristic_filter_node(state)
    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Good"


def test_heuristic_enforces_threshold():
    state = {
        "user_id": "user-1",
        "topic": "QuantumComputing",
        "results": [
            {"title": "Weak", "url": "https://dev.to/x", "snippet": "Some generic software news without topic words"},
        ],
    }
    with patch("app.agents.discovery.nodes._owned_urls", return_value=set()):
        result = heuristic_filter_node(state)
    assert result["results"] == []


@pytest.mark.asyncio
async def test_summarize_v2_returns_structured_json_one_groq_call():
    fake_llm = MagicMock()
    fake_llm.content = (
        '{"one_liner": "React 19 ships compiler.", '
        '"full_summary": "React 19 introduces a new compiler and improved hooks.", '
        '"source_type": "blog"}'
    )
    with (
        patch("app.agents.discovery.nodes.fetch_article_text", AsyncMock(return_value="Long article body about React 19.")),
        patch("app.agents.discovery.nodes.groq_client") as mock_groq,
    ):
        mock_groq.invoke = MagicMock(return_value=fake_llm)
        state = {
            "topic": "React",
            "results": [{"title": "React 19", "url": "https://dev.to/react-19", "snippet": "React update"}],
        }
        result = await summarize_v2_node(state)

    mock_groq.invoke.assert_called_once()
    assert result["article"]["one_liner"] == "React 19 ships compiler."
    assert "compiler" in result["article"]["body"]
    assert result["article"]["source_type"] == "blog"
    assert len(result["article"]["citations"]) == 1


@pytest.mark.asyncio
async def test_summarize_v2_no_card_when_content_unavailable():
    with (
        patch("app.agents.discovery.nodes.fetch_article_text", AsyncMock(return_value=None)),
        patch("app.agents.discovery.nodes.groq_client") as mock_groq,
    ):
        state = {
            "topic": "React",
            "results": [{"title": "React 19", "url": "https://dev.to/x", "snippet": ""}],
        }
        result = await summarize_v2_node(state)

    mock_groq.invoke.assert_not_called()
    assert result["article"] == {}
