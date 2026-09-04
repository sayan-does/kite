import time
from collections import defaultdict

from fastapi import HTTPException

_window_sec = 60
_max_requests = 10

_counts: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(user_id: str):
    now = time.time()
    cutoff = now - _window_sec
    timestamps = _counts[user_id]
    timestamps[:] = [t for t in timestamps if t > cutoff]
    if len(timestamps) >= _max_requests:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")
    timestamps.append(now)
