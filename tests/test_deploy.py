import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import _normalise_db_url
from tests.dbutil import new_engine


@pytest.mark.parametrize("given,expected", [
    ("postgres://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ("postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ("sqlite:///./x.db", "sqlite:///./x.db"),
])
def test_database_url_normalised(given, expected):
    assert _normalise_db_url(given) == expected


def test_demo_mode_boots_a_usable_site_and_a_full_walkthrough_works(monkeypatch):
    """Start the app as a host would, then do the whole job: review, sign off, read, acknowledge."""
    import app.db as db
    from app.main import create_app
    from app.models import Base, Claim

    engine = new_engine()
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(db, "engine", engine)
    pw = "walk-" + "through-1"
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_PASSWORD", pw)
    monkeypatch.setattr(db, "init_db", lambda: None)
    import app.main as main
    monkeypatch.setattr(main, "init_db", lambda: None)

    app = create_app(secret_key="k")
    from app.web import get_session  # noqa: F401
    from app.db import get_session as gs

    def override():
        s = db.SessionLocal()
        try:
            yield s
        finally:
            s.close()
    app.dependency_overrides[gs] = override

    def tok(c, path="/login"):
        return re.search(r'name="csrf" value="([^"]+)"', c.get(path).text).group(1)

    def sign_in(c, user):
        r = c.post("/login", data={"username": user, "password": pw, "csrf": tok(c)})
        assert r.status_code == 303

    with TestClient(app, follow_redirects=False) as boss, TestClient(app, follow_redirects=False) as kabir:
        with db.SessionLocal() as s:
            claims = s.scalars(select(Claim)).all()
            assert claims and {c.review_status.value for c in claims} == {"generated"}
            target = next(c.id for c in claims if c.sensitivity.value == "team"
                          and c.confidence.value == "verified")
        sign_in(boss, "meera")
        page = boss.get(f"/review/claims/{target}").text
        version = re.search(r'name="version" value="(\d+)"', page).group(1)
        assert boss.post(f"/review/claims/{target}/approve",
                         data={"csrf": tok(boss, f"/review/claims/{target}"),
                               "version": version}).status_code == 303
        assert boss.post("/handover/approve", data={"csrf": tok(boss, "/handover")}).status_code == 303
        sign_in(kabir, "kabir")
        page = kabir.get("/handover")
        assert page.status_code == 200 and "I have read this handover" in page.text
        kabir.post("/handover/acknowledge", data={"csrf": tok(kabir, "/handover")})
        assert "Kabir" in boss.get("/handover").text
        assert boss.get("/health").json()["status"] == "ok"
