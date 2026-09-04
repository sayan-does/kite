import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.discovery.graph import run_discovery_for_tag, run_discovery_for_user
from app.agents.discovery.interest_resolver import WeightedInterest


@pytest.mark.asyncio
async def test_discovery_graph_end_to_end():
    fake_results = [
        {"title": "Frontend News", "url": "https://example.com/1", "snippet": "Great frontend content here"},
    ]
    fake_llm_response = MagicMock()
    fake_llm_response.content = (
        "TITLE: Frontend Framework Updates\n"
        "SUMMARY: New features in React and Vue.\n"
        "BODY: React 19 introduces new compiler optimizations."
    )

    with (
        patch("app.agents.discovery.nodes.search", AsyncMock(return_value=fake_results)),
        patch("app.agents.discovery.nodes.groq_client") as mock_groq,
        patch("app.agents.discovery.nodes.supabase") as mock_supabase,
    ):
        mock_groq.invoke = MagicMock(return_value=fake_llm_response)

        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table
        mock_upsert = MagicMock()
        mock_table.upsert.return_value = mock_upsert
        mock_upsert.execute.return_value = MagicMock()

        await run_discovery_for_tag(tag_id=1, tag_name="Frontend")

        mock_table.upsert.assert_called_once()
        call_data = mock_table.upsert.call_args[0][0]
        assert call_data["title"] == "Frontend Framework Updates"
        assert call_data["tag_id"] == 1
        assert len(call_data["citations"]) > 0


@pytest.mark.asyncio
async def test_v2_graph_halts_at_open_slots_zero():
    user_id = str(uuid.uuid4())
    ranked = [
        WeightedInterest("Frontend", "interest", 0.6),
        WeightedInterest("react", "stack", 0.4),
    ]

    with (
        patch("app.agents.discovery.interest_resolver.resolve_interests", return_value=ranked),
        patch("app.agents.discovery.nodes.supabase") as mock_supabase,
    ):
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table
        mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": f"existing-{i}"} for i in range(10)]
        )

        await run_discovery_for_user(user_id)

        mock_table.insert.assert_not_called()


@pytest.mark.asyncio
async def test_v2_graph_partial_refill_when_interests_exhausted():
    user_id = str(uuid.uuid4())
    ranked = [WeightedInterest("Frontend", "interest", 1.0)]
    fake_results = [
        {"title": "Frontend News", "url": "https://dev.to/frontend", "snippet": "Frontend framework news 2026"},
    ]
    fake_llm = MagicMock()
    fake_llm.content = (
        '{"one_liner": "Frontend update.", "full_summary": "Full frontend summary.", "source_type": "blog"}'
    )

    with (
        patch("app.agents.discovery.interest_resolver.resolve_interests", return_value=ranked),
        patch("app.agents.discovery.nodes._owned_urls", return_value=set()),
        patch("app.agents.discovery.nodes.search", AsyncMock(return_value=fake_results)),
        patch("app.agents.discovery.nodes.fetch_article_text", AsyncMock(return_value="Article body about Frontend.")),
        patch("app.agents.discovery.nodes.groq_client") as mock_groq,
        patch("app.agents.discovery.nodes.supabase") as mock_supabase,
    ):
        mock_groq.invoke = MagicMock(return_value=fake_llm)
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table
        mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        mock_table.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=[])
        mock_table.insert.return_value.execute.return_value = MagicMock()

        await run_discovery_for_user(user_id)

        assert mock_table.insert.call_count == 1
        saved = mock_table.insert.call_args[0][0]
        assert saved["user_id"] == user_id
        assert saved["source"] == "interest"
        assert saved["topic"] == "Frontend"
