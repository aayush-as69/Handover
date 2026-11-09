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

from .models import LoginAttempt, utcnow  # noqa: E402

MAX_FAILURES = 5
WINDOW = timedelta(minutes=5)


def login_blocked(session: Session, key: str) -> bool:
    since = utcnow() - WINDOW
    n = session.scalar(select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.key == key, LoginAttempt.at >= since))
    return (n or 0) >= MAX_FAILURES


def record_login_failure(session: Session, key: str) -> None:
    session.execute(delete(LoginAttempt).where(LoginAttempt.at < utcnow() - WINDOW))
    session.add(LoginAttempt(key=key))
    session.commit()


def clear_login_failures(session: Session, key: str) -> None:
    session.execute(delete(LoginAttempt).where(LoginAttempt.key == key))
    session.commit()
