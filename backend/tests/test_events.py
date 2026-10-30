"""Tests for the tech-events service + endpoints (no DB; HTTP mocked)."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.services.events import parse_events

client = TestClient(app)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

SAMPLE = [
    {"name": "Past Conf", "url": "https://past.example", "startDate": "2025-06-01", "endDate": "2025-06-02"},
    {"name": "KubeCon EU", "hyperlink": "https://kubecon.example", "startDate": "2026-03-19", "endDate": "2026-03-22", "city": "Paris", "country": "France"},
    {"title": "Remote Summit", "url": "https://remote.example", "start": "2026-02-10", "online": True},
    {"name": "", "url": "https://noname.example", "startDate": "2026-05-01"},  # dropped: no title
]


def test_parse_drops_past_and_untitled_and_sorts():
    events = parse_events(SAMPLE, now=NOW)
    titles = [e["title"] for e in events]
    assert titles == ["Remote Summit", "KubeCon EU"]  # sorted by start, past+untitled dropped
    assert events[0]["location"] == "Online"
    assert events[1]["location"] == "Paris, France"
    assert events[1]["end"].startswith("2026-03-22")


def test_parse_handles_events_wrapper_and_epoch():
    data = {"events": [{"name": "Epoch Event", "url": "https://e.example", "startDate": 1772323200}]}
    events = parse_events(data, now=NOW)
    assert len(events) == 1
    assert events[0]["title"] == "Epoch Event"


def test_parse_handles_millisecond_epoch_and_overflow():
    # developers.events uses millisecond epochs; must not raise OSError/overflow.
    ms = [
        {"name": "MS Event", "url": "https://ms.example", "date": [1772323200000, 1772409600000]},
        {"name": "Huge", "url": "https://huge.example", "startDate": 9_999_999_999_999_999},
    ]
    events = parse_events(ms, now=NOW)
    titles = [e["title"] for e in events]
    assert "MS Event" in titles  # ms normalized to a real 2026 date
    # the absurd value coerces to None → dropped, never raised


def test_events_endpoint_adds_calendar_links(monkeypatch):
    async def fake_fetch(*, limit=50, force=False):
        return parse_events(SAMPLE, now=NOW)[:limit]

    monkeypatch.setattr("app.routers.events.fetch_tech_events", fake_fetch)
    resp = client.get("/events?limit=10")
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert events
    assert all("google_calendar_url" in e for e in events)
    assert events[0]["google_calendar_url"].startswith("https://calendar.google.com/calendar/render?")


def test_events_ics_endpoint(monkeypatch):
    async def fake_fetch(*, limit=50, force=False):
        return parse_events(SAMPLE, now=NOW)[:limit]

    monkeypatch.setattr("app.routers.events.fetch_tech_events", fake_fetch)
    resp = client.get("/events.ics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/calendar")
    assert "attachment" in resp.headers.get("content-disposition", "")
    assert "BEGIN:VCALENDAR" in resp.text
    assert "BEGIN:VALARM" in resp.text
