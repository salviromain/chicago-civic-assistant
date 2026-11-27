"""Request limits for /query (Day 12): per client a minute and a day, and for the whole service a day.

    limiter.check("203.0.113.7", per_minute=5, per_day=50, total_per_day=500)
    -> None (allowed, and counted) or Limited(retry_after_s=42, reason="...")

Why three limits:
- per minute: one client can't fire questions in a loop;
- per client per day: one client can't use up the day for everyone;
- per service per day: a cap on what a day can cost (on the paid tier, ~$0.003 a
  question) or how much of the free quota the demo uses.

Days end at midnight Pacific time, when Gemini's daily quota resets. Counts live in
memory: they reset on restart and aren't shared between server instances, so the
deployment runs one instance (Day 13). 0 turns a limit off.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from collections import deque
from dataclasses import dataclass
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


@dataclass
class Limited:
    retry_after_s: int
    reason: str


def seconds_until_pacific_midnight(now: float) -> int:
    t = dt.datetime.fromtimestamp(now, PACIFIC)
    midnight = dt.datetime.combine(t.date() + dt.timedelta(days=1), dt.time(), PACIFIC)
    # Compare timestamps: subtracting two datetimes in the same zone ignores a
    # daylight-saving change between them (the 25-hour day would count as 24)
    return max(int(midnight.timestamp() - now) + 1, 1)


class RateLimiter:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.recent: dict[str, deque[float]] = {}  # client -> request times in the last minute
        self.day = None
        self.daily: dict[str, int] = {}             # client -> requests today
        self.total = 0                              # all requests today

    def check(self, client: str, *, per_minute: int, per_day: int, total_per_day: int) -> Limited | None:
        """Count this request, or say why it's refused and when to retry (not counted)."""
        with self.lock:
            now = self.clock()
            today = dt.datetime.fromtimestamp(now, PACIFIC).date()
            if today != self.day:
                self.day, self.daily, self.total = today, {}, 0
            recent = self.recent.setdefault(client, deque())
            while recent and recent[0] <= now - 60:
                recent.popleft()

            if total_per_day and self.total >= total_per_day:
                return Limited(seconds_until_pacific_midnight(now),
                               f"The service's daily limit ({total_per_day} questions) is reached. "
                               "It resets at midnight Pacific time.")
            if per_day and self.daily.get(client, 0) >= per_day:
                return Limited(seconds_until_pacific_midnight(now),
                               f"Daily limit reached ({per_day} questions per client). "
                               "It resets at midnight Pacific time.")
            if per_minute and len(recent) >= per_minute:
                return Limited(max(int(recent[0] + 60 - now) + 1, 1),
                               f"Too many questions: up to {per_minute} a minute.")

            recent.append(now)
            self.daily[client] = self.daily.get(client, 0) + 1
            self.total += 1
            if len(self.recent) > 10_000:  # forget clients idle for a minute
                self.recent = {c: q for c, q in self.recent.items() if q and q[-1] > now - 60}
            return None


def client_address(peer: str | None, forwarded_for: str | None, trusted_proxies: int) -> str:
    """The client's IP address. Behind `trusted_proxies` proxies (Cloud Run: 1), it's the
    entry that many places from the right of X-Forwarded-For: each proxy appends the
    address it saw, and entries further left were written by the client and could be
    made up. With no trusted proxy, it's the address of the connection itself."""
    if trusted_proxies and forwarded_for:
        hops = [h.strip() for h in forwarded_for.split(",") if h.strip()]
        if len(hops) >= trusted_proxies:
            return hops[-trusted_proxies]
    return peer or "unknown"
