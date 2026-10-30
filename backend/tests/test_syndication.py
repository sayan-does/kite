"""Unit tests for RSS/OPML and calendar serializers (no DB / network)."""

from datetime import datetime, timezone

from app.services.calendars import google_calendar_url, render_ics
from app.services.syndication import render_opml, render_rss


def test_rss_is_well_formed_and_escapes():
    xml = render_rss(
        title="Kite <feed>",
        link="https://kite.app/feed",
        description="My feed & stuff",
        self_url="https://kite.app/feed.rss?key=abc",
        items=[
            {
                "title": "A & B <tag>",
                "url": "https://example.com/post?a=1&b=2",
                "summary": "Body with <html> & amps",
                "published_at": "2026-10-31T09:00:00Z",
            }
        ],
    )
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<rss version=\"2.0\"" in xml
    assert "&amp;" in xml and "&lt;tag&gt;" in xml  # escaped
    assert "<pubDate>" in xml
    assert 'rel="self"' in xml
    # Parses as XML.
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml)
    assert root.tag == "rss"
    assert root.find("./channel/item/title").text == "A & B <tag>"


def test_rss_handles_missing_fields():
    xml = render_rss(title="t", link="l", description="d", items=[{}])
    import xml.etree.ElementTree as ET

    ET.fromstring(xml)  # must not raise
    assert "<title>Untitled</title>" in xml


def test_opml_lists_sources():
    opml = render_opml(
        title="Kite sources",
        sources=[
            {"title": "HN", "url": "https://hn.example/rss", "html_url": "https://hn.example"},
            {"name": "No URL source"},
        ],
    )
    import xml.etree.ElementTree as ET

    root = ET.fromstring(opml)
    outlines = root.findall("./body/outline")
    assert len(outlines) == 2
    assert outlines[0].get("xmlUrl") == "https://hn.example/rss"


def test_google_calendar_url():
    url = google_calendar_url(
        title="KubeCon",
        start=datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 11, 10, 17, 0, tzinfo=timezone.utc),
        location="Online",
    )
    assert url.startswith("https://calendar.google.com/calendar/render?")
    assert "dates=20261110T090000Z%2F20261110T170000Z" in url
    assert "text=KubeCon" in url


def test_ics_has_event_and_alarm():
    ics = render_ics(
        [
            {
                "uid": "evt-1",
                "title": "PyCon; 2026",
                "start": "2026-05-14T08:00:00Z",
                "end": "2026-05-14T18:00:00Z",
                "url": "https://pycon.example",
            }
        ],
        reminder_minutes=30,
    )
    assert "BEGIN:VCALENDAR" in ics and "END:VCALENDAR" in ics
    assert "BEGIN:VEVENT" in ics
    assert "DTSTART:20260514T080000Z" in ics
    assert "SUMMARY:PyCon\\; 2026" in ics  # escaped semicolon
    assert "BEGIN:VALARM" in ics
    assert "TRIGGER:-PT30M" in ics
    assert ics.endswith("\r\n")
