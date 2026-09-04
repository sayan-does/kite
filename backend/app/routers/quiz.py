"""Daily AI quiz: one session per user per UTC day, graded server-side.

Correct answers are never sent to the client before submission, and the single
row per user per day is what makes the streak worth anything.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import get_current_user_id
from app.config import settings
from app.db import supabase
from app.services import streaks
from app.services.quiz import (
    PASS_THRESHOLD,
    QUESTIONS_PER_QUIZ,
    generate_niches,
    generate_questions,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/quiz", tags=["quiz"])


class NicheBody(BaseModel):
    niche: str = Field(min_length=1, max_length=120)


class SubmitBody(BaseModel):
    answers: list[int] = Field(min_length=QUESTIONS_PER_QUIZ, max_length=QUESTIONS_PER_QUIZ)


def _quiz_disabled_response() -> dict:
    return {"enabled": False}


def _require_quiz_enabled() -> None:
    if not settings.QUIZ_ENABLED:
        raise HTTPException(status_code=404, detail="Quiz is disabled")


def _user_categories(user_id: str) -> list[tuple[str, int]]:
    interests = (
        supabase.table("user_interests").select("tag_id").eq("user_id", user_id).execute().data or []
    )
    tag_ids = [row["tag_id"] for row in interests if row.get("tag_id")]
    if not tag_ids:
        return []
    tags = (
        supabase.table("interest_tags").select("id, name").in_("id", tag_ids).execute().data or []
    )
    return [(t["name"], t["id"]) for t in tags if t.get("name")]


def _today_session(user_id: str) -> dict | None:
    resp = (
        supabase.table("quiz_sessions")
        .select("*")
        .eq("user_id", user_id)
        .eq("quiz_date", streaks.today_utc().isoformat())
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def _questions_for(session_id: str) -> list[dict]:
    return (
        supabase.table("quiz_questions")
        .select("*")
        .eq("session_id", session_id)
        .order("position")
        .execute()
        .data
        or []
    )


def _public_question(row: dict, *, reveal: bool) -> dict:
    payload = {
        "position": row["position"],
        "question": row["question"],
        "options": row["options"],
        "chosen_index": row.get("chosen_index"),
    }
    if reveal:
        payload["correct_index"] = row["correct_index"]
        chosen = row.get("chosen_index")
        payload["is_correct"] = chosen is not None and chosen == row["correct_index"]
    return payload


def _session_payload(user_id: str, session: dict | None) -> dict:
    streak = streaks.read(user_id)
    if session is None:
        return {
            "enabled": True,
            "state": "not_started",
            "streak": streak,
            "pass_threshold": PASS_THRESHOLD,
            "questions_per_quiz": QUESTIONS_PER_QUIZ,
        }

    submitted = session["status"] == "submitted"
    questions = (
        _questions_for(session["id"]) if session["status"] in {"questions_ready", "submitted"} else []
    )

    return {
        "enabled": True,
        "state": session["status"],
        "session_id": session["id"],
        "topic": session.get("topic"),
        "niche": session.get("niche"),
        "niche_options": session.get("niche_options") or [],
        "questions": [_public_question(q, reveal=submitted) for q in questions],
        "correct_count": session.get("correct_count"),
        "passed": session.get("passed"),
        "streak": streak,
        "pass_threshold": PASS_THRESHOLD,
        "questions_per_quiz": QUESTIONS_PER_QUIZ,
    }


@router.get("/today")
async def get_today(user_id: str = Depends(get_current_user_id)):
    if not settings.QUIZ_ENABLED:
        return _quiz_disabled_response()
    return _session_payload(user_id, _today_session(user_id))


@router.post("/start")
async def start_quiz(user_id: str = Depends(get_current_user_id)):
    """Open today's session and offer three niches from the user's categories."""
    _require_quiz_enabled()
    existing = _today_session(user_id)
    if existing is not None:
        # Today is already in flight or spent; resuming is the only option.
        return _session_payload(user_id, existing)

    categories = _user_categories(user_id)
    if not categories:
        raise HTTPException(status_code=400, detail="Pick at least one category first")

    # One category per day, chosen at random, so the three niches are all drawn
    # from the same category rather than being a mix the user has to compare.
    topic, tag_id = random.choice(categories)
    niches = await generate_niches([topic])

    row = {
        "user_id": user_id,
        "tag_id": tag_id,
        "topic": topic,
        "niche_options": niches,
        "quiz_date": streaks.today_utc().isoformat(),
        "status": "niche_pending",
    }
    try:
        resp = supabase.table("quiz_sessions").insert(row).execute()
    except Exception:
        # A concurrent start lost the unique(user_id, quiz_date) race.
        logger.info("quiz session insert conflicted for %s", user_id, exc_info=True)
        conflicted = _today_session(user_id)
        if conflicted is None:
            raise HTTPException(status_code=500, detail="Could not start quiz")
        return _session_payload(user_id, conflicted)

    if not resp.data:
        raise HTTPException(status_code=500, detail="Could not start quiz")
    return _session_payload(user_id, resp.data[0])


@router.post("/niche")
async def choose_niche(body: NicheBody, user_id: str = Depends(get_current_user_id)):
    """Lock in a niche and generate the three questions for it."""
    _require_quiz_enabled()
    session = _today_session(user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="No quiz started today")
    if session["status"] == "submitted":
        raise HTTPException(status_code=409, detail="Today's quiz is already complete")
    if session["status"] == "questions_ready":
        # Questions already exist; re-picking would hand out a fresh attempt.
        return _session_payload(user_id, session)

    offered = session.get("niche_options") or []
    if body.niche not in offered:
        raise HTTPException(status_code=400, detail="Niche was not one of the offered options")

    questions = await generate_questions(body.niche)
    if len(questions) < QUESTIONS_PER_QUIZ:
        raise HTTPException(status_code=503, detail="Could not generate a quiz right now")

    supabase.table("quiz_questions").delete().eq("session_id", session["id"]).execute()
    supabase.table("quiz_questions").insert([
        {
            "session_id": session["id"],
            "position": i + 1,
            "question": q["question"],
            "options": q["options"],
            "correct_index": q["correct_index"],
        }
        for i, q in enumerate(questions[:QUESTIONS_PER_QUIZ])
    ]).execute()

    updated = (
        supabase.table("quiz_sessions")
        .update({"niche": body.niche, "status": "questions_ready"})
        .eq("id", session["id"])
        .execute()
    )
    return _session_payload(user_id, (updated.data or [{**session, "status": "questions_ready"}])[0])


@router.post("/submit")
async def submit_quiz(body: SubmitBody, user_id: str = Depends(get_current_user_id)):
    """Grade today's answers, update the streak, and reveal the correct options."""
    _require_quiz_enabled()
    session = _today_session(user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="No quiz started today")
    if session["status"] == "niche_pending":
        raise HTTPException(status_code=409, detail="Choose a niche first")
    if session["status"] == "submitted":
        # Idempotent: the stored result stands, and the streak is untouched.
        return _session_payload(user_id, session)

    questions = _questions_for(session["id"])
    if len(questions) < QUESTIONS_PER_QUIZ:
        raise HTTPException(status_code=409, detail="Today's quiz is incomplete")

    if any(not 0 <= answer < len(q["options"]) for answer, q in zip(body.answers, questions)):
        raise HTTPException(status_code=400, detail="Answer index out of range")

    correct_count = 0
    for answer, question in zip(body.answers, questions):
        if answer == question["correct_index"]:
            correct_count += 1
        supabase.table("quiz_questions").update({"chosen_index": answer}).eq(
            "id", question["id"]
        ).execute()

    passed = correct_count >= PASS_THRESHOLD
    supabase.table("quiz_sessions").update({
        "status": "submitted",
        "correct_count": correct_count,
        "passed": passed,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", session["id"]).execute()

    streak = streaks.apply_result(user_id, passed=passed)

    graded = _questions_for(session["id"])
    return {
        "enabled": True,
        "state": "submitted",
        "session_id": session["id"],
        "topic": session.get("topic"),
        "niche": session.get("niche"),
        "niche_options": session.get("niche_options") or [],
        "questions": [_public_question(q, reveal=True) for q in graded],
        "correct_count": correct_count,
        "passed": passed,
        "streak": streak,
        "pass_threshold": PASS_THRESHOLD,
        "questions_per_quiz": QUESTIONS_PER_QUIZ,
    }
