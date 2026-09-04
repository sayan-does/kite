"""Streak arithmetic on UTC calendar days.

The pure helpers are tested directly; the persistence path is covered through
the quiz endpoints in test_quiz.py.
"""

from datetime import date

from app.services.streaks import advance, decayed

TODAY = date(2026, 3, 10)
YESTERDAY = date(2026, 3, 9)
TWO_DAYS_AGO = date(2026, 3, 8)


def test_first_pass_starts_streak_at_one():
    assert advance(0, None, TODAY, passed=True) == 1


def test_pass_on_consecutive_day_increments():
    assert advance(4, YESTERDAY, TODAY, passed=True) == 5


def test_pass_after_a_gap_restarts_at_one():
    assert advance(9, TWO_DAYS_AGO, TODAY, passed=True) == 1


def test_fail_resets_to_zero():
    # The daily attempt is spent, so there is no way to recover the run today.
    assert advance(7, YESTERDAY, TODAY, passed=False) == 0


def test_fail_on_a_dead_streak_stays_zero():
    assert advance(0, TWO_DAYS_AGO, TODAY, passed=False) == 0


def test_second_pass_same_day_does_not_double_count():
    assert advance(3, TODAY, TODAY, passed=True) == 3


def test_pass_same_day_from_zero_still_counts_one():
    assert advance(0, TODAY, TODAY, passed=True) == 1


def test_decay_keeps_streak_passed_yesterday():
    assert decayed(6, YESTERDAY, TODAY) == 6


def test_decay_keeps_streak_passed_today():
    assert decayed(6, TODAY, TODAY) == 6


def test_decay_clears_streak_after_a_missed_day():
    # Nothing runs overnight, so a skipped day is only noticed on the next read.
    assert decayed(6, TWO_DAYS_AGO, TODAY) == 0


def test_decay_clears_streak_with_no_recorded_success():
    assert decayed(3, None, TODAY) == 0


def test_decay_leaves_zero_alone():
    assert decayed(0, TWO_DAYS_AGO, TODAY) == 0
