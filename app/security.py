"""Passwords, login throttling and CSRF tokens. Standard library only."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

_ITER = 200_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITER)
    return f"pbkdf2${_ITER}${salt.hex()}${dk.hex()}"


# Checked when the username does not exist, at the real cost, so response time does not reveal
# which names are registered.
DUMMY_HASH = "pbkdf2$%d$%s$%s" % (_ITER, "00" * 16, "00" * 32)


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        _, iters, salt, dk = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(calc.hex(), dk)
    except (ValueError, TypeError):
        return False


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def csrf_ok(expected: str | None, given: str | None) -> bool:
    return bool(expected) and bool(given) and hmac.compare_digest(expected, given)


class LoginThrottle:
    """Blocks a username after too many recent failures."""

    def __init__(self, max_failures: int = 5, window: float = 300.0, clock=time.monotonic):
        self.max, self.window, self.clock = max_failures, window, clock
        self._fails: dict[str, list[float]] = {}

    def _recent(self, key: str) -> list[float]:
        now = self.clock()
        recent = [t for t in self._fails.get(key, []) if now - t < self.window]
        self._fails[key] = recent
        return recent

    def blocked(self, key: str) -> bool:
        return len(self._recent(key)) >= self.max

    def fail(self, key: str) -> None:
        self._recent(key).append(self.clock())

    def reset(self, key: str) -> None:
        self._fails.pop(key, None)


# ---------------------------------------------------------------- lockout kept in the database

from datetime import timedelta  # noqa: E402

from sqlalchemy import delete, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from .models import LoginAttempt, User, utcnow  # noqa: E402

MAX_FAILURES = 5
WINDOW = timedelta(minutes=5)


# Limits within the 5-minute window. Designed so one office behind one address is not locked
# out by a few typos, while guessing is still capped from every angle:
MAX_FAILURES_PER_USER_AND_IP = MAX_FAILURES   # one address guessing one account
MAX_FAILURES_PER_USER = 20                    # many addresses guessing one account
MAX_USERNAMES_PER_IP = 15                     # one address trying many accounts (spraying)
MAX_FAILURES_PER_IP = 100                     # raw volume from one address


def client_ip(request, trust_proxy: bool) -> str:
    """The caller's address. Behind a proxy (Render) the proxy appends the real address as the
    LAST X-Forwarded-For entry; earlier entries are client-supplied and can be forged."""
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        last = forwarded.split(",")[-1].strip()
        if last:
            return last[:45]
    return (request.client.host if request.client else "unknown")[:45]


def _pair_key(username: str, ip: str) -> str:
    return f"ipu:{ip}|{hashlib.sha256(username.encode()).hexdigest()[:16]}"


def login_blocked(session: Session, key: str, limit: int | None = None) -> bool:
    since = utcnow() - WINDOW
    n = session.scalar(select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.key == key, LoginAttempt.at >= since))
    return (n or 0) >= (MAX_FAILURES if limit is None else limit)


def login_allowed(session: Session, username: str, ip: str) -> bool:
    """False if any of the four limits has been reached."""
    since = utcnow() - WINDOW
    pair = _pair_key(username, ip)
    if login_blocked(session, pair, MAX_FAILURES_PER_USER_AND_IP):
        return False
    if login_blocked(session, f"u:{username}", MAX_FAILURES_PER_USER):
        return False
    if login_blocked(session, f"ip:{ip}", MAX_FAILURES_PER_IP):
        return False
    distinct = session.scalar(select(func.count(func.distinct(LoginAttempt.key))).where(
        LoginAttempt.key.like(f"ipu:{ip}|%"), LoginAttempt.at >= since))
    return (distinct or 0) < MAX_USERNAMES_PER_IP


def record_login_failure_for(session: Session, username: str, ip: str) -> None:
    session.execute(delete(LoginAttempt).where(LoginAttempt.at < utcnow() - WINDOW))
    session.add_all([LoginAttempt(key=_pair_key(username, ip)), LoginAttempt(key=f"u:{username}"),
                     LoginAttempt(key=f"ip:{ip}")])
    session.commit()


def clear_login_failures_for(session: Session, username: str, ip: str) -> None:
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


def record_login_failure(session: Session, key: str) -> None:
    session.execute(delete(LoginAttempt).where(LoginAttempt.at < utcnow() - WINDOW))
    session.add(LoginAttempt(key=key))
    session.commit()


def clear_login_failures(session: Session, key: str) -> None:
    session.execute(delete(LoginAttempt).where(LoginAttempt.key == key))
    session.commit()


def set_user_password(user: User, password: str) -> bool:
    """Set a password and revoke all previously issued sessions for the user.

    Return False when the supplied password already matches, avoiding needless hash
    churn and session invalidation on each demo boot.
    """
    if not isinstance(password, str) or not password:
        raise ValueError("password cannot be empty")
    if verify_password(password, user.password_hash):
        return False
    user.password_hash = hash_password(password)
    user.session_version = (user.session_version or 0) + 1
    return True
