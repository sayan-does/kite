"""Compose a 1–2 line “what’s new” blurb for package detail."""
from __future__ import annotations

from typing import Any

from app.services.extractive import clean_snippet
from app.services.version_gap import parse_semver_parts

_MAX_LEN = 300
_MAX_NOTES = 2


def _cap_whats_new(text: str, *, max_len: int = _MAX_LEN) -> str:
    text = (text or "").strip()
    if len(text) > max_len:
        return text[:max_len].rstrip()
    return text


def _version_newer_than(candidate: str | None, tracked: str | None) -> bool:
    if not candidate or candidate == tracked:
        return False
    c_parts = parse_semver_parts(candidate)
    t_parts = parse_semver_parts(tracked)
    if c_parts and t_parts:
        return c_parts > t_parts
    return candidate.strip().lstrip("vV") != (tracked or "").strip().lstrip("vV")


def _fallback_summary(
    tracked: str,
    latest: str | None,
    version_gap: dict[str, Any] | None,
) -> str:
    latest_part = latest or "unknown"
    gap_kind = (version_gap or {}).get("kind")
    if gap_kind in ("major", "minor", "patch"):
        return (
            f"Update available: {tracked} → {latest_part} ({gap_kind}). "
            "Release notes are not available yet."
        )
    return f"Update available: {tracked} → {latest_part}. Release notes are not available yet."


def _timeline_notes(tracked: str, timeline: list[dict]) -> str:
    eligible = []
    for row in timeline:
        version = row.get("version")
        if not _version_newer_than(version, tracked):
            continue
        note = clean_snippet(row.get("summary") or "", max_len=_MAX_LEN)
        if note:
            eligible.append({**row, "_cleaned": note})
    eligible.sort(
        key=lambda r: 0 if r.get("is_security") else 1 if r.get("is_breaking") else 2,
    )
    notes: list[str] = []
    seen: set[str] = set()
    for row in eligible:
        note = row["_cleaned"]
        key = note.lower()
        if key in seen:
            continue
        seen.add(key)
        notes.append(note)
        if len(notes) >= _MAX_NOTES:
            break
    if not notes:
        return ""
    joined = []
    for note in notes:
        text = note.rstrip()
        if text and text[-1] not in ".!?":
            text += "."
        joined.append(text)
    return _cap_whats_new(" ".join(joined))


def compose_whats_new(
    status: str,
    tracked: str,
    latest: str | None,
    version_gap: dict[str, Any] | None,
    headline_summary: str | None,
    timeline: list[dict],
) -> str | None:
    """Return a 1–2 line summary for outdated packages; None when up to date."""
    if status == "up_to_date":
        return None

    cleaned_headline = _cap_whats_new(clean_snippet(headline_summary or "", max_len=_MAX_LEN))
    if cleaned_headline:
        return cleaned_headline

    from_timeline = _timeline_notes(tracked, timeline)
    if from_timeline:
        return from_timeline

    return _fallback_summary(tracked, latest, version_gap)
