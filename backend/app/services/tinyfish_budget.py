"""TinyFish budget tracking for free-tier limits."""

from datetime import datetime, timezone
from collections import deque

from app.config import settings
import logging

logger = logging.getLogger(__name__)


class TinyFishBudget:
    def __init__(self):
        self.daily_fetch_count = 0
        self.daily_fetch_limit = 1000
        self.search_timestamps = deque(maxlen=30)  # Rolling 1-min window
        self.search_per_min_limit = 30
        self.last_reset = datetime.now(timezone.utc).date()

    def try_spend_fetch(self, n: int = 1) -> bool:
        """Try to spend n fetch credits. Returns True if within budget."""
        self._maybe_reset()
        if self.daily_fetch_count + n > self.daily_fetch_limit:
            logger.warning(f"TinyFish fetch budget exhausted: {self.daily_fetch_count}/{self.daily_fetch_limit}")
            return False
        self.daily_fetch_count += n
        logger.debug(f"TinyFish fetch budget: {self.daily_fetch_count}/{self.daily_fetch_limit}")
        return True

    def try_spend_search(self) -> bool:
        """Try to spend one search credit. Returns True if within budget."""
        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - 60
        self.search_timestamps = deque(
            [ts for ts in self.search_timestamps if ts > cutoff],
            maxlen=30
        )
        if len(self.search_timestamps) >= self.search_per_min_limit:
            logger.warning(f"TinyFish search rate limit: {len(self.search_timestamps)}/min")
            return False
        self.search_timestamps.append(now.timestamp())
        logger.debug(f"TinyFish search: {len(self.search_timestamps)}/min")
        return True

    def _maybe_reset(self):
        """Reset daily counter if new day."""
        today = datetime.now(timezone.utc).date()
        if today > self.last_reset:
            logger.info("TinyFish daily fetch budget reset")
            self.daily_fetch_count = 0
            self.last_reset = today

    def get_fetch_stats(self) -> dict:
        """Get current fetch budget stats."""
        return {
            "daily_fetch_count": self.daily_fetch_count,
            "daily_fetch_limit": self.daily_fetch_limit,
            "search_per_min_count": len(self.search_timestamps),
            "search_per_min_limit": self.search_per_min_limit,
        }


# Global budget tracker instance
tinyfish_budget = TinyFishBudget()