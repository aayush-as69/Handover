import re
import time

import pytest
from fastapi.testclient import TestClient

from app.config import ConfigError, Settings
from app.main import create_app

GOOD = {"APP_ENV": "production", "SECRET_KEY": "x" * 40,
        "DATABASE_URL": "postgresql://u:p@h/db"}


def test_production_accepts_good_settings():
    assert Settings(GOOD).validate() == []


@pytest.mark.parametrize("change", [
    {"SECRET_KEY": ""}, {"SECRET_KEY": "short"}, {"COOKIE_SECURE": "false"},
    {"DATABASE_URL": "sqlite:///x.db"},
    {"DEMO_MODE": "1", "DEMO_PASSWORD": "demo1234"}, {"DEMO_MODE": "1"},
    {"EDGE_SHARED_SECRET": "too-short"},
])
def test_production_refuses_unsafe_settings(change):
    with pytest.raises(ConfigError):
        Settings({**GOOD, **change}).validate()


def test_unknown_env_refused_and_dev_only_warns():
    with pytest.raises(ConfigError):
        Settings({"APP_ENV": "prod"}).validate()
    assert Settings({}).validate()          # warning about SECRET_KEY, no raise


def test_production_app_hides_docs_and_sets_hsts():
    app = create_app(config=Settings(GOOD))
    with TestClient(app) as c:
        assert c.get("/docs").status_code == 404
        assert c.get("/openapi.json").status_code == 404
        assert "max-age" in c.get("/health").headers["strict-transport-security"]


def test_session_cookie_flags_and_expiry(monkeypatch):
    app = create_app(config=Settings(GOOD))
    with TestClient(app, base_url="https://testserver") as c:
        r = c.get("/login")
        raw = r.headers.get("set-cookie", "")
        assert "handover_session" in raw
        assert "httponly" in raw.lower() and "samesite=lax" in raw.lower() and "secure" in raw.lower()
        assert "max-age=28800" in raw.lower()
        token = re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)
        # An expired cookie is ignored: the stored csrf token no longer matches.
        real = time.time
        monkeypatch.setattr(time, "time", lambda: real() + 9 * 3600)
        r2 = c.post("/login", data={"username": "a", "password": "b", "csrf": token})
        assert r2.status_code in (400, 403)


def test_edge_origin_secret_blocks_direct_render_origin():
    secret = "edge-origin-secret-" + "x" * 40
    app = create_app(config=Settings({
        **GOOD,
        "EDGE_SHARED_SECRET": secret,
    }))
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200
        assert c.get("/ready").status_code in (200, 503)
        assert c.get("/login").status_code == 403
        assert c.get("/static/theme.js").status_code == 403
        trusted = c.get("/login", headers={"X-Handover-Origin-Key": secret})
        assert trusted.status_code == 200


def test_cloudflare_client_ip_is_trusted_only_with_edge_secret():
    from starlette.requests import Request
    from app.security import client_ip

    secret = "edge-origin-secret-" + "x" * 40
    def request(headers):
        return Request({
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": ("10.0.0.2", 443),
            "server": ("10.0.0.3", 443),
            "scheme": "https",
        })

    trusted = request({
        "X-Handover-Origin-Key": secret,
        "CF-Connecting-IP": "203.0.113.25",
        "X-Forwarded-For": "198.51.100.10, 10.0.0.2",
    })
    assert client_ip(trusted, True, secret) == "203.0.113.25"

    untrusted = request({
        "CF-Connecting-IP": "203.0.113.25",
        "X-Forwarded-For": "198.51.100.10, 10.0.0.2",
    })
    assert client_ip(untrusted, True, secret) == "10.0.0.2"
