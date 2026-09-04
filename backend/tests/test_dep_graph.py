import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.dependency.graph import run_dependency_update


@pytest.mark.asyncio
async def test_dep_graph_end_to_end():
    with (
        patch("app.agents.dependency.nodes.httpx.AsyncClient") as mock_http,
        patch("app.agents.dependency.nodes.supabase") as mock_supabase,
        patch("app.agents.dependency.nodes.groq_client") as mock_groq,
        patch("app.agents.dependency.nodes.search", AsyncMock(return_value=[])),
    ):
        # Registry check: returns new version
        mock_registry_resp = MagicMock()
        mock_registry_resp.status_code = 200
        mock_registry_resp.json.return_value = {"version": "19.0.0"}

        # OSV vuln check: returns an advisory
        mock_vuln_resp = MagicMock()
        mock_vuln_resp.status_code = 200
        mock_vuln_resp.json.return_value = {
            "vulns": [{"id": "GHSA-1111", "summary": "Test advisory for react"}]
        }

        # Changelog: returns 404 (no feed)
        mock_changelog_resp = MagicMock()
        mock_changelog_resp.status_code = 404

        mock_http_instance = AsyncMock()
        mock_http_instance.get.side_effect = [mock_registry_resp, mock_changelog_resp]
        mock_http_instance.post.return_value = mock_vuln_resp
        mock_http.return_value.__aenter__.return_value = mock_http_instance

        # Cache: empty initial
        mock_cache = MagicMock()
        mock_cache.data = []
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = (
            mock_cache
        )

        # Groq summarize
        fake_llm_response = MagicMock()
        fake_llm_response.content = "React 19 is now available."
        mock_groq.invoke = MagicMock(return_value=fake_llm_response)

        # Save
        mock_table = MagicMock()
        mock_upsert = MagicMock()
        mock_upsert.execute.return_value = MagicMock()
        mock_table.upsert.return_value = mock_upsert

        def table_side_effect(name):
            if name == "package_registry_cache":
                cache_table = MagicMock()
                cache_table.upsert.return_value = MagicMock()
                cache_table.upsert.return_value.execute.return_value = MagicMock()
                return cache_table
            if name == "dependency_updates":
                return mock_table
            return MagicMock()

        mock_supabase.table.side_effect = table_side_effect

        await run_dependency_update("npm", "react")

        # Final save should have been called
        mock_table.upsert.assert_called_once()
        call_data = mock_table.upsert.call_args[0][0]
        assert call_data["ecosystem"] == "npm"
        assert call_data["package_name"] == "react"
        assert call_data["update_type"] in ("release", "security", "breaking", "buzz")
