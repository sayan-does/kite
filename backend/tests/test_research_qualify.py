from app.agents.discovery.research import (
    apply_research_metadata,
    extract_paper_urls,
    is_aiml_topic,
    is_curated_outlet,
    is_paper_url,
    qualifies_as_research,
)


def test_is_aiml_topic():
    assert is_aiml_topic("AI/ML") is True
    assert is_aiml_topic(" AI/ML ") is True
    assert is_aiml_topic("React") is False
    assert is_aiml_topic(None) is False


def test_curated_outlet_hosts():
    assert is_curated_outlet("https://huggingface.co/blog/transformers") is True
    assert is_curated_outlet("https://www.deeplearning.ai/the-batch/") is True
    assert is_curated_outlet("https://blog.google/technology/ai/gemini") is True
    assert is_curated_outlet("https://deepmind.google/blog/foo") is True
    assert is_curated_outlet("https://medium.com/some-post") is False


def test_paper_url_and_extract():
    assert is_paper_url("https://arxiv.org/abs/2401.12345") is True
    assert is_paper_url("https://openreview.net/forum?id=abc") is True
    assert is_paper_url("https://example.com/arxiv-mirror") is False
    text = "See https://arxiv.org/abs/2401.12345 and also https://openreview.net/forum?id=xyz."
    papers = extract_paper_urls(text)
    assert papers[0].startswith("https://arxiv.org/")
    assert papers[1].startswith("https://openreview.net/")


def test_qualifies_as_research():
    assert qualifies_as_research("https://huggingface.co/papers/foo") is True
    assert qualifies_as_research(
        "https://techcrunch.com/ai",
        extra_urls=["https://arxiv.org/abs/1"],
    ) is True
    assert qualifies_as_research(
        "https://techcrunch.com/ai",
        text="New work on https://arxiv.org/abs/2401.1",
    ) is True
    assert qualifies_as_research(
        "https://techcrunch.com/ai",
        text="Discusses an arxiv.org preprint today",
    ) is True
    assert qualifies_as_research("https://techcrunch.com/ai", text="plain news") is False


def test_apply_research_metadata_adds_paper_citation():
    article = {
        "title": "Explainer",
        "source_type": "blog",
        "citations": [
            {"type": "blog", "url": "https://example.com/post", "title": "Explainer"},
        ],
    }
    enriched = apply_research_metadata(
        article,
        "See the paper at https://arxiv.org/abs/2401.99999 for details.",
    )
    assert enriched["is_research"] is True
    assert any(c.get("title") == "Paper" for c in enriched["citations"])
    assert enriched["citations"][0]["url"] == "https://example.com/post"
