"""Daily quiz streaks, on UTC calendar days.

A streak advances on the first day a user passes the quiz and resets to zero
the moment a day is missed or failed. Days are UTC to match the 06:00 UTC
collect cron, so a user's day boundary never depends on their device clock.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from app.db import supabase

logger = logging.getLogger(__name__)

_EMPTY = {"current_streak": 0, "longest_streak": 0, "last_success_date": None}


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _parse_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def advance(current: int, last_success: date | None, today: date, *, passed: bool) -> int:
    """The streak value after today's attempt.

    A pass on a consecutive day extends the run; a pass after a gap starts a
    new one. A failure spends the single daily attempt, so the run ends there.
    """
    if not passed:
        return 0
    if last_success == today:
        return max(current, 1)
    if last_success == today - timedelta(days=1):
        return current + 1
    return 1


def decayed(current: int, last_success: date | None, today: date) -> int:
    """Zero out a run whose last success is too old to still be alive.

    Nothing runs on the user's behalf overnight, so a streak only looks stale
    when it is next read.
    """
    if current <= 0:
        return 0
    if last_success is None:
        return 0
    if last_success < today - timedelta(days=1):
        return 0
    return current


def read(user_id: str) -> dict:
    """Current streak for a user, repaired if a day was missed since last write."""
    try:
        resp = (
            supabase.table("user_streaks")
            .select("current_streak, longest_streak, last_success_date")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
    except Exception:
        logger.warning("could not read streak for %s", user_id, exc_info=True)
        return dict(_EMPTY)

    if not resp.data:
        return dict(_EMPTY)

    row = resp.data[0]
    current = row.get("current_streak") or 0
    last_success = _parse_date(row.get("last_success_date"))
    repaired = decayed(current, last_success, today_utc())

    if repaired != current:
        try:
            supabase.table("user_streaks").update({
                "current_streak": repaired,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("user_id", user_id).execute()
        except Exception:
            logger.warning("could not repair streak for %s", user_id, exc_info=True)

    return {
        "current_streak": repaired,
        "longest_streak": row.get("longest_streak") or 0,
        "last_success_date": last_success.isoformat() if last_success else None,
    }


def apply_result(user_id: str, *, passed: bool, today: date | None = None) -> dict:
    """Record today's quiz outcome and return the resulting streak."""
    day = today or today_utc()
    existing = read(user_id)

    last_success = _parse_date(existing.get("last_success_date"))
    current = advance(existing["current_streak"], last_success, day, passed=passed)
    longest = max(existing["longest_streak"], current)
    new_last_success = day if passed else last_success

    row = {
        "user_id": user_id,
        "current_streak": current,
        "longest_streak": longest,
        "last_success_date": new_last_success.isoformat() if new_last_success else None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        supabase.table("user_streaks").upsert(row, on_conflict="user_id").execute()
    except Exception:
        logger.warning("could not persist streak for %s", user_id, exc_info=True)

    return {
        "current_streak": current,
        "longest_streak": longest,
        "last_success_date": row["last_success_date"],
    }
