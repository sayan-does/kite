import time

import pytest
from fastapi import HTTPException

from app.services.rate_limit import check_rate_limit, _counts, _max_requests


def test_under_limit_passes():
    uid = "test-user-under"
    _counts.pop(uid, None)
    for _ in range(_max_requests - 1):
        check_rate_limit(uid)


def test_over_limit_raises_429():
    uid = "test-user-over"
    _counts.pop(uid, None)
    for _ in range(_max_requests):
        check_rate_limit(uid)
    with pytest.raises(HTTPException) as exc:
        check_rate_limit(uid)
    assert exc.value.status_code == 429


def test_window_expires():
    uid = "test-user-window"
    _counts.pop(uid, None)
    for _ in range(_max_requests):
        check_rate_limit(uid)
    with pytest.raises(HTTPException) as exc:
        check_rate_limit(uid)
    assert exc.value.status_code == 429

    old = time.time() - 120
    _counts[uid] = [old]
    check_rate_limit(uid)
