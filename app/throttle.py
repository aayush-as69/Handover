"""The one place that throttles: request rate per address, and login lockout.

* `RateLimiter` - sliding window per key, in memory (per server process). A cheap first line
  of defence; a proxy or CDN limiter in front is still advised.
* `login_allowed` / `record_login_failure` / `clear_login_failures` - lockout kept in the
  database so it survives restarts and is shared by every process.
"""

from __future__ import annotations

import hashlib
import time
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .models import LoginAttempt, utcnow

MAX_FAILURES = 5
WINDOW = timedelta(minutes=5)


# Limits within the 5-minute window. Designed so one office behind one address is not locked
# out by a few typos, while guessing is still capped from every angle:
MAX_FAILURES_PER_USER_AND_IP = MAX_FAILURES   # one address guessing one account
MAX_FAILURES_PER_USER = 20                    # many addresses guessing one account
MAX_USERNAMES_PER_IP = 15                     # one address trying many accounts (spraying)
MAX_FAILURES_PER_IP = 100                     # raw volume from one address


def _pair_key(username: str, ip: str) -> str:
    return f"ipu:{ip}|{hashlib.sha256(username.encode()).hexdigest()[:16]}"


def _blocked(session: Session, key: str, limit: int | None = None) -> bool:
    since = utcnow() - WINDOW
    n = session.scalar(select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.key == key, LoginAttempt.at >= since))
    return (n or 0) >= (MAX_FAILURES if limit is None else limit)


def login_allowed(session: Session, username: str, ip: str) -> bool:
    """False if any of the four limits has been reached."""
    since = utcnow() - WINDOW
    pair = _pair_key(username, ip)
    if _blocked(session, pair, MAX_FAILURES_PER_USER_AND_IP):
        return False
    if _blocked(session, f"u:{username}", MAX_FAILURES_PER_USER):
        return False
    if _blocked(session, f"ip:{ip}", MAX_FAILURES_PER_IP):
        return False
    distinct = session.scalar(select(func.count(func.distinct(LoginAttempt.key))).where(
        LoginAttempt.key.like(f"ipu:{ip}|%"), LoginAttempt.at >= since))
    return (distinct or 0) < MAX_USERNAMES_PER_IP


def record_login_failure(session: Session, username: str, ip: str) -> None:
    session.execute(delete(LoginAttempt).where(LoginAttempt.at < utcnow() - WINDOW))
    session.add_all([LoginAttempt(key=_pair_key(username, ip)), LoginAttempt(key=f"u:{username}"),
                     LoginAttempt(key=f"ip:{ip}")])
    session.commit()


def clear_login_failures(session: Session, username: str, ip: str) -> None:
    """A correct password clears that person's own counters, not the address's volume count."""
    session.execute(delete(LoginAttempt).where(
        LoginAttempt.key.in_([_pair_key(username, ip), f"u:{username}"])))
    session.commit()


class RateLimiter:
    """Sliding-window request limiter per key, kept in memory (per server process).
    A cheap first line of defence; a proxy or CDN limiter in front is still advised."""

    def __init__(self, limit: int, seconds: int = 60, clock=time.monotonic):
        self.limit, self.seconds, self.clock = limit, seconds, clock
        self.hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        if self.limit <= 0:
            return True
        now = self.clock()
        recent = [t for t in self.hits.get(key, ()) if now - t < self.seconds]
        if len(recent) >= self.limit:
            self.hits[key] = recent
            return False
        recent.append(now)
        self.hits[key] = recent
        if len(self.hits) > 10_000:                       # bound memory under address churn
            self.hits = {k: v for k, v in self.hits.items() if v and now - v[-1] < self.seconds}
        return True
