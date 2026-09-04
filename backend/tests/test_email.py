from unittest.mock import patch

import pytest

from app.config import settings
from app.services.email import send_digest


@pytest.mark.asyncio
async def test_send_digest_builds_correct_payload():
    items = [
        {"type": "article", "title": "React 19 Released", "summary": "New compiler optimizations."},
        {
            "type": "dependency_update",
            "package_name": "lodash",
            "version": "5.0.0",
            "update_type": "release",
            "summary": "Major version bump.",
        },
    ]

    with patch("app.services.email.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "mock-email-id"}

        result = await send_digest("test@example.com", items)

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[0][0]

        assert call_kwargs["from"] == settings.EMAIL_FROM
        assert call_kwargs["to"] == ["test@example.com"]
        assert call_kwargs["subject"] == "Your Kite Daily Digest"
        assert "React 19 Released" in call_kwargs["html"]
        assert "lodash" in call_kwargs["html"]
        assert "release" in call_kwargs["html"]
        assert result == {"id": "mock-email-id"}
