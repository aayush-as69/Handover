"""Unexpected failures: nothing internal leaks, and the person gets a usable answer."""
import re

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.enums import ReviewStatus
from app.models import Claim
from tests.test_web import PW, env, login  # noqa: F401


def csrf(c, path="/admin/sources"):
    return re.search(r'name="csrf" value="([^"]+)"', c.get(path).text).group(1)


# ------------------------------------------------------------ database failure


def test_a_database_error_shows_a_plain_page_not_sql_or_a_stack_trace(env, monkeypatch):
    app, Session = env
    c = login(app, "meera")
    import app.web as web

    def boom(*a, **k):
        raise RuntimeError("could not connect to server: password authentication failed for user 'prod'")
    monkeypatch.setattr(web, "project_for", boom)
    safe = TestClient(app, raise_server_exceptions=False)
    safe.cookies.update(c.cookies)
    r = safe.get("/review")
    assert r.status_code == 500
    assert "Something went wrong" in r.text
    for leak in ("password authentication", "prod", "Traceback", "RuntimeError"):
        assert leak not in r.text
    assert safe.get("/health").status_code == 200            # the process itself keeps serving


# ------------------------------------------------------------ LLM provider failures


def _llm_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("handler,expected", [
    (lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused")), "could not reach"),
    (lambda r: httpx.Response(401, json={}), "rejected the API key"),
    (lambda r: httpx.Response(429, json={}), "rate limit"),
    (lambda r: httpx.Response(503, text="<html>down</html>"), "returned an error (503)"),
    (lambda r: httpx.Response(200, text="not json at all"), None),
    (lambda r: httpx.Response(200, json={"choices": []}), None),
    (lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "{broken"}}]}), None),
])
def test_provider_failures_become_a_message_and_change_nothing(env, monkeypatch, handler, expected):
    app, Session = env
    import app.handover_web as hw
    from app.extract.llm import OpenAICompatibleExtractor
    monkeypatch.setattr(hw, "llm_from_env", lambda: OpenAICompatibleExtractor(
        base_url="http://x", api_key="k", model="m", client=_llm_client(handler)))
    c = login(app, "riya")
    with Session() as s:
        before = len(s.scalars(select(Claim)).all())
    r = c.post("/admin/sources/extract", data={"engine": "llm", "csrf": csrf(c)}, follow_redirects=True)
    assert r.status_code == 200
    assert "Traceback" not in r.text and "http://x" not in r.text 
    if expected:
        assert expected in r.text
    with Session() as s:
        assert len(s.scalars(select(Claim)).all()) == before


def test_missing_llm_settings_are_explained(env, monkeypatch):
    app, _ = env
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    c = login(app, "riya")
    r = c.post("/admin/sources/extract", data={"engine": "llm", "csrf": csrf(c)}, follow_redirects=True)
    assert "set these environment variables first" in r.text


# ------------------------------------------------------------ human approval is mandatory


def test_nothing_is_ever_approved_by_extraction_or_verification(env):
    """A 'verified' label is a mechanical check. Only a reviewer's action makes a claim approved."""
    app, Session = env
    with Session() as s:
        claims = s.scalars(select(Claim)).all()
        assert claims
        assert all(c.review_status != ReviewStatus.approved for c in claims)


def test_verify_module_never_writes_review_status():
    import pathlib
    src = (pathlib.Path(__file__).parent.parent / "app" / "verify.py").read_text()
    assert not re.search(r"review_status\s*=", src), "verification must not decide approval"
    assert "ReviewStatus.approved" not in src


def test_a_non_reviewer_cannot_approve_a_verified_claim(env):
    app, Session = env
    c = login(app, "kabir")                                   # a viewer
    with Session() as s:
        claim = s.scalars(select(Claim)).first()
        cid, ver = claim.id, claim.version
    r = c.post(f"/review/claims/{cid}/approve", data={"csrf": "x", "version": ver})
    assert r.status_code in (303, 401, 403, 404)
    with Session() as s:
        assert s.get(Claim, cid).review_status != ReviewStatus.approved


def test_unapproved_verified_claims_do_not_reach_the_handover(env):
    from app.handover import build_sections
    from app.models import Project, User
    app, Session = env
    with Session() as s:
        project = s.scalar(select(Project))
        viewer = s.scalar(select(User).where(User.username == "kabir"))
        assert build_sections(s, project, viewer) == []
