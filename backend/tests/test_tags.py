from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

EXPECTED_TAGS = {
    "Frontend",
    "Backend",
    "AI/ML",
    "DevOps",
    "Security",
    "Automation",
    "Programming Languages",
}

# Removed in 0011 along with their articles; onboarding must never offer them.
REMOVED_TAGS = {"Databases", "Mobile", "Cloud Infra", "Developer Tools"}


def test_list_interest_tags_returns_seven_supported_categories():
    response = client.get("/interest-tags")
    assert response.status_code == 200
    names = {t["name"] for t in response.json()["tags"]}
    assert names == EXPECTED_TAGS


def test_list_interest_tags_excludes_removed_categories():
    response = client.get("/interest-tags")
    names = {t["name"] for t in response.json()["tags"]}
    assert names.isdisjoint(REMOVED_TAGS)
