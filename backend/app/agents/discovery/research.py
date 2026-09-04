"""AI/ML research-news qualification helpers (soft Research label, not a citation type)."""

from __future__ import annotations

import re
from urllib.parse import urlparse

AIML_TOPIC = "AI/ML"

# Editable curated research-journalism outlets (hostname match, www. stripped).
RESEARCH_OUTLET_DOMAINS: tuple[str, ...] = (
    "huggingface.co",
    "blog.google",
    "deepmind.google",
    "deeplearning.ai",
)

PAPER_HOSTS: tuple[str, ...] = (
    "arxiv.org",
    "openreview.net",
)

_PAPER_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:arxiv\.org|openreview\.net)[^\s\"'<>]*",
    re.IGNORECASE,
)


def is_aiml_topic(topic: str | None) -> bool:
    return (topic or "").strip() == AIML_TOPIC


def hostname(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return ""
    return host.lower().removeprefix("www.")


def _host_matches(url: str, domains: tuple[str, ...]) -> bool:
    host = hostname(url)
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in domains)


def is_curated_outlet(url: str) -> bool:
    return _host_matches(url, RESEARCH_OUTLET_DOMAINS)


def is_paper_url(url: str) -> bool:
    return _host_matches(url, PAPER_HOSTS)


def extract_paper_urls(text: str) -> list[str]:
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in _PAPER_URL_RE.findall(text):
        cleaned = match.rstrip(").,;]")
        if cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    return out


def qualifies_as_research(
    url: str,
    *,
    extra_urls: list[str] | None = None,
    text: str = "",
) -> bool:
    """True if curated outlet or a paper/preprint link is present."""
    if is_curated_outlet(url) or is_paper_url(url):
        return True
    for u in extra_urls or []:
        if is_paper_url(u):
            return True
    if extract_paper_urls(text) or extract_paper_urls(url):
        return True
    # Snippet may mention paper hosts without a full URL
    lowered = (text or "").lower()
    if "arxiv.org" in lowered or "openreview.net" in lowered:
        return True
    return False


def apply_research_metadata(article: dict, content: str = "") -> dict:
    """Mutate/return article with is_research + optional Paper citation(s).

    Paper links are stored as citation type ``blog`` (title ``Paper``) so
    citation prefs stay unchanged — not a new source_type enum value.
    """
    out = dict(article)
    citations = list(out.get("citations") or [])
    primary_url = ""
    if citations:
        primary_url = citations[0].get("url") or ""
    primary_url = primary_url or out.get("url") or ""

    paper_urls = extract_paper_urls(content)
    existing = {c.get("url") for c in citations if c.get("url")}
    for paper_url in paper_urls:
        if paper_url in existing or paper_url == primary_url:
            continue
        citations.append({"type": "blog", "url": paper_url, "title": "Paper"})
        existing.add(paper_url)

    out["citations"] = citations
    out["is_research"] = qualifies_as_research(
        primary_url,
        extra_urls=[c.get("url", "") for c in citations],
        text=content,
    )
    return out
