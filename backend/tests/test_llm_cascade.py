import pytest

from app.services import llm


def test_clean_json_strips_think_block():
    raw = '<think>\nlet me reason about this\n</think>\n{"one_liner": "hi"}'
    assert llm.clean_json_text(raw) == '{"one_liner": "hi"}'


def test_clean_json_strips_code_fence():
    raw = '```json\n{"a": 1}\n```'
    assert llm.clean_json_text(raw) == '{"a": 1}'


def test_clean_json_strips_fence_and_think_together():
    raw = '<think>reasoning</think>\n```json\n{"a": 1}\n```'
    assert llm.parse_json_response(raw) == {"a": 1}


def test_clean_json_handles_unterminated_think():
    # A truncated completion can leave the scratchpad open with no closing tag.
    raw = '{"a": 1}<think>and then I was cut off'
    assert llm.parse_json_response(raw) == {"a": 1}


def test_clean_json_drops_leading_prose():
    raw = 'Here is the JSON you asked for:\n{"a": 1}\nHope that helps.'
    assert llm.parse_json_response(raw) == {"a": 1}


def test_parse_json_returns_none_on_garbage():
    assert llm.parse_json_response("not json at all") is None
    assert llm.parse_json_response("") is None


def test_parse_json_returns_none_for_non_object():
    assert llm.parse_json_response("[1, 2, 3]") is None


def test_for_role_returns_none_when_no_provider(monkeypatch):
    monkeypatch.setattr(llm.settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(llm.settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(llm.settings, "OPENROUTER_API_KEY", "")
    assert llm.for_role("summarize") is None


def test_for_role_single_provider_has_no_fallbacks(monkeypatch):
    sentinel = object()
    monkeypatch.setitem(llm._ROLE_CHAINS, "summarize", [lambda: sentinel, lambda: None])
    assert llm.for_role("summarize") is sentinel


def test_for_role_chains_fallbacks_in_order(monkeypatch):
    class FakeClient:
        def __init__(self, name):
            self.name = name
            self.fallbacks = None

        def with_fallbacks(self, fallbacks):
            self.fallbacks = fallbacks
            return self

    primary, second, third = FakeClient("a"), FakeClient("b"), FakeClient("c")
    monkeypatch.setitem(
        llm._ROLE_CHAINS,
        "summarize",
        [lambda: primary, lambda: second, lambda: third],
    )
    result = llm.for_role("summarize")
    assert result is primary
    assert [c.name for c in primary.fallbacks] == ["b", "c"]


def test_for_role_skips_unconfigured_providers(monkeypatch):
    class FakeClient:
        def with_fallbacks(self, fallbacks):
            self.fallbacks = fallbacks
            return self

    only = FakeClient()
    monkeypatch.setitem(
        llm._ROLE_CHAINS,
        "triage",
        [lambda: None, lambda: only, lambda: None],
    )
    assert llm.for_role("triage") is only


@pytest.mark.asyncio
async def test_ainvoke_role_raises_when_budget_exhausted():
    gov = llm.BudgetGovernor(max_requests=0, max_tokens=0)
    with pytest.raises(llm.BudgetExhausted):
        await llm.ainvoke_role("summarize", "prompt", governor=gov)


@pytest.mark.asyncio
async def test_ainvoke_role_returns_none_without_provider(monkeypatch):
    monkeypatch.setattr(llm, "for_role", lambda role: None)
    gov = llm.BudgetGovernor(max_requests=5, max_tokens=100_000)
    assert await llm.ainvoke_role("summarize", "prompt", governor=gov) is None
