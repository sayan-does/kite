import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.common import fetch_article_text

FIXTURE_HTML = """
<html><head><title>Test</title></head><body>
<nav>Menu</nav>
<article><h1>React 19 Released</h1><p>Major update with compiler improvements and new hooks.</p></article>
<footer>Footer</footer>
</body></html>
"""


@pytest.mark.asyncio
async def test_extracts_body_text_from_fixture():
    mock_resp = MagicMock()
    mock_resp.text = FIXTURE_HTML
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        text = await fetch_article_text("https://example.com/article")

    assert text is not None
    assert "React 19 Released" in text
    assert "compiler improvements" in text


@pytest.mark.asyncio
async def test_returns_none_on_fetch_error():
    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("network error")
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        text = await fetch_article_text("https://example.com/fail")

    assert text is None
