"""Tests for snippet cleaning and extractive one-liners."""

from app.services.extractive import clean_snippet, extractive_one_liner, is_readable_text


def test_clean_snippet_strips_html():
    raw = "<p>React 19 ships with <strong>new compiler</strong> improvements.</p>"
    cleaned = clean_snippet(raw)
    assert "<" not in cleaned
    assert "React 19 ships" in cleaned


def test_clean_snippet_rejects_gibberish():
    raw = "&#x27;&#x27;&#x27; @@@ ### $$$ %%%"
    assert clean_snippet(raw) == ""


def test_clean_snippet_decodes_entities():
    raw = "Tom &amp; Jerry release notes"
    assert clean_snippet(raw) == "Tom & Jerry release notes"


def test_is_readable_text_accepts_text_after_html_stripped():
    assert is_readable_text("<a href='x'>click here for details</a>")


def test_extractive_one_liner_uses_cleaned_sentence():
    title = "React 19 release"
    html = "<p>React 19 introduces a new compiler for faster builds and smaller bundles.</p>"
    one_liner = extractive_one_liner(title, html)
    assert "React 19 introduces" in one_liner
    assert "<" not in one_liner


def test_extractive_one_liner_falls_back_to_title():
    one_liner = extractive_one_liner("Rust 1.80 lands", "&#x27;&#x27;&#x27;")
    assert one_liner == "Rust 1.80 lands"
