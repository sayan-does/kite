from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.discovery.nodes import (
    _kb_topic_urls,
    heuristic_filter_node,
    save_kb_article_node,
)


def test_kb_topic_urls_returns_existing_urls():
    with patch("app.agents.discovery.nodes.supabase") as mock_supabase:
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"url": "https://a.com"}, {"url": "https://b.com"}, {"url": None}]
        )
        urls = _kb_topic_urls("React")

    assert urls == {"https://a.com", "https://b.com"}


def test_heuristic_drops_owned_urls_from_state():
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


def test_heuristic_legacy_uses_user_owned_urls_when_state_missing():
    state = {
        "user_id": "user-1",
        "topic": "React",
        "results": [
            {"title": "Good", "url": "https://github.com/facebook/react", "snippet": "React 2026 release notes update"},
            {"title": "Owned", "url": "https://medium.com/react-post", "snippet": "React framework news 2026"},
        ],
    }
    with patch("app.agents.discovery.nodes._owned_urls", return_value={"https://medium.com/react-post"}):
        result = heuristic_filter_node(state)
    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Good"


def test_save_kb_article_inserts_and_decrements_slot():
    state = {
        "topic": "React",
        "topic_kind": "interest",
        "tag_id": 1,
        "open_slots": 10,
        "cand_idx": 0,
        "article": {
            "title": "React 19",
            "one_liner": "React 19 ships.",
            "summary": "React 19 ships.",
            "body": "Details.",
            "source_type": "blog",
            "citations": [{"type": "blog", "url": "https://dev.to/react-19", "title": "React 19"}],
        },
    }
    with patch("app.agents.discovery.nodes.supabase") as mock_supabase:
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value = MagicMock(data=[{"id": "new-id"}])

        result = save_kb_article_node(state)

    assert result["open_slots"] == 9
    assert result["cand_idx"] == 1
    call_row = mock_table.upsert.call_args[0][0]
    assert call_row["topic"] == "React"
    assert call_row["url"] == "https://dev.to/react-19"
    assert "user_id" not in call_row


def test_save_kb_article_conflict_advances_idx_without_slot_decrement():
    state = {
        "topic": "React",
        "topic_kind": "interest",
        "tag_id": 1,
        "open_slots": 10,
        "cand_idx": 0,
        "article": {
            "title": "React 19",
            "one_liner": "React 19 ships.",
            "summary": "React 19 ships.",
            "body": "Details.",
            "source_type": "blog",
            "citations": [{"type": "blog", "url": "https://dev.to/react-19", "title": "React 19"}],
        },
    }
    with patch("app.agents.discovery.nodes.supabase") as mock_supabase:
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value = MagicMock(data=[])

        result = save_kb_article_node(state)

    assert result["open_slots"] == 10
    assert result["cand_idx"] == 1


def test_save_kb_article_skips_empty_article():
    state = {
        "topic": "React",
        "topic_kind": "interest",
        "tag_id": 1,
        "open_slots": 10,
        "cand_idx": 2,
        "article": {},
    }
    with patch("app.agents.discovery.nodes.supabase") as mock_supabase:
        result = save_kb_article_node(state)

    mock_supabase.table.assert_not_called()
    assert result["cand_idx"] == 3
    assert result["open_slots"] == 10


def test_save_kb_article_research_flag_and_paper_citation():
    state = {
        "topic": "AI/ML",
        "topic_kind": "interest",
        "tag_id": 1,
        "open_slots": 5,
        "cand_idx": 0,
        "article": {
            "title": "New LLM paper explained",
            "one_liner": "A new paper drops.",
            "summary": "A new paper drops.",
            "body": "Details.",
            "source_type": "blog",
            "is_research": True,
            "citations": [
                {
                    "type": "blog",
                    "url": "https://huggingface.co/blog/cool-paper",
                    "title": "New LLM paper explained",
                },
                {
                    "type": "blog",
                    "url": "https://arxiv.org/abs/2401.12345",
                    "title": "Paper",
                },
            ],
        },
    }
    with patch("app.agents.discovery.nodes.supabase") as mock_supabase:
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value = MagicMock(data=[{"id": "r1"}])

        result = save_kb_article_node(state)

    assert result["open_slots"] == 4
    call_row = mock_table.upsert.call_args[0][0]
    assert call_row["is_research"] is True
    assert call_row["source_type"] == "blog"
    assert call_row["url"] == "https://huggingface.co/blog/cool-paper"
    paper = [c for c in call_row["citations"] if c.get("title") == "Paper"]
    assert len(paper) == 1
    assert paper[0]["url"].startswith("https://arxiv.org/")
