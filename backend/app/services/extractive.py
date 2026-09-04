"""Local extractive one-liner for raw-tier cards (no LLM)."""

from __future__ import annotations

import html
import re

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]")
_GIBBERISH_RE = re.compile(r"[<>{}|\\]|&(?:#\d+|#x[\da-f]+|[a-z]+);", re.I)


def clean_snippet(text: str, *, max_len: int = 500) -> str:
    """Strip HTML, decode entities, collapse whitespace, drop obvious garbage."""
    raw = (text or "").strip()
    if not raw:
        return ""

    if "<" in raw and ">" in raw:
        try:
            from bs4 import BeautifulSoup

            raw = BeautifulSoup(raw, "html.parser").get_text(separator=" ", strip=True)
        except Exception:
            raw = _HTML_TAG_RE.sub(" ", raw)

    raw = html.unescape(raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    if not raw:
        return ""

    if _looks_like_gibberish(raw):
        return ""

    return raw[:max_len].rstrip()


def _looks_like_gibberish(text: str) -> bool:
    if _GIBBERISH_RE.search(text):
        return True
    alnum = sum(1 for c in text if c.isalnum())
    if len(text) >= 10 and alnum / len(text) < 0.45:
        return True
    symbols = sum(1 for c in text if not c.isalnum() and not c.isspace())
    if len(text) >= 10 and symbols / len(text) > 0.4:
        return True
    words = [w for w in re.split(r"\W+", text) if len(w) > 2]
    if len(text) >= 40 and len(words) < 3:
        return True
    return False


def is_readable_text(text: str) -> bool:
    """True when text is safe to show as card excerpt."""
    cleaned = clean_snippet(text)
    return bool(cleaned) and not _looks_like_gibberish(cleaned)


def extractive_one_liner(title: str, text: str, *, max_len: int = 160) -> str:
    """Pick the first substantive sentence from body text, else fall back to title."""
    cleaned = clean_snippet(text, max_len=2000)
    if cleaned:
        for match in _SENTENCE_RE.finditer(cleaned):
            sentence = match.group(0).strip()
            if len(sentence) >= 40:
                return sentence[:max_len].rstrip()
        if len(cleaned) >= 20:
            return cleaned[:max_len].rstrip()
    title = (title or "").strip()
    return title[:max_len] if title else "New story collected for your feed."
