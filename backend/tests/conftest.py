import pytest

from app.config import settings

# TestClient starts the app lifespan, which would otherwise fire a real
# multi-category collect against the network and flood kb_articles mid-suite.
settings.PREFILL_ON_STARTUP = False


# Test modules that talk to a real Supabase project. They are marked `integration`
# automatically so CI can run the hermetic tier (`-m "not integration"`) on every PR
# and the full suite only against a staging database.
INTEGRATION_MODULES = {
    "test_auth", "test_citation_prefs", "test_cold_topic_fill", "test_delete_me",
    "test_digest", "test_feed", "test_feed_progress", "test_feed_state",
    "test_feed_topic_requirements", "test_interests", "test_mcp", "test_me",
    "test_notifications", "test_prefill", "test_quiz", "test_risk_report",
    "test_saved", "test_scheduler", "test_stack_crud", "test_stack_github_import",
    "test_stack_projects", "test_stack_timeline", "test_stack_upload",
    "test_syndication_endpoints", "test_tags", "test_tinyfish_e2e",
    "test_topic_partitioning_e2e",
}


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "enable_feed_v3: opt out of the autouse FEED_V3 override for this test",
    )
    config.addinivalue_line(
        "markers",
        "integration: needs a real Supabase project (run with `pytest`, skip with `-m 'not integration'`)",
    )


def pytest_collection_modifyitems(items):
    for item in items:
        if item.module.__name__.rsplit(".", 1)[-1] in INTEGRATION_MODULES:
            item.add_marker(pytest.mark.integration)


@pytest.fixture(autouse=True)
def disable_feed_v3_unless_overridden(request, monkeypatch):
    """Keep legacy scheduler/discovery tests stable when FEED_V3 is enabled locally."""
    if "enable_feed_v3" in request.keywords:
        return
    monkeypatch.setattr(settings, "FEED_V3", False)
