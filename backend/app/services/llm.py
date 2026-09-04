"""Role-based LLM provider cascade with a per-cycle spend budget.

Rate limits are enforced per model, so assigning different pipeline stages to
different providers multiplies the free quota available per day. Roles are
mapped by prompt shape: anything carrying article text goes to a provider with
a large tokens-per-minute ceiling, while short high-volume calls go to whatever
is fastest.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from app.config import settings

logger = logging.getLogger(__name__)

Role = Literal["summarize", "cluster", "triage"]

# Reasoning models differ in where they put their scratchpad. gpt-oss-* returns a
# separate `reasoning` field and leaves `content` clean, but qwen3.6-27b inlines
# a <think> block that breaks json.loads.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class BudgetExhausted(RuntimeError):
    """Raised when a cycle has spent its allotted LLM requests or tokens."""


@dataclass
class BudgetGovernor:
    """Caps LLM spend for a single pipeline cycle.

    Ranking and cost control are deliberately the same mechanism: callers walk a
    scored candidate list from the top and stop when the budget is gone, so
    running out degrades quality instead of failing the run.
    """

    max_requests: int = field(default_factory=lambda: settings.LLM_MAX_REQUESTS_PER_CYCLE)
    max_tokens: int = field(default_factory=lambda: settings.LLM_MAX_TOKENS_PER_CYCLE)
    requests_used: int = 0
    tokens_used: int = 0

    def reset_cycle(self) -> None:
        self.requests_used = 0
        self.tokens_used = 0

    @property
    def requests_remaining(self) -> int:
        return max(0, self.max_requests - self.requests_used)

    @property
    def tokens_remaining(self) -> int:
        return max(0, self.max_tokens - self.tokens_used)

    def can_spend(self, estimated_tokens: int) -> bool:
        return (
            self.requests_used + 1 <= self.max_requests
            and self.tokens_used + estimated_tokens <= self.max_tokens
        )

    def try_spend(self, estimated_tokens: int) -> bool:
        """Reserve one request plus estimated tokens. False when exhausted."""
        if not self.can_spend(estimated_tokens):
            return False
        self.requests_used += 1
        self.tokens_used += estimated_tokens
        return True

    def record_actual(self, actual_tokens: int, estimated_tokens: int) -> None:
        """Reconcile a reservation against real usage once known."""
        self.tokens_used += actual_tokens - estimated_tokens
        if self.tokens_used < 0:
            self.tokens_used = 0


budget = BudgetGovernor()


def estimate_tokens(text: str) -> int:
    """Rough 4-chars-per-token heuristic, plus headroom for the completion."""
    return max(1, len(text) // 4) + 512


def _gemini():
    if not settings.GEMINI_API_KEY:
        return None
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError:
        logger.warning("langchain-google-genai not installed; skipping Gemini")
        return None
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=settings.GEMINI_API_KEY,
        temperature=0,
    )


def _groq(model: str | None = None):
    if not settings.GROQ_API_KEY:
        return None
    try:
        from langchain_groq import ChatGroq
    except ImportError:
        logger.warning("langchain-groq not installed; skipping Groq")
        return None
    return ChatGroq(
        model=model or settings.GROQ_MODEL,
        api_key=settings.GROQ_API_KEY,
        temperature=0,
    )


def _openrouter():
    if not settings.OPENROUTER_API_KEY:
        return None
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        logger.warning("langchain-openai not installed; skipping OpenRouter")
        return None
    return ChatOpenAI(
        model=settings.OPENROUTER_MODEL,
        api_key=settings.OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
        temperature=0,
    )


# Long prompts need a large TPM ceiling; short ones do not, so they go to the
# fastest provider first and leave the large-context budget for summarization.
_ROLE_CHAINS: dict[str, list] = {
    "summarize": [_gemini, lambda: _groq(), _openrouter],
    "cluster": [_gemini, lambda: _groq(settings.GROQ_SMALL_MODEL), _openrouter],
    "triage": [lambda: _groq(settings.GROQ_SMALL_MODEL), _gemini, _openrouter],
}


def for_role(role: Role):
    """Return a runnable for this role with the remaining providers as fallbacks.

    Returns None when no provider is configured, so callers can degrade to their
    deterministic path rather than crash at import time.
    """
    builders = _ROLE_CHAINS.get(role, _ROLE_CHAINS["summarize"])
    clients = [client for client in (build() for build in builders) if client is not None]
    if not clients:
        logger.warning("no LLM provider configured for role %s", role)
        return None
    primary, *fallbacks = clients
    if not fallbacks:
        return primary
    return primary.with_fallbacks(fallbacks)


def clean_json_text(raw: str) -> str:
    """Strip reasoning blocks and code fences so json.loads can succeed."""
    if not raw:
        return ""
    text = _THINK_RE.sub("", raw)
    # An unterminated <think> means the model was cut off mid-scratchpad.
    if "<think>" in text.lower():
        text = re.split(r"<think>", text, flags=re.IGNORECASE)[0]
    text = _FENCE_RE.sub("", text).strip()
    # Some models prepend prose before the object; take the outermost braces.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    return text.strip()


def parse_json_response(raw: str) -> dict | None:
    cleaned = clean_json_text(raw)
    if not cleaned:
        return None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


async def ainvoke_role(role: Role, prompt: str, *, governor: BudgetGovernor | None = None):
    """Invoke a role's cascade under the budget. Returns None when unaffordable."""
    gov = governor or budget
    estimated = estimate_tokens(prompt)
    if not gov.try_spend(estimated):
        raise BudgetExhausted(
            f"budget exhausted: {gov.requests_used}/{gov.max_requests} requests, "
            f"{gov.tokens_used}/{gov.max_tokens} tokens"
        )

    client = for_role(role)
    if client is None:
        return None

    from langchain_core.messages import HumanMessage

    response = await client.ainvoke([HumanMessage(content=prompt)])
    actual = _usage_tokens(response)
    if actual:
        gov.record_actual(actual, estimated)
    return response


def _usage_tokens(response) -> int | None:
    meta = getattr(response, "usage_metadata", None) or {}
    total = meta.get("total_tokens")
    return int(total) if total else None
