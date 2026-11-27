"""The request limits, with a fake clock."""

import datetime as dt

from app.ratelimit import PACIFIC, RateLimiter, client_address, seconds_until_pacific_midnight

NOON = dt.datetime(2026, 11, 27, 12, 0, tzinfo=PACIFIC).timestamp()


class Clock:
    def __init__(self, t=NOON):
        self.t = t

    def __call__(self):
        return self.t


def limits(**kw):
    return {"per_minute": 0, "per_day": 0, "total_per_day": 0, **kw}


def test_per_minute_limit_is_a_sliding_window():
    clock = Clock()
    rl = RateLimiter(clock)
    assert [rl.check("a", **limits(per_minute=2)) for _ in range(2)] == [None, None]
    clock.t += 20
    blocked = rl.check("a", **limits(per_minute=2))
    assert blocked and blocked.retry_after_s == 41  # the first request leaves the window in 40 s
    assert rl.check("b", **limits(per_minute=2)) is None  # other clients aren't affected
    clock.t += 41
    assert rl.check("a", **limits(per_minute=2)) is None


def test_refused_requests_are_not_counted():
    clock = Clock()
    rl = RateLimiter(clock)
    rl.check("a", **limits(per_minute=1))
    for _ in range(5):
        assert rl.check("a", **limits(per_minute=1))
    clock.t += 61
    assert rl.check("a", **limits(per_minute=1)) is None


def test_daily_limits_reset_at_midnight_pacific():
    clock = Clock()
    rl = RateLimiter(clock)
    assert rl.check("a", **limits(per_day=1)) is None
    blocked = rl.check("a", **limits(per_day=1))
    assert blocked and blocked.retry_after_s == 12 * 3600 + 1
    assert rl.check("b", **limits(per_day=1, total_per_day=2)) is None
    assert "service" in rl.check("c", **limits(total_per_day=2)).reason
    clock.t += 12 * 3600 + 1  # just past midnight
    assert rl.check("a", **limits(per_day=1, total_per_day=2)) is None


def test_seconds_until_midnight_handles_daylight_saving():
    # 2026-11-01: clocks go back at 2 a.m., so that day has 25 hours
    start = dt.datetime(2026, 11, 1, 0, 0, tzinfo=PACIFIC).timestamp()
    assert seconds_until_pacific_midnight(start) == 25 * 3600 + 1


def test_client_address():
    assert client_address("10.0.0.1", None, 0) == "10.0.0.1"
    assert client_address("10.0.0.1", "203.0.113.7", 0) == "10.0.0.1"  # no proxy: header ignored
    assert client_address("10.0.0.1", "203.0.113.7", 1) == "203.0.113.7"
    # A client that writes its own header can't pick its address: the proxy appended the real one
    assert client_address("10.0.0.1", "1.2.3.4, 203.0.113.7", 1) == "203.0.113.7"
    assert client_address("10.0.0.1", "203.0.113.7, 10.1.1.1", 2) == "203.0.113.7"
    assert client_address(None, None, 1) == "unknown"
