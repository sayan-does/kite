"""Unit tests for package-detail what's-new composition."""
from app.services.whats_new import compose_whats_new


def test_up_to_date_returns_none():
    assert compose_whats_new("up_to_date", "1.0.0", "1.0.0", {"kind": "none"}, "ignored", []) is None


def test_prefers_cleaned_headline():
    summary = compose_whats_new(
        "update_available",
        "1.0.0",
        "2.0.0",
        {"kind": "major"},
        "<p>React 19 ships a new compiler.</p>",
        [{"version": "2.0.0", "summary": "Should not win", "is_security": True, "is_breaking": False}],
    )
    assert summary == "React 19 ships a new compiler."
    assert "<" not in summary


def test_stitches_security_then_breaking_timeline_notes():
    summary = compose_whats_new(
        "security",
        "1.0.0",
        "2.0.0",
        {"kind": "major"},
        None,
        [
            {"version": "2.0.0", "summary": "Breaking API rename", "is_security": False, "is_breaking": True},
            {"version": "1.9.0", "summary": "<p>Security fix for XSS</p>", "is_security": True, "is_breaking": False},
            {"version": "1.0.0", "summary": "Tracked release", "is_security": False, "is_breaking": False},
        ],
    )
    assert summary == "Security fix for XSS. Breaking API rename."


def test_fallback_when_no_notes():
    summary = compose_whats_new(
        "update_available",
        "2.0.0",
        "3.0.0",
        {"kind": "major"},
        None,
        [],
    )
    assert summary == (
        "Update available: 2.0.0 → 3.0.0 (major). Release notes are not available yet."
    )
