from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.services.kb import cleanup_knowledgebase


def test_cleanup_deletes_rows_older_than_retention():
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)

    with (
        patch("app.services.kb.settings") as mock_settings,
        patch("app.services.kb.supabase") as mock_supabase,
    ):
        mock_settings.KB_RETENTION_DAYS = 14
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table
        mock_lt = MagicMock()
        mock_table.delete.return_value = mock_lt
        mock_lt.lt.return_value = mock_lt
        mock_lt.execute.return_value = MagicMock()

        cleanup_knowledgebase()

    mock_table.delete.assert_called_once()
    mock_lt.lt.assert_called_once()
    arg_name, arg_value = mock_lt.lt.call_args[0]
    assert arg_name == "fetched_at"
    parsed = datetime.fromisoformat(arg_value.replace("Z", "+00:00"))
    assert parsed < datetime.now(timezone.utc)
    assert parsed > cutoff - timedelta(minutes=1)
