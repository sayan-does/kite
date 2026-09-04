"""Quiz generation validation and the graded end-to-end flow.

The LLM is always stubbed. Generation tests exercise the parser and validator
directly; the endpoint tests run against the real database with a throwaway
user so the one-attempt-per-day constraint is genuinely tested.
"""

import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import supabase
from app.main import app
from app.services import quiz as quiz_service
from app.services.llm import BudgetExhausted

client = TestClient(app)


@pytest.fixture(autouse=True)
def enable_quiz(monkeypatch):
    monkeypatch.setattr(settings, "QUIZ_ENABLED", True)


def test_quiz_disabled_when_flag_off(monkeypatch, quiz_user):
    monkeypatch.setattr(settings, "QUIZ_ENABLED", False)
    response = client.get("/quiz/today", headers=quiz_user["headers"])
    assert response.status_code == 200
    assert response.json() == {"enabled": False}

    assert client.post("/quiz/start", headers=quiz_user["headers"]).status_code == 404


def _reply(content: str):
    return SimpleNamespace(content=content)


# ---------------------------------------------------------------------------
# Niche generation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_niches_uses_model_output(monkeypatch):
    async def fake(role, prompt):
        return _reply('{"niches": ["CSS container queries", "React hooks", "Web vitals"]}')

    monkeypatch.setattr(quiz_service, "ainvoke_role", fake)
    niches = await quiz_service.generate_niches(["Frontend"])
    assert niches == ["CSS container queries", "React hooks", "Web vitals"]


@pytest.mark.asyncio
async def test_generate_niches_accepts_a_bare_array(monkeypatch):
    async def fake(role, prompt):
        return _reply('["Goroutines", "Ownership", "Type inference"]')

    monkeypatch.setattr(quiz_service, "ainvoke_role", fake)
    assert len(await quiz_service.generate_niches(["Programming Languages"])) == 3


@pytest.mark.asyncio
async def test_generate_niches_falls_back_when_too_few_returned(monkeypatch):
    async def fake(role, prompt):
        return _reply('{"niches": ["Only one"]}')

    monkeypatch.setattr(quiz_service, "ainvoke_role", fake)
    niches = await quiz_service.generate_niches(["DevOps"])
    assert len(niches) == quiz_service.NICHE_OPTIONS
    assert set(niches) <= set(quiz_service._NICHE_BANK["DevOps"])


@pytest.mark.asyncio
async def test_generate_niches_falls_back_on_budget_exhaustion(monkeypatch):
    async def fake(role, prompt):
        raise BudgetExhausted("out of budget")

    monkeypatch.setattr(quiz_service, "ainvoke_role", fake)
    niches = await quiz_service.generate_niches(["Security"])
    assert len(niches) == quiz_service.NICHE_OPTIONS


@pytest.mark.asyncio
async def test_generate_niches_deduplicates(monkeypatch):
    async def fake(role, prompt):
        return _reply('{"niches": ["Docker", "docker", "Helm", "Tracing"]}')

    monkeypatch.setattr(quiz_service, "ainvoke_role", fake)
    niches = await quiz_service.generate_niches(["DevOps"])
    assert niches == ["Docker", "Helm", "Tracing"]


# ---------------------------------------------------------------------------
# Question generation
# ---------------------------------------------------------------------------

_GOOD_QUESTIONS = """
{"questions": [
  {"question": "Q1?", "options": ["a", "b", "c", "d"], "correct_index": 0},
  {"question": "Q2?", "options": ["e", "f", "g", "h"], "correct_index": 3},
  {"question": "Q3?", "options": ["i", "j", "k", "l"], "correct_index": 1}
]}
"""


@pytest.mark.asyncio
async def test_generate_questions_returns_validated_set(monkeypatch):
    async def fake(role, prompt):
        return _reply(_GOOD_QUESTIONS)

    monkeypatch.setattr(quiz_service, "ainvoke_role", fake)
    questions = await quiz_service.generate_questions("React hooks")
    assert len(questions) == quiz_service.QUESTIONS_PER_QUIZ
    for q in questions:
        assert len(q["options"]) == quiz_service.OPTIONS_PER_QUESTION
        assert 0 <= q["correct_index"] < quiz_service.OPTIONS_PER_QUESTION


@pytest.mark.asyncio
async def test_generate_questions_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def fake(role, prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            return _reply('{"questions": [{"question": "bad", "options": ["a"], "correct_index": 0}]}')
        return _reply(_GOOD_QUESTIONS)

    monkeypatch.setattr(quiz_service, "ainvoke_role", fake)
    questions = await quiz_service.generate_questions("Kubernetes")
    assert calls["n"] == 2
    assert [q["question"] for q in questions] == ["Q1?", "Q2?", "Q3?"]


@pytest.mark.asyncio
async def test_generate_questions_falls_back_to_static_bank(monkeypatch):
    async def fake(role, prompt):
        return _reply("not json at all")

    monkeypatch.setattr(quiz_service, "ainvoke_role", fake)
    questions = await quiz_service.generate_questions("Anything")
    assert len(questions) == quiz_service.QUESTIONS_PER_QUIZ
    bank = {q["question"] for q in quiz_service._QUESTION_BANK}
    assert {q["question"] for q in questions} <= bank


def test_validator_rejects_out_of_range_answer_index():
    assert quiz_service._valid_questions([
        {"question": "Q?", "options": ["a", "b", "c", "d"], "correct_index": 4},
    ]) == []


def test_validator_rejects_wrong_option_count():
    assert quiz_service._valid_questions([
        {"question": "Q?", "options": ["a", "b", "c"], "correct_index": 0},
    ]) == []


def test_validator_rejects_duplicate_options():
    # Duplicates mean more than one option could be defended as correct.
    assert quiz_service._valid_questions([
        {"question": "Q?", "options": ["a", "a", "b", "c"], "correct_index": 0},
    ]) == []


def test_validator_rejects_boolean_masquerading_as_index():
    assert quiz_service._valid_questions([
        {"question": "Q?", "options": ["a", "b", "c", "d"], "correct_index": True},
    ]) == []


def test_fallback_niches_are_generic_for_an_unknown_category():
    niches = quiz_service.fallback_niches(["Not A Category"])
    assert len(niches) == quiz_service.NICHE_OPTIONS
    assert set(niches) <= set(quiz_service._GENERIC_NICHES)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
def quiz_user():
    """A fresh user per test, since one quiz session per UTC day is the rule."""
    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users"
    admin_headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    email = f"quiz-test-{uuid.uuid4().hex[:8]}@example.com"
    password = uuid.uuid4().hex
    resp = httpx.post(
        url,
        headers=admin_headers,
        json={"email": email, "password": password, "email_confirm": True},
    )
    resp.raise_for_status()
    user_id = resp.json()["id"]

    sign_in = httpx.post(
        f"{settings.SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": settings.SUPABASE_ANON_KEY, "Content-Type": "application/json"},
        json={"email": email, "password": password},
    )
    sign_in.raise_for_status()
    token = sign_in.json()["access_token"]

    client.post("/auth/callback", json={"access_token": token})

    yield {"id": user_id, "headers": {"Authorization": f"Bearer {token}"}}

    try:
        supabase.table("quiz_sessions").delete().eq("user_id", user_id).execute()
        supabase.table("user_streaks").delete().eq("user_id", user_id).execute()
        httpx.delete(f"{url}/{user_id}", headers=admin_headers)
    except Exception:
        pass


@pytest.fixture
def stub_llm(monkeypatch):
    async def fake_niches(categories):
        return ["Niche A", "Niche B", "Niche C"]

    async def fake_questions(niche, **kwargs):
        return [
            {"question": "Q1?", "options": ["a", "b", "c", "d"], "correct_index": 0},
            {"question": "Q2?", "options": ["e", "f", "g", "h"], "correct_index": 1},
            {"question": "Q3?", "options": ["i", "j", "k", "l"], "correct_index": 2},
        ]

    monkeypatch.setattr("app.routers.quiz.generate_niches", fake_niches)
    monkeypatch.setattr("app.routers.quiz.generate_questions", fake_questions)


def _start_and_pick(headers) -> dict:
    started = client.post("/quiz/start", headers=headers)
    assert started.status_code == 200, started.text
    niche = started.json()["niche_options"][0]
    picked = client.post("/quiz/niche", json={"niche": niche}, headers=headers)
    assert picked.status_code == 200, picked.text
    return picked.json()


def test_quiz_today_before_starting(quiz_user):
    response = client.get("/quiz/today", headers=quiz_user["headers"])
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "not_started"
    assert data["streak"]["current_streak"] == 0


def test_quiz_requires_auth():
    assert client.get("/quiz/today").status_code in (401, 403)


def test_quiz_start_requires_a_category(quiz_user, stub_llm):
    response = client.post("/quiz/start", headers=quiz_user["headers"])
    assert response.status_code == 400


def test_quiz_start_offers_three_niches(quiz_user, stub_llm):
    headers = quiz_user["headers"]
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)

    response = client.post("/quiz/start", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "niche_pending"
    assert len(data["niche_options"]) == 3


def test_quiz_questions_hide_the_answer_until_submitted(quiz_user, stub_llm):
    headers = quiz_user["headers"]
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)

    data = _start_and_pick(headers)
    assert data["state"] == "questions_ready"
    assert len(data["questions"]) == 3
    for question in data["questions"]:
        assert "correct_index" not in question
        assert len(question["options"]) == 4


def test_quiz_rejects_a_niche_that_was_not_offered(quiz_user, stub_llm):
    headers = quiz_user["headers"]
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)
    client.post("/quiz/start", headers=headers)

    response = client.post("/quiz/niche", json={"niche": "Something Else"}, headers=headers)
    assert response.status_code == 400


def test_quiz_submit_grades_server_side_and_awards_streak(quiz_user, stub_llm):
    headers = quiz_user["headers"]
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)
    _start_and_pick(headers)

    response = client.post("/quiz/submit", json={"answers": [0, 1, 2]}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["correct_count"] == 3
    assert data["passed"] is True
    assert data["streak"]["current_streak"] == 1
    assert all(q["is_correct"] for q in data["questions"])
    assert all("correct_index" in q for q in data["questions"])


def test_quiz_two_of_three_still_passes(quiz_user, stub_llm):
    headers = quiz_user["headers"]
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)
    _start_and_pick(headers)

    response = client.post("/quiz/submit", json={"answers": [0, 1, 0]}, headers=headers)
    data = response.json()
    assert data["correct_count"] == 2
    assert data["passed"] is True
    assert data["streak"]["current_streak"] == 1


def test_quiz_one_of_three_fails_and_leaves_streak_at_zero(quiz_user, stub_llm):
    headers = quiz_user["headers"]
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)
    _start_and_pick(headers)

    response = client.post("/quiz/submit", json={"answers": [0, 0, 0]}, headers=headers)
    data = response.json()
    assert data["correct_count"] == 1
    assert data["passed"] is False
    assert data["streak"]["current_streak"] == 0


def test_quiz_resubmitting_returns_the_stored_result(quiz_user, stub_llm):
    headers = quiz_user["headers"]
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)
    _start_and_pick(headers)

    first = client.post("/quiz/submit", json={"answers": [0, 1, 0]}, headers=headers).json()
    second = client.post("/quiz/submit", json={"answers": [0, 1, 2]}, headers=headers).json()

    # A second submit must not upgrade the score or re-award the streak.
    assert second["correct_count"] == first["correct_count"] == 2
    assert second["streak"]["current_streak"] == 1


def test_quiz_start_after_submitting_returns_the_spent_session(quiz_user, stub_llm):
    headers = quiz_user["headers"]
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)
    _start_and_pick(headers)
    client.post("/quiz/submit", json={"answers": [0, 1, 2]}, headers=headers)

    response = client.post("/quiz/start", headers=headers)
    assert response.status_code == 200
    assert response.json()["state"] == "submitted"


def test_quiz_niche_after_submitting_returns_409(quiz_user, stub_llm):
    headers = quiz_user["headers"]
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)
    data = _start_and_pick(headers)
    client.post("/quiz/submit", json={"answers": [0, 1, 2]}, headers=headers)

    response = client.post("/quiz/niche", json={"niche": data["niche"]}, headers=headers)
    assert response.status_code == 409


def test_quiz_submit_before_choosing_a_niche_returns_409(quiz_user, stub_llm):
    headers = quiz_user["headers"]
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)
    client.post("/quiz/start", headers=headers)

    response = client.post("/quiz/submit", json={"answers": [0, 0, 0]}, headers=headers)
    assert response.status_code == 409


def test_quiz_submit_without_a_session_returns_404(quiz_user, stub_llm):
    response = client.post("/quiz/submit", json={"answers": [0, 0, 0]}, headers=quiz_user["headers"])
    assert response.status_code == 404


def test_quiz_submit_rejects_wrong_answer_count(quiz_user, stub_llm):
    headers = quiz_user["headers"]
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)
    _start_and_pick(headers)

    assert client.post("/quiz/submit", json={"answers": [0, 1]}, headers=headers).status_code == 422


def test_quiz_submit_rejects_out_of_range_answer(quiz_user, stub_llm):
    headers = quiz_user["headers"]
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)
    _start_and_pick(headers)

    response = client.post("/quiz/submit", json={"answers": [0, 1, 9]}, headers=headers)
    assert response.status_code == 400


def test_quiz_today_reflects_a_submitted_session(quiz_user, stub_llm):
    headers = quiz_user["headers"]
    client.put("/me/interests", json={"tag_ids": [1]}, headers=headers)
    _start_and_pick(headers)
    client.post("/quiz/submit", json={"answers": [0, 1, 2]}, headers=headers)

    data = client.get("/quiz/today", headers=headers).json()
    assert data["state"] == "submitted"
    assert data["passed"] is True
    assert data["streak"]["current_streak"] == 1
    assert data["streak"]["longest_streak"] == 1
