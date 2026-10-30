"""Calendar helpers for the tech-events feature.

Uses link/ICS export instead of Google OAuth: an "Add to Google Calendar" URL
works for any Google user with no credentials, and an .ics document (with a
VALARM reminder) imports into Google/Apple/Outlook. Pure + unit-testable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlencode

GCAL_BASE = "https://calendar.google.com/calendar/render"


def _utc_compact(value: str | datetime) -> str:
    """Format as a UTC timestamp Google/ICS accept: 20260131T090000Z."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def google_calendar_url(
    *,
    title: str,
    start: str | datetime,
    end: str | datetime,
    details: str = "",
    location: str = "",
) -> str:
    """Build an 'Add to Google Calendar' link (no OAuth required)."""
    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": f"{_utc_compact(start)}/{_utc_compact(end)}",
    }
    if details:
        params["details"] = details
    if location:
        params["location"] = location
    return f"{GCAL_BASE}?{urlencode(params)}"


def _ics_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def render_ics(events: list[dict], *, reminder_minutes: int = 60) -> str:
    """Render a VCALENDAR with one VEVENT per event, each with a VALARM reminder.

    Each event dict may have: uid, title, start, end, details, location, url.
    """
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Kite//Tech Events//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for i, ev in enumerate(events):
        uid = str(ev.get("uid") or ev.get("url") or f"kite-event-{i}")
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{_ics_escape(uid)}")
        lines.append(f"DTSTART:{_utc_compact(ev['start'])}")
        lines.append(f"DTEND:{_utc_compact(ev['end'])}")
        lines.append(f"SUMMARY:{_ics_escape(str(ev.get('title') or 'Event'))}")
        desc_bits = [str(ev.get("details") or ""), str(ev.get("url") or "")]
        desc = " ".join(b for b in desc_bits if b).strip()
        if desc:
            lines.append(f"DESCRIPTION:{_ics_escape(desc)}")
        if ev.get("location"):
            lines.append(f"LOCATION:{_ics_escape(str(ev['location']))}")
        if ev.get("url"):
            lines.append(f"URL:{_ics_escape(str(ev['url']))}")
        # Reminder.
        lines.append("BEGIN:VALARM")
        lines.append(f"TRIGGER:-PT{int(reminder_minutes)}M")
        lines.append("ACTION:DISPLAY")
        lines.append(f"DESCRIPTION:{_ics_escape(str(ev.get('title') or 'Event'))}")
        lines.append("END:VALARM")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    # RFC 5545 wants CRLF line endings.
    return "\r\n".join(lines) + "\r\n"
