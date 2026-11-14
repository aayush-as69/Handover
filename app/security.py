"""Passwords, CSRF tokens and client address. Throttling lives in throttle.py."""

from __future__ import annotations

import hashlib
import ipaddress
import hmac
import os
import secrets

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


def client_ip(request, trust_proxy: bool,
              edge_shared_secret: str | None = None) -> str:
    """Return the trusted client address behind Render or an authenticated Cloudflare edge.

    Cloudflare's CF-Connecting-IP is only trusted when the request also carries the private
    origin header. Without that edge configuration, Render's appended final X-Forwarded-For
    address remains the source of truth.
    """
    if trust_proxy and edge_shared_secret:
        supplied = request.headers.get("x-handover-origin-key", "")
        if hmac.compare_digest(supplied, edge_shared_secret):
            candidate = request.headers.get("cf-connecting-ip", "").strip()
            try:
                return str(ipaddress.ip_address(candidate))
            except ValueError:
                pass
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        last = forwarded.split(",")[-1].strip()
        if last:
            return last[:45]
    return (request.client.host if request.client else "unknown")[:45]


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
