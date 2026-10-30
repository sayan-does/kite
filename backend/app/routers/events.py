"""Tech-events endpoints: upcoming events with add-to-calendar + .ics export."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.services.calendars import google_calendar_url, render_ics
from app.services.events import fetch_tech_events

router = APIRouter()


def _with_calendar_links(events: list[dict]) -> list[dict]:
    enriched: list[dict] = []
    for ev in events:
        enriched.append(
            {
                **ev,
                "google_calendar_url": google_calendar_url(
                    title=ev["title"],
                    start=ev["start"],
                    end=ev["end"],
                    details=ev.get("url", ""),
                    location=ev.get("location", ""),
                ),
            }
        )
    return enriched


@router.get("/events")
async def get_events(limit: int = Query(30, ge=1, le=100)):
    """Upcoming tech events, each with an 'Add to Google Calendar' link."""
    events = await fetch_tech_events(limit=limit)
    return {"events": _with_calendar_links(events)}


@router.get("/events.ics")
async def get_events_ics(limit: int = Query(30, ge=1, le=100)):
    """Download upcoming events as an .ics calendar (with reminders)."""
    events = await fetch_tech_events(limit=limit)
    ics = render_ics(events, reminder_minutes=60)
    return Response(
        content=ics,
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="kite-tech-events.ics"'},
    )
