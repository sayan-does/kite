import json
import re
from urllib.parse import urlparse

from langchain_core.messages import HumanMessage

from app.agents.common import fetch_article_text, groq_client, search
from app.agents.discovery.research import (
    RESEARCH_OUTLET_DOMAINS,
    apply_research_metadata,
    is_aiml_topic,
    is_curated_outlet,
    qualifies_as_research,
)
from app.config import settings
from app.db import supabase

RELEVANCE_THRESHOLD = 0.25
MAX_FEED_CARDS = 10


def _classify_url(url: str) -> str:
    domain = urlparse(url).netloc.lower()
    if any(d in domain for d in ["github.com", "gitlab."]):
        return "github"
    if any(d in domain for d in ["youtube.com", "youtu.be", "vimeo.com"]):
        return "youtube"
    if any(
        d in domain
        for d in [
            "docs.",
            ".dev",
            "developer.",
            "developers.",
            "api.",
            "mdn.",
            "w3.org",
            "mozilla.org",
            "learn.microsoft.com",
            "python.org",
            "npmjs.com",
            "pypi.org",
            "maven.",
        ]
    ):
        return "official_docs"
    if any(d in domain for d in [".blog", "blog.", "medium.com", "dev.to", "hashnode.", "substack."]):
        return "blog"
    return "blog"


def _topic_label(state: dict) -> str:
    return state.get("topic") or state.get("tag", "")


def _kb_topic_urls(topic: str) -> set[str]:
    rows = (
        supabase.table("kb_articles")
        .select("url")
        .eq("topic", topic)
        .execute()
        .data
        or []
    )
    return {row["url"] for row in rows if row.get("url")}


def _owned_urls(user_id: str) -> set[str]:
    rows = (
        supabase.table("articles")
        .select("citations")
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    )
    urls: set[str] = set()
    for row in rows:
        for citation in row.get("citations") or []:
            url = citation.get("url")
            if url:
                urls.add(url)
    return urls


def _keyword_overlap(text: str, topic: str) -> float:
    topic_words = {w for w in re.split(r"\W+", topic.lower()) if len(w) > 2}
    if not topic_words:
        return 0.0
    text_words = set(re.split(r"\W+", text.lower()))
    return len(topic_words & text_words) / len(topic_words)


def _recency_bonus(snippet: str) -> float:
    if re.search(r"202[4-6]", snippet):
        return 1.0
    return 0.7


def _dedupe_results_preserve_order(results: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for r in results:
        url = (r.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(r)
    return out


async def _search_aiml_three_pass() -> list[dict]:
    """Curated outlets → biased research query → general AI/ML news."""
    site_clause = " OR ".join(f"site:{d}" for d in RESEARCH_OUTLET_DOMAINS)
    curated_query = f"({site_clause}) AI machine learning research OR paper OR model 2026"
    curated_raw = await search(curated_query)
    curated = [r for r in curated_raw if is_curated_outlet(r.get("url", ""))]

    biased_query = (
        "AI ML research paper preprint explained OR arxiv news OR openreview 2026"
    )
    biased_raw = await search(biased_query)
    biased = [
        r
        for r in biased_raw
        if qualifies_as_research(
            r.get("url", ""),
            text=f"{r.get('title', '')} {r.get('snippet', '')}",
        )
    ]

    general_query = "latest news and updates about AI/ML in software development 2026"
    general = await search(general_query)

    return _dedupe_results_preserve_order([*curated, *biased, *general])


async def search_node(state: dict) -> dict:
    tag_name = _topic_label(state)
    if is_aiml_topic(tag_name):
        results = await _search_aiml_three_pass()
    else:
        query = f"latest news and updates about {tag_name} in software development 2026"
        results = await search(query)
    return {**state, "results": results}


def filter_relevance_node(state: dict) -> dict:
    results = state.get("results", [])
    seen_urls = set()
    filtered = []
    for r in results:
        url = r.get("url", "")
        snippet = (r.get("title", "") + " " + r.get("snippet", "")).lower()
        if not url or url in seen_urls:
            continue
        if not snippet or len(snippet.strip()) < 20:
            continue
        seen_urls.add(url)
        filtered.append(r)
    return {**state, "results": filtered}


def heuristic_filter_node(state: dict) -> dict:
    results = state.get("results", [])
    topic = _topic_label(state)
    user_id = state.get("user_id")
    if "owned_urls" in state:
        owned = state["owned_urls"]
    elif user_id:
        owned = _owned_urls(user_id)
    else:
        owned = set()

    scored: list[tuple[float, dict]] = []
    for r in results:
        url = r.get("url", "")
        if not url or url in owned:
            continue
        source_type = _classify_url(url)
        if source_type not in ("official_docs", "github", "blog", "youtube"):
            continue
        text = f"{r.get('title', '')} {r.get('snippet', '')}"
        overlap = _keyword_overlap(text, topic)
        score = overlap * _recency_bonus(text)
        if score >= RELEVANCE_THRESHOLD:
            scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    filtered = [r for _, r in scored]
    return {**state, "results": filtered, "current_candidates": filtered, "candidates": filtered}


async def summarize_node(state: dict) -> dict:
    results = state.get("results", [])
    if not results:
        return {**state, "article": {"title": "", "summary": "", "body": ""}}

    sources_text = "\n".join(
        f"- {r['title']}: {r['snippet'][:500]}" for r in results[:5]
    )
    tag_name = _topic_label(state)
    prompt = (
        f"You are a tech news curator. Based on the following search results about '{tag_name}', "
        "write a short article update.\n\n"
        f"Sources:\n{sources_text}\n\n"
        "Respond in this format:\n"
        "TITLE: <short title>\n"
        "SUMMARY: <1-2 sentence summary>\n"
        "BODY: <2-3 paragraph article body>\n"
    )
    msg = HumanMessage(content=prompt)
    response = groq_client.invoke([msg])
    content = response.content

    title = ""
    summary = ""
    body = ""
    for line in content.split("\n"):
        if line.startswith("TITLE:"):
            title = line.replace("TITLE:", "", 1).strip()
        elif line.startswith("SUMMARY:"):
            summary = line.replace("SUMMARY:", "", 1).strip()
        elif line.startswith("BODY:"):
            body = line.replace("BODY:", "", 1).strip()

    return {**state, "article": {"title": title, "summary": summary, "body": body}}


async def summarize_v2_node(state: dict) -> dict:
    results = state.get("results", [])
    if not results:
        return {**state, "article": {}}

    candidate = results[0]
    url = candidate.get("url", "")
    title = candidate.get("title", "")
    snippet = candidate.get("snippet", "")
    topic = _topic_label(state)

    content = await fetch_article_text(url) if url else None
    if not content:
        content = snippet
    if not content or len(content.strip()) < 20:
        return {**state, "article": {}}

    source_type = _classify_url(url) if url else "blog"
    prompt = (
        f"You are a tech news curator. Summarize this real article about '{topic}'.\n\n"
        f"Title: {title}\nURL: {url}\n\n"
        f"Content:\n{content[:8000]}\n\n"
        "Respond with ONLY valid JSON:\n"
        '{"one_liner": "<single punchy sentence>", '
        '"full_summary": "<2-3 paragraph summary>", '
        f'"source_type": "{source_type}"}}'
    )
    msg = HumanMessage(content=prompt)
    response = groq_client.invoke([msg])
    raw = response.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {**state, "article": {}}

    one_liner = parsed.get("one_liner", "")
    full_summary = parsed.get("full_summary", "")
    st = parsed.get("source_type", source_type)
    if st not in ("official_docs", "github", "blog", "youtube"):
        st = source_type

    if not one_liner or not full_summary:
        return {**state, "article": {}}

    article = {
        "title": title or one_liner[:80],
        "one_liner": one_liner,
        "summary": one_liner,
        "body": full_summary,
        "source_type": st,
        "citations": [{"type": st, "url": url, "title": title}],
    }
    article = apply_research_metadata(article, content or snippet or "")
    return {**state, "article": article}


def citation_extract_node(state: dict) -> dict:
    results = state.get("results", [])
    citations = []
    for r in results:
        url = r.get("url", "")
        if url:
            citations.append({
                "type": _classify_url(url),
                "url": url,
                "title": r.get("title", ""),
            })
    article = dict(state.get("article", {}))
    article["citations"] = citations
    return {**state, "article": article}


async def youtube_embed_node(state: dict) -> dict:
    from app.services.youtube import resolve_youtube_url

    article = dict(state.get("article", {}))
    if not article:
        return state

    yt = await resolve_youtube_url(article)
    if yt:
        article["youtube_url"] = yt
        return {**state, "article": article}
    return state


def save_article_node(state: dict) -> dict:
    article = state.get("article", {})
    tag_id = state.get("tag_id")
    if not article.get("title"):
        return state

    supabase.table("articles").upsert(
        {
            "tag_id": tag_id,
            "title": article["title"],
            "summary": article.get("summary", ""),
            "body": article.get("body"),
            "citations": article.get("citations", []),
            "youtube_url": article.get("youtube_url"),
        },
        on_conflict="id",
    ).execute()
    return state


def save_article_v2_node(state: dict) -> dict:
    article = state.get("article", {})
    user_id = state.get("user_id")
    if not article.get("title") or not user_id:
        return state

    row = {
        "user_id": user_id,
        "title": article["title"],
        "one_liner": article.get("one_liner", ""),
        "summary": article.get("summary", ""),
        "body": article.get("body"),
        "source_type": article.get("source_type"),
        "source": state.get("source"),
        "topic": state.get("topic"),
        "citations": article.get("citations", []),
        "youtube_url": article.get("youtube_url"),
    }
    supabase.table("articles").insert(row).execute()

    count_resp = (
        supabase.table("articles")
        .select("id, fetched_at")
        .eq("user_id", user_id)
        .order("fetched_at", desc=False)
        .execute()
    )
    rows = count_resp.data or []
    if len(rows) > MAX_FEED_CARDS:
        to_delete = rows[: len(rows) - MAX_FEED_CARDS]
        for old in to_delete:
            supabase.table("articles").delete().eq("id", old["id"]).execute()

    open_slots = state.get("open_slots", 0) - 1
    articles_saved = state.get("articles_saved", 0) + 1
    return {
        **state,
        "open_slots": open_slots,
        "articles_saved": articles_saved,
    }


def init_topic_node(state: dict) -> dict:
    topic = state["topic"]
    return {
        **state,
        "open_slots": 10,
        "owned_urls": _kb_topic_urls(topic),
        "cand_idx": 0,
        "candidates": [],
        "results": [],
        "article": {},
    }


def prepare_candidate_node(state: dict) -> dict:
    candidates = state.get("candidates", [])
    idx = state.get("cand_idx", 0)
    if idx >= len(candidates):
        return {**state, "results": []}
    return {**state, "results": [candidates[idx]]}


def save_kb_article_node(state: dict) -> dict:
    article = state.get("article", {})
    topic = state.get("topic")
    topic_kind = state.get("topic_kind")
    tag_id = state.get("tag_id")
    cand_idx = state.get("cand_idx", 0)

    if not article.get("title") or not topic or not topic_kind:
        return {**state, "cand_idx": cand_idx + 1}

    citations = article.get("citations") or []
    url = citations[0].get("url") if citations else None

    row = {
        "topic": topic,
        "topic_kind": topic_kind,
        "tag_id": tag_id,
        "title": article["title"],
        "one_liner": article.get("one_liner", ""),
        "summary": article.get("summary", article.get("one_liner", "")),
        "body": article.get("body"),
        "source_type": article.get("source_type"),
        "citations": citations,
        "youtube_url": article.get("youtube_url"),
        "url": url,
        "is_research": bool(article.get("is_research", False)),
    }

    resp = (
        supabase.table("kb_articles")
        .upsert(row, on_conflict="topic,url", ignore_duplicates=True)
        .execute()
    )
    inserted = bool(resp.data)

    if inserted:
        open_slots = state.get("open_slots", 0) - 1
        return {**state, "open_slots": open_slots, "cand_idx": cand_idx + 1}

    return {**state, "cand_idx": cand_idx + 1}


def route_after_prepare_candidate(state: dict) -> str:
    if state.get("results"):
        return "summarize"
    return "end"


def route_after_save_kb(state: dict) -> str:
    if state.get("open_slots", 0) <= 0:
        return "end"
    candidates = state.get("candidates", [])
    if state.get("cand_idx", 0) >= len(candidates):
        return "end"
    return "prepare"


def init_node(state: dict) -> dict:
    from app.agents.discovery.interest_resolver import resolve_interests

    user_id = state["user_id"]
    existing = (
        supabase.table("articles")
        .select("id")
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    )
    open_slots = max(0, MAX_FEED_CARDS - len(existing))
    ranked = resolve_interests(user_id)
    return {
        **state,
        "open_slots": open_slots,
        "ranked_interests": ranked,
        "interest_idx": 0,
        "articles_saved": 0,
        "current_candidates": [],
        "owned_urls": _owned_urls(user_id),
    }


def select_next_interest_node(state: dict) -> dict:
    ranked = state.get("ranked_interests", [])
    idx = state.get("interest_idx", 0)
    if idx >= len(ranked) or state.get("open_slots", 0) <= 0:
        return {**state, "exhausted": True}

    item = ranked[idx]
    return {
        **state,
        "topic": item.topic,
        "source": item.source,
        "interest_idx": idx + 1,
        "results": [],
        "current_candidates": [],
        "exhausted": False,
    }


def route_after_filter(state: dict) -> str:
    if state.get("results"):
        return "summarize"
    return "select"


def route_after_save(state: dict) -> str:
    if state.get("open_slots", 0) <= 0:
        return "end"
    if state.get("interest_idx", 0) >= len(state.get("ranked_interests", [])):
        return "end"
    return "select"


def route_after_init(state: dict) -> str:
    if state.get("open_slots", 0) <= 0 or not state.get("ranked_interests"):
        return "end"
    return "select"
