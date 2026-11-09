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
