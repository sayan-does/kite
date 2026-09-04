from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.dependency.nodes import (
    changelog_fetch_node,
    conditional_buzz_node,
    dep_summarize_node,
    registry_check_node,
    save_update_node,
    vuln_check_node,
)


def _npm_history_payload(latest: str, versions: dict[str, str] | None = None):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    times = {"created": now, "modified": now, latest: now}
    if versions:
        times.update(versions)
    return {
        "dist-tags": {"latest": latest},
        "time": times,
        "versions": {latest: {}},
    }


def _chain_supabase(mock_supabase, cache_data=None):
    """Build a flexible supabase mock for registry/timeline upserts."""
    cache_data = cache_data if cache_data is not None else []

    def table(name):
        mock_table = MagicMock()
        if name == "package_registry_cache":
            execute_result = MagicMock()
            execute_result.data = cache_data
            mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value = execute_result
            mock_table.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = execute_result
            mock_table.upsert.return_value.execute.return_value = MagicMock()
        else:
            execute_result = MagicMock()
            execute_result.data = []
            mock_table.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = execute_result
            mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value = execute_result
            mock_table.upsert.return_value.execute.return_value = MagicMock()
        return mock_table

    mock_supabase.table.side_effect = table


@pytest.mark.asyncio
async def test_registry_detects_new_version():
    state = {"ecosystem": "npm", "package_name": "react"}
    with (
        patch("httpx.AsyncClient") as mock_client,
        patch("app.agents.dependency.nodes.supabase") as mock_supabase,
    ):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _npm_history_payload("19.0.0")
        mock_instance = AsyncMock()
        mock_instance.get.return_value = mock_resp
        mock_client.return_value.__aenter__.return_value = mock_instance
        _chain_supabase(mock_supabase, cache_data=[])

        result = await registry_check_node(state)
        assert result["new_version"] == "19.0.0"
        assert result["latest_version"] == "19.0.0"


@pytest.mark.asyncio
async def test_registry_no_change_when_same():
    state = {"ecosystem": "npm", "package_name": "react"}
    with (
        patch("httpx.AsyncClient") as mock_client,
        patch("app.agents.dependency.nodes.supabase") as mock_supabase,
    ):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _npm_history_payload("18.2.0")
        mock_instance = AsyncMock()
        mock_instance.get.return_value = mock_resp
        mock_client.return_value.__aenter__.return_value = mock_instance
        _chain_supabase(mock_supabase, cache_data=[{"latest_version": "18.2.0"}])

        result = await registry_check_node(state)
        assert result["new_version"] is None
        assert result["latest_version"] == "18.2.0"


@pytest.mark.asyncio
async def test_vuln_finds_advisory():
    state = {"package_name": "lodash", "ecosystem": "npm", "latest_version": "4.17.21"}
    with (
        patch("httpx.AsyncClient") as mock_client,
        patch("app.agents.dependency.nodes.supabase") as mock_supabase,
    ):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "vulns": [{"id": "GHSA-1111", "summary": "Prototype pollution in lodash"}]
        }
        mock_instance = AsyncMock()
        mock_instance.post.return_value = mock_resp
        mock_client.return_value.__aenter__.return_value = mock_instance
        _chain_supabase(mock_supabase)

        result = await vuln_check_node(state)
        assert len(result["findings"]) == 1
        assert result["findings"][0]["update_type"] == "security"


@pytest.mark.asyncio
async def test_vuln_no_advisories():
    state = {"package_name": "lodash", "ecosystem": "npm", "latest_version": "4.17.21"}
    with patch("httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"vulns": []}
        mock_instance = AsyncMock()
        mock_instance.post.return_value = mock_resp
        mock_client.return_value.__aenter__.return_value = mock_instance

        result = await vuln_check_node(state)
        assert len(result["findings"]) == 0


@pytest.mark.asyncio
async def test_changelog_finds_release():
    state = {
        "ecosystem": "npm",
        "package_name": "react",
        "new_version": "19.0.0",
        "findings": [],
    }
    with (
        patch("httpx.AsyncClient") as mock_client,
        patch("app.agents.dependency.nodes.supabase") as mock_supabase,
    ):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = """<?xml version="1.0"?>
<feed>
  <entry>
    <title>v19.0.0</title>
    <link href="https://github.com/facebook/react/releases/tag/v19.0.0"/>
    <content>React 19 release with major compiler optimizations</content>
  </entry>
</feed>"""
        mock_instance = AsyncMock()
        mock_instance.get.return_value = mock_resp
        mock_client.return_value.__aenter__.return_value = mock_instance
        _chain_supabase(mock_supabase)

        result = await changelog_fetch_node(state)
        assert len(result["findings"]) == 1
        assert result["findings"][0]["update_type"] == "breaking"


@pytest.mark.asyncio
async def test_changelog_skips_when_no_new_version():
    state = {
        "ecosystem": "npm",
        "package_name": "react",
        "new_version": None,
        "findings": [],
    }
    result = await changelog_fetch_node(state)
    assert result == state


@pytest.mark.asyncio
async def test_changelog_missing_feed_skips_gracefully():
    state = {
        "ecosystem": "npm",
        "package_name": "react",
        "new_version": "19.0.0",
        "findings": [],
    }
    with patch("httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_instance = AsyncMock()
        mock_instance.get.return_value = mock_resp
        mock_client.return_value.__aenter__.return_value = mock_instance

        result = await changelog_fetch_node(state)
        assert result["findings"] == []


@pytest.mark.asyncio
async def test_conditional_buzz_skipped_when_findings_exist():
    state = {
        "package_name": "react",
        "findings": [{"update_type": "release", "summary": "React 19 released"}],
    }
    result = await conditional_buzz_node(state)
    assert len(result["findings"]) == 1
    assert result["findings"][0]["update_type"] == "release"


@pytest.mark.asyncio
async def test_conditional_buzz_runs_when_no_findings():
    state = {"package_name": "unknown-pkg-xyz", "findings": []}
    with patch("app.agents.dependency.nodes.search", AsyncMock(return_value=[
        {"title": "Buzz about unknown-pkg-xyz", "url": "https://example.com/1", "snippet": "Some buzz content"},
    ])):
        result = await conditional_buzz_node(state)
        assert len(result["findings"]) == 1
        assert result["findings"][0]["update_type"] == "buzz"


@pytest.mark.asyncio
async def test_summarize_node():
    fake_llm_response = MagicMock()
    fake_llm_response.content = "React 19 is now available with significant performance improvements."
    with patch("app.agents.dependency.nodes.groq_client") as mock_groq:
        mock_groq.invoke = MagicMock(return_value=fake_llm_response)

        state = {
            "ecosystem": "npm",
            "package_name": "react",
            "new_version": "19.0.0",
            "latest_version": "19.0.0",
            "findings": [
                {"update_type": "release", "summary": "React 19 released", "citations": [{"url": "https://react.dev", "type": "official_docs", "title": "React Blog"}]},
                {"update_type": "breaking", "summary": "Breaking changes in 19.0", "citations": [{"url": "https://github.com/facebook/react/releases", "type": "github", "title": "Release Notes"}]},
            ],
        }
        result = await dep_summarize_node(state)
        assert result["update"] is not None
        assert result["update"]["update_type"] == "breaking"
        assert "performance" in result["update"]["summary"]


@pytest.mark.asyncio
async def test_summarize_no_findings():
    state = {
        "ecosystem": "npm",
        "package_name": "react",
        "findings": [],
    }
    result = await dep_summarize_node(state)
    assert result["update"] is None


def test_save_update_node():
    state = {
        "ecosystem": "npm",
        "package_name": "react",
        "update": {
            "version": "19.0.0",
            "update_type": "release",
            "summary": "React 19 released",
            "citations": [{"type": "blog", "url": "https://react.dev/blog", "title": "React Blog"}],
        },
    }
    with patch("app.agents.dependency.nodes.supabase") as mock_supabase:
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table
        mock_upsert = MagicMock()
        mock_table.upsert.return_value = mock_upsert
        mock_upsert.execute.return_value = MagicMock()

        result = save_update_node(state)
        assert result == state
        mock_table.upsert.assert_called_once()


def test_save_update_no_update():
    state = {"ecosystem": "npm", "package_name": "react", "update": None}
    result = save_update_node(state)
    assert result == state
