from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.discovery.kb_graph import run_kb_discovery_for_topic


@pytest.mark.asyncio
async def test_kb_graph_halts_at_open_slots_zero():
    candidates = [
        {"title": f"Article {i}", "url": f"https://dev.to/{i}", "snippet": f"React news 2026 item {i}"}
        for i in range(15)
    ]

    with (
        patch("app.agents.discovery.nodes._kb_topic_urls", return_value=set()),
        patch("app.agents.discovery.nodes.search", AsyncMock(return_value=candidates)),
        patch("app.agents.discovery.nodes.fetch_article_text", AsyncMock(return_value="Long body about React 2026.")),
        patch("app.agents.discovery.nodes.groq_client") as mock_groq,
        patch("app.agents.discovery.nodes.supabase") as mock_supabase,
        patch("app.agents.discovery.nodes.youtube_embed_node", AsyncMock(side_effect=lambda s: s)),
    ):
        mock_groq.invoke = MagicMock(
            return_value=MagicMock(
                content='{"one_liner": "React update.", "full_summary": "Summary.", "source_type": "blog"}'
            )
        )
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value = MagicMock(
            data=[{"id": "kb-1"}]
        )

        await run_kb_discovery_for_topic("React", "interest", 1)

    assert mock_table.upsert.call_count == 10
    for call in mock_table.upsert.call_args_list:
        row = call[0][0]
        assert row["topic"] == "React"
        assert row["topic_kind"] == "interest"
        assert row["tag_id"] == 1
        assert "user_id" not in row


@pytest.mark.asyncio
async def test_kb_graph_halts_when_candidates_exhausted():
    candidates = [
        {"title": "Only one", "url": "https://dev.to/one", "snippet": "React news 2026 only one"},
    ]

    with (
        patch("app.agents.discovery.nodes._kb_topic_urls", return_value=set()),
        patch("app.agents.discovery.nodes.search", AsyncMock(return_value=candidates)),
        patch("app.agents.discovery.nodes.fetch_article_text", AsyncMock(return_value="Long body about React 2026.")),
        patch("app.agents.discovery.nodes.groq_client") as mock_groq,
        patch("app.agents.discovery.nodes.supabase") as mock_supabase,
        patch("app.agents.discovery.nodes.youtube_embed_node", AsyncMock(side_effect=lambda s: s)),
    ):
        mock_groq.invoke = MagicMock(
            return_value=MagicMock(
                content='{"one_liner": "React update.", "full_summary": "Summary.", "source_type": "blog"}'
            )
        )
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value = MagicMock(
            data=[{"id": "kb-1"}]
        )

        await run_kb_discovery_for_topic("React", "interest", 1)

    assert mock_table.upsert.call_count == 1
