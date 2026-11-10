"""Tests for TinyFish budget tracking."""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services.tinyfish_budget import TinyFishBudget


def test_try_spend_fetch_increments_counter():
    """Test that try_spend_fetch increments the daily counter."""
    budget = TinyFishBudget()
    assert budget.daily_fetch_count == 0
    assert budget.try_spend_fetch(5) is True
    assert budget.daily_fetch_count == 5


def test_try_spend_fetch_returns_false_when_exhausted():
    """Test that try_spend_fetch returns False when budget exhausted."""
    budget = TinyFishBudget()
    budget.daily_fetch_count = 999
    assert budget.try_spend_fetch(2) is False
    assert budget.daily_fetch_count == 999  # Not incremented


def test_try_spend_fetch_exact_limit():
    """Test spending exactly at the limit."""
    budget = TinyFishBudget()
    budget.daily_fetch_count = 990
    assert budget.try_spend_fetch(10) is True
    assert budget.daily_fetch_count == 1000


def test_try_spend_search_rate_limit():
    """Test search rate limiting (30 per minute)."""
    budget = TinyFishBudget()
    
    # Should succeed 30 times
    for i in range(30):
        assert budget.try_spend_search() is True
    
    # Should fail on 31st within same minute
    assert budget.try_spend_search() is False


def test_try_spend_search_resets_after_minute():
    """Test that search rate limit resets after a minute."""
    budget = TinyFishBudget()
    
    # Use up all 30
    for _ in range(30):
        budget.try_spend_search()
    
    # Should be exhausted
    assert budget.try_spend_search() is False
    
    # Simulate time passing (manually manipulate timestamps)
    old_timestamps = list(budget.search_timestamps)
    budget.search_timestamps.clear()
    
    # Should succeed now
    assert budget.try_spend_search() is True


def test_daily_reset_on_new_day():
    """Test that daily counter resets on new day."""
    budget = TinyFishBudget()
    budget.daily_fetch_count = 500
    budget.last_reset = datetime.now(timezone.utc).date() - timedelta(days=1)  # Yesterday
    
    assert budget.try_spend_fetch(600) is True
    assert budget.daily_fetch_count == 600


def test_get_fetch_stats():
    """Test get_fetch_stats returns correct info."""
    budget = TinyFishBudget()
    budget.daily_fetch_count = 100
    
    for _ in range(5):
        budget.try_spend_search()
    
    stats = budget.get_fetch_stats()
    assert stats["daily_fetch_count"] == 100
    assert stats["daily_fetch_limit"] == 1000
    assert stats["search_per_min_count"] == 5
    assert stats["search_per_min_limit"] == 30


def test_try_spend_fetch_single_default():
    """Test try_spend_fetch with default n=1."""
    budget = TinyFishBudget()
    assert budget.try_spend_fetch() is True
    assert budget.daily_fetch_count == 1