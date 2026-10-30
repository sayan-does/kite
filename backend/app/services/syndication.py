"""Pure RSS 2.0 / OPML serializers for the personal-feed export feature.

Kept dependency-free (plain dicts in, str out) so it is trivially unit-testable
without a database or network. The authenticated endpoints that call these live
in the feed/me routers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape, quoteattr

RFC822 = "%a, %d %b %Y %H:%M:%S %z"


def _rfc822(value: str | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return format_datetime(value)


def render_rss(
    *,
    title: str,
    link: str,
    description: str,
    items: list[dict],
    self_url: str | None = None,
) -> str:
    """Render an RSS 2.0 document.

    Each item dict may have: title, url, summary/description, published_at, guid.
    """
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "<channel>",
        f"<title>{escape(title)}</title>",
        f"<link>{escape(link)}</link>",
        f"<description>{escape(description)}</description>",
    ]
    if self_url:
        parts.append(f'<atom:link href={quoteattr(self_url)} rel="self" type="application/rss+xml"/>')

    for item in items:
        item_title = escape(str(item.get("title") or "Untitled"))
        item_url = str(item.get("url") or item.get("link") or "")
        body = str(item.get("summary") or item.get("description") or "")
        parts.append("<item>")
        parts.append(f"<title>{item_title}</title>")
        if item_url:
            parts.append(f"<link>{escape(item_url)}</link>")
            # isPermaLink=false: the URL is the identity but may change host.
            guid = escape(str(item.get("guid") or item_url))
            parts.append(f'<guid isPermaLink="false">{guid}</guid>')
        if body:
            parts.append(f"<description>{escape(body)}</description>")
        pub = _rfc822(item.get("published_at"))
        if pub:
            parts.append(f"<pubDate>{pub}</pubDate>")
        parts.append("</item>")

    parts.extend(["</channel>", "</rss>"])
    return "\n".join(parts)


def render_opml(*, title: str, sources: list[dict]) -> str:
    """Render an OPML 2.0 outline of feed sources.

    Each source dict may have: title/name, url (xmlUrl), html_url (htmlUrl).
    """
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<opml version="2.0">',
        "<head>",
        f"<title>{escape(title)}</title>",
        "</head>",
        "<body>",
    ]
    for src in sources:
        name = escape(str(src.get("title") or src.get("name") or src.get("url") or "source"))
        attrs = [f"text={quoteattr(name)}", 'type="rss"']
        xml_url = src.get("url") or src.get("xml_url")
        if xml_url:
            attrs.append(f"xmlUrl={quoteattr(str(xml_url))}")
        html_url = src.get("html_url") or src.get("htmlUrl")
        if html_url:
            attrs.append(f"htmlUrl={quoteattr(str(html_url))}")
        parts.append(f"<outline {' '.join(attrs)}/>")
    parts.extend(["</body>", "</opml>"])
    return "\n".join(parts)
