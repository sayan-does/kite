"""Unit tests for the derived reading-time estimate on feed cards."""

from app.routers.feed import _reading_minutes


def test_empty_text_is_one_minute():
    assert _reading_minutes({}) == 1
    assert _reading_minutes({"body": "   "}) == 1


def test_short_body_rounds_to_one():
    assert _reading_minutes({"body": "a few words here"}) == 1


def test_prefers_body_over_summary_and_one_liner():
    article = {
        "body": " ".join(["word"] * 400),  # ~2 min
        "summary": "short",
        "one_liner": "short",
    }
    assert _reading_minutes(article) == 2


def test_falls_back_to_summary_then_one_liner():
    assert _reading_minutes({"summary": " ".join(["w"] * 600)}) == 3
    assert _reading_minutes({"one_liner": " ".join(["w"] * 200)}) == 1


def test_longform_scales_with_word_count():
    assert _reading_minutes({"body": " ".join(["w"] * 1000)}) == 5
