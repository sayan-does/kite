from unittest.mock import MagicMock, patch

from app.agents.discovery.nodes import save_article_v2_node


def test_eleventh_insert_evicts_oldest():
    existing = [{"id": f"id-{i}", "fetched_at": f"2026-01-{i:02d}T00:00:00Z"} for i in range(1, 11)]
    state = {
        "user_id": "user-1",
        "source": "interest",
        "topic": "Frontend",
        "open_slots": 1,
        "articles_saved": 0,
        "article": {
            "title": "New Card",
            "one_liner": "New one liner",
            "summary": "New one liner",
            "body": "Full summary",
            "source_type": "blog",
            "citations": [{"type": "blog", "url": "https://new.com", "title": "New"}],
        },
    }

    mock_table = MagicMock()
    mock_insert = MagicMock()
    mock_insert.execute.return_value = MagicMock()
    mock_table.insert.return_value = mock_insert

    mock_select = MagicMock()
    mock_select.eq.return_value.order.return_value.execute.return_value = MagicMock(
        data=existing + [{"id": "id-new", "fetched_at": "2026-01-11T00:00:00Z"}]
    )
    mock_table.select.return_value = mock_select

    mock_delete = MagicMock()
    mock_delete.eq.return_value.execute.return_value = MagicMock()
    mock_table.delete.return_value = mock_delete

    with patch("app.agents.discovery.nodes.supabase") as mock_sb:
        mock_sb.table.return_value = mock_table
        result = save_article_v2_node(state)

    mock_table.delete.assert_called()
    assert result["open_slots"] == 0
    assert result["articles_saved"] == 1


def test_no_new_content_leaves_feed_unchanged():
    state = {
        "user_id": "user-1",
        "source": "interest",
        "topic": "Frontend",
        "open_slots": 3,
        "articles_saved": 0,
        "article": {},
    }

    with patch("app.agents.discovery.nodes.supabase") as mock_sb:
        result = save_article_v2_node(state)

    mock_sb.table.assert_not_called()
    assert result["open_slots"] == 3
    assert result["articles_saved"] == 0
