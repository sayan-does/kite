from unittest.mock import MagicMock, patch

import pytest

from app.services.kb import KbTopic, resolve_kb_topics


def _table_mock(responses: list):
    """Return a supabase mock where each table().select()...execute() consumes one response."""
    call_idx = {"i": 0}

    def make_chain():
        chain = MagicMock()
        response = responses[call_idx["i"]] if call_idx["i"] < len(responses) else MagicMock(data=[])
        call_idx["i"] += 1
        chain.select.return_value = chain
        chain.in_.return_value = chain
        chain.execute.return_value = response
        return chain

    mock_supabase = MagicMock()
    mock_supabase.table.side_effect = lambda _name: make_chain()
    return mock_supabase


def test_resolve_kb_topics_returns_followed_tags_only():
    mock_supabase = _table_mock([
        MagicMock(data=[{"tag_id": 1}, {"tag_id": 2}]),
        MagicMock(data=[
            {"id": 1, "name": "Frontend"},
            {"id": 2, "name": "Backend"},
        ]),
        MagicMock(data=[]),
    ])
    with patch("app.services.kb.supabase", mock_supabase):
        topics = resolve_kb_topics()

    assert len(topics) == 2
    assert all(t.topic_kind == "interest" for t in topics)
    assert topics[0].topic == "Backend"
    assert topics[1].topic == "Frontend"
    assert topics[0].tag_id == 2
    assert topics[1].tag_id == 1


def test_resolve_kb_topics_excludes_packages_below_threshold():
    mock_supabase = _table_mock([
        MagicMock(data=[]),
        MagicMock(data=[
            {"user_id": "u1", "package_name": "react"},
            {"user_id": "u2", "package_name": "react"},
            {"user_id": "u1", "package_name": "lodash"},
        ]),
    ])
    with (
        patch("app.services.kb.settings") as mock_settings,
        patch("app.services.kb.supabase", mock_supabase),
    ):
        mock_settings.KB_STACK_MIN_USERS = 3
        topics = resolve_kb_topics()

    assert topics == []


def test_resolve_kb_topics_includes_popular_stack_packages():
    mock_supabase = _table_mock([
        MagicMock(data=[{"tag_id": 5}]),
        MagicMock(data=[{"id": 5, "name": "AI"}]),
        MagicMock(data=[
            {"user_id": "u1", "package_name": "react"},
            {"user_id": "u2", "package_name": "react"},
            {"user_id": "u3", "package_name": "react"},
            {"user_id": "u1", "package_name": "lodash"},
        ]),
    ])
    with (
        patch("app.services.kb.settings") as mock_settings,
        patch("app.services.kb.supabase", mock_supabase),
    ):
        mock_settings.KB_STACK_MIN_USERS = 3
        topics = resolve_kb_topics()

    stack_topics = [t for t in topics if t.topic_kind == "stack"]
    assert len(stack_topics) == 1
    assert stack_topics[0].topic == "react"
    assert stack_topics[0].tag_id is None

    interest_topics = [t for t in topics if t.topic_kind == "interest"]
    assert len(interest_topics) == 1
    assert interest_topics[0].tag_id == 5
