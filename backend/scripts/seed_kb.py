"""Seed kb_articles for every followed interest tag (dev/demo fill)."""
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import supabase
from app.services.kb import resolve_kb_topics

TOPIC_SOURCES: dict[str, dict] = {
    "Frontend": {
        "primary": "https://react.dev/blog/2024/12/05/react-19",
        "blog": ("React 19 blog", "https://react.dev/blog"),
        "github": ("React repository", "https://github.com/facebook/react"),
        "docs": ("React docs", "https://react.dev"),
        "youtube": ("React 19 overview", "https://www.youtube.com/watch?v=lyEKhv8-3n0"),
    },
    "Backend": {
        "primary": "https://fastapi.tiangolo.com/release-notes/",
        "blog": ("FastAPI release notes", "https://fastapi.tiangolo.com"),
        "github": ("FastAPI on GitHub", "https://github.com/tiangolo/fastapi"),
        "docs": ("FastAPI docs", "https://fastapi.tiangolo.com/learn/"),
        "youtube": ("Building APIs with FastAPI", "https://www.youtube.com/watch?v=7t2alSnE2-I"),
    },
    "AI/ML": {
        "primary": "https://huggingface.co/blog",
        "blog": ("Hugging Face blog", "https://huggingface.co/blog"),
        "github": ("Transformers", "https://github.com/huggingface/transformers"),
        "docs": ("HF docs", "https://huggingface.co/docs"),
        "youtube": ("Intro to transformers", "https://www.youtube.com/watch?v=GQQHAty6jDI"),
    },
    "DevOps": {
        "primary": "https://www.docker.com/blog/",
        "blog": ("Docker blog", "https://www.docker.com/blog/"),
        "github": ("Docker docs repo", "https://github.com/docker/docs"),
        "docs": ("Docker docs", "https://docs.docker.com"),
        "youtube": ("Docker in 100 seconds", "https://www.youtube.com/watch?v=Gjnup-PuquQ"),
    },
    "Databases": {
        "primary": "https://www.postgresql.org/about/news/",
        "blog": ("PostgreSQL news", "https://www.postgresql.org/about/news/"),
        "github": ("PostgreSQL", "https://github.com/postgres/postgres"),
        "docs": ("Postgres docs", "https://www.postgresql.org/docs/"),
        "youtube": ("PostgreSQL intro", "https://www.youtube.com/watch?v=qw--VYLpxG4"),
    },
    "Mobile": {
        "primary": "https://reactnative.dev/blog",
        "blog": ("React Native blog", "https://reactnative.dev/blog"),
        "github": ("React Native", "https://github.com/facebook/react-native"),
        "docs": ("RN docs", "https://reactnative.dev/docs/getting-started"),
        "youtube": ("React Native in 100s", "https://www.youtube.com/watch?v=0-S5a0WPX50"),
    },
}

SAMPLES = [
    ("{topic} trends to watch this week", "Quick roundup of what changed in {topic}."),
    ("New {topic} tooling gaining traction", "Developers are adopting fresh libraries and workflows."),
    ("{topic} best practices update", "Community consensus is shifting on architecture patterns."),
    ("Security notes for {topic} teams", "Recent advisories and hardening recommendations."),
    ("Performance tips in {topic}", "Benchmarks and optimization patterns worth knowing."),
    ("{topic} ecosystem release highlights", "Notable version bumps and migration notes."),
    ("Conference talks summarised: {topic}", "Key takeaways from recent meetups and streams."),
    ("Open source spotlight: {topic}", "Projects worth starring and trying locally."),
]


def _body(topic: str, title: str, i: int, src: dict) -> str:
    return (
        f"{title}\n\n"
        f"This briefing covers recent developments in {topic}. Teams are evaluating new "
        f"patterns for reliability, developer experience, and shipping speed.\n\n"
        f"Key points:\n"
        f"• Major releases and RFCs landed in the last week\n"
        f"• Production teams shared migration notes and benchmarks\n"
        f"• Security advisories worth reviewing before your next deploy\n\n"
        f"Primary source: {src['primary']}\n"
        f"Article {i} of 8 in the {topic} knowledgebase window."
    )


def main() -> None:
    topics = [t for t in resolve_kb_topics() if t.topic_kind == "interest"]
    if not topics:
        print("No followed interest tags — nothing to seed.")
        return

    supabase.table("kb_articles").delete().like("body", "Demo KB article%").execute()
    supabase.table("kb_articles").delete().like("body", "This briefing covers recent%").execute()

    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for topic in topics:
        src = TOPIC_SOURCES.get(topic.topic, TOPIC_SOURCES["Frontend"])
        blog_title, blog_url = src["blog"]
        gh_title, gh_url = src["github"]
        docs_title, docs_url = src["docs"]
        yt_title, yt_url = src["youtube"]

        for i, (title_tpl, summary_tpl) in enumerate(SAMPLES, start=1):
            title = title_tpl.format(topic=topic.topic)
            summary = summary_tpl.format(topic=topic.topic)
            citations = [
                {"type": "blog", "url": blog_url, "title": blog_title},
                {"type": "github", "url": gh_url, "title": gh_title},
                {"type": "official_docs", "url": docs_url, "title": docs_title},
            ]
            youtube_url = yt_url if i in (3, 7) else None
            if youtube_url:
                citations.append({"type": "youtube", "url": yt_url, "title": yt_title})

            row = {
                "topic": topic.topic,
                "topic_kind": "interest",
                "tag_id": topic.tag_id,
                "title": title,
                "one_liner": summary,
                "summary": summary + f" See {blog_title} and official docs for details.",
                "body": _body(topic.topic, title, i, src),
                "source_type": "youtube" if youtube_url else "blog",
                "citations": citations,
                "youtube_url": youtube_url,
                "url": src["primary"],
                "fetched_at": now,
            }
            slug = f"{topic.topic.lower().replace('/', '-')}-{uuid.uuid4().hex[:8]}"
            row["url"] = f"{src['primary']}#{slug}"
            supabase.table("kb_articles").insert(row).execute()
            inserted += 1

    print(f"Seeded {inserted} kb_articles across {len(topics)} topic(s): {[t.topic for t in topics]}")


if __name__ == "__main__":
    main()
