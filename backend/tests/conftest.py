import pytest

from app.config import settings

# TestClient starts the app lifespan, which would otherwise fire a real
# multi-category collect against the network and flood kb_articles mid-suite.
settings.PREFILL_ON_STARTUP = False


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "enable_feed_v3: opt out of the autouse FEED_V3 override for this test",
    )


@pytest.fixture(autouse=True)
def disable_feed_v3_unless_overridden(request, monkeypatch):
    """Keep legacy scheduler/discovery tests stable when FEED_V3 is enabled locally."""
    if "enable_feed_v3" in request.keywords:
        return
    monkeypatch.setattr(settings, "FEED_V3", False)
