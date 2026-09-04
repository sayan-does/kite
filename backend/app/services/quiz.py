"""Generation for the daily quiz: niche topics and multiple-choice questions.

Questions test general knowledge of a niche rather than the day's headlines, so
a user can play while their feed is still being built. Both generators fall
back to a static bank, because the quiz gates a streak and must not be
unavailable just because an LLM provider is rate-limited.
"""

from __future__ import annotations

import json
import logging
import random

from app.services.llm import BudgetExhausted, ainvoke_role, clean_json_text

logger = logging.getLogger(__name__)

QUESTIONS_PER_QUIZ = 3
OPTIONS_PER_QUESTION = 4
NICHE_OPTIONS = 3
PASS_THRESHOLD = 2

# Used when no provider answers usefully. Keyed by category name, matching the
# interest_tags seed.
_NICHE_BANK: dict[str, list[str]] = {
    "Frontend": [
        "CSS layout and container queries",
        "React rendering and hooks",
        "Web performance and Core Web Vitals",
        "Accessibility and semantic HTML",
        "Browser APIs and the DOM",
    ],
    "Backend": [
        "REST and API design",
        "Caching and queues",
        "Authentication and sessions",
        "Database transactions and indexing",
        "Concurrency and async runtimes",
    ],
    "AI/ML": [
        "Transformer architecture",
        "Prompting and context windows",
        "Embeddings and vector search",
        "Model evaluation and benchmarks",
        "Fine-tuning and quantization",
    ],
    "DevOps": [
        "Kubernetes objects and scheduling",
        "Docker images and layers",
        "CI/CD pipelines",
        "Infrastructure as code",
        "Observability and tracing",
    ],
    "Security": [
        "Web vulnerabilities and OWASP",
        "TLS and certificates",
        "Authentication and OAuth flows",
        "Cryptography basics",
        "Supply chain and dependency risk",
    ],
    "Automation": [
        "Browser automation with Playwright",
        "Workflow orchestration and n8n",
        "Web scraping and parsing",
        "Scheduling, cron and webhooks",
        "CI automation and bots",
    ],
    "Programming Languages": [
        "Go concurrency and goroutines",
        "Rust ownership and borrowing",
        "Python typing and the data model",
        "TypeScript generics and inference",
        "Memory management across languages",
    ],
}

_GENERIC_NICHES = [
    "Version control and Git internals",
    "Testing strategies",
    "System design fundamentals",
    "Networking and HTTP",
    "Data structures and complexity",
]

# Deliberately small: this exists so the streak still works during an outage,
# not as a content library.
_QUESTION_BANK: list[dict] = [
    {
        "question": "In HTTP, which status code indicates the requested resource was not found?",
        "options": ["301", "404", "500", "204"],
        "correct_index": 1,
    },
    {
        "question": "What does the 'S' in HTTPS provide?",
        "options": [
            "Server-side rendering",
            "An encrypted transport layer",
            "Static file caching",
            "Session persistence",
        ],
        "correct_index": 1,
    },
    {
        "question": "Which Git command creates a new commit that undoes an earlier one?",
        "options": ["git reset", "git revert", "git rebase", "git stash"],
        "correct_index": 1,
    },
    {
        "question": "What is the average time complexity of a lookup in a hash table?",
        "options": ["O(1)", "O(log n)", "O(n)", "O(n log n)"],
        "correct_index": 0,
    },
    {
        "question": "In JSON, which of these is not a valid value type?",
        "options": ["null", "number", "undefined", "boolean"],
        "correct_index": 2,
    },
    {
        "question": "Which HTTP method is expected to be idempotent?",
        "options": ["POST", "PUT", "PATCH", "CONNECT"],
        "correct_index": 1,
    },
]


def fallback_niches(categories: list[str]) -> list[str]:
    pool: list[str] = []
    for category in categories:
        pool.extend(_NICHE_BANK.get(category, []))
    if not pool:
        pool = list(_GENERIC_NICHES)
    return random.sample(pool, min(NICHE_OPTIONS, len(pool)))


def fallback_questions() -> list[dict]:
    picked = random.sample(_QUESTION_BANK, QUESTIONS_PER_QUIZ)
    return [dict(q) for q in picked]


def _parse_list(raw: str, key: str) -> list | None:
    """Read a JSON object with a single list under `key`.

    parse_json_response only accepts objects, and models sometimes return a
    bare array, so both shapes are handled here.
    """
    cleaned = clean_json_text(raw)
    if not cleaned:
        # clean_json_text trims to the outermost braces, which discards a bare
        # top-level array; retry against the original text.
        cleaned = (raw or "").strip().strip("`")
        start, end = cleaned.find("["), cleaned.rfind("]")
        if start == -1 or end <= start:
            return None
        cleaned = cleaned[start : end + 1]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        value = parsed.get(key)
        return value if isinstance(value, list) else None
    return None


def _valid_niches(candidates: list) -> list[str]:
    seen: list[str] = []
    for item in candidates:
        text = item.strip() if isinstance(item, str) else ""
        if not text or len(text) > 80:
            continue
        if text.lower() in {s.lower() for s in seen}:
            continue
        seen.append(text)
    return seen[:NICHE_OPTIONS]


async def generate_niches(categories: list[str]) -> list[str]:
    """Three niche topics drawn from the user's categories."""
    if not categories:
        return fallback_niches(categories)

    prompt = (
        f"Categories: {', '.join(categories)}.\n\n"
        f"Pick {NICHE_OPTIONS} distinct, specific technical sub-topics a developer "
        "could be quizzed on. Each must be at most 6 words and drawn from the "
        "categories above.\n"
        'Reply with JSON only: {"niches": ["...", "...", "..."]}'
    )

    try:
        resp = await ainvoke_role("triage", prompt)
    except BudgetExhausted:
        logger.info("niche generation skipped: LLM budget exhausted")
        return fallback_niches(categories)
    except Exception:
        logger.warning("niche generation failed", exc_info=True)
        return fallback_niches(categories)

    if resp is None:
        return fallback_niches(categories)

    parsed = _parse_list(getattr(resp, "content", "") or "", "niches")
    niches = _valid_niches(parsed or [])
    if len(niches) < NICHE_OPTIONS:
        return fallback_niches(categories)
    return niches


def _valid_questions(candidates: list) -> list[dict]:
    """Keep only well-formed questions: 4 distinct options and an in-range answer."""
    valid: list[dict] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        question = item.get("question")
        options = item.get("options")
        index = item.get("correct_index")

        if not isinstance(question, str) or not question.strip():
            continue
        if not isinstance(options, list) or len(options) != OPTIONS_PER_QUESTION:
            continue
        if not all(isinstance(o, str) and o.strip() for o in options):
            continue
        if len({o.strip().lower() for o in options}) != OPTIONS_PER_QUESTION:
            continue
        if isinstance(index, bool) or not isinstance(index, int):
            continue
        if not 0 <= index < OPTIONS_PER_QUESTION:
            continue

        valid.append({
            "question": question.strip(),
            "options": [o.strip() for o in options],
            "correct_index": index,
        })
    return valid


async def generate_questions(niche: str, *, attempts: int = 2) -> list[dict]:
    """Three validated multiple-choice questions about `niche`."""
    prompt = (
        f"Topic: {niche}\n\n"
        f"Write {QUESTIONS_PER_QUIZ} multiple-choice questions testing a developer's "
        f"knowledge of this topic. Each needs exactly {OPTIONS_PER_QUESTION} distinct "
        "options with exactly one correct answer. Vary which position is correct. "
        "Do not reference recent news or dates.\n"
        'Reply with JSON only: {"questions": [{"question": "...", '
        '"options": ["a", "b", "c", "d"], "correct_index": 0}]}'
    )

    for attempt in range(attempts):
        try:
            resp = await ainvoke_role("summarize", prompt)
        except BudgetExhausted:
            logger.info("question generation skipped: LLM budget exhausted")
            break
        except Exception:
            logger.warning("question generation failed (attempt %d)", attempt + 1, exc_info=True)
            continue

        if resp is None:
            break

        parsed = _parse_list(getattr(resp, "content", "") or "", "questions")
        questions = _valid_questions(parsed or [])
        if len(questions) >= QUESTIONS_PER_QUIZ:
            return questions[:QUESTIONS_PER_QUIZ]
        logger.warning(
            "question generation returned %d valid questions (attempt %d)",
            len(questions),
            attempt + 1,
        )

    return fallback_questions()
