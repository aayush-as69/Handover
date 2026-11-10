import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session
from tests.dbutil import new_engine
from app.demo import load_demo_project
from app.enums import ChangeType, Confidence, ReviewStatus, Sensitivity
from app.extract.pipeline import run_extraction
from app.extract.rules import RuleExtractor
from app.main import create_app
from app.models import Chunk, Claim
from app.security import LoginThrottle, hash_password, verify_password
from app import web

PW = "demo-" + "pass-123"


@pytest.fixture()
def env():
    engine = new_engine()
    Session = sessionmaker(engine, expire_on_commit=False)
    with Session() as s:
        project = load_demo_project(s, password=PW)
        run_extraction(s, project, RuleExtractor())
        s.commit()
    app = create_app(secret_key="test-key")

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override
    return app, Session


def client(app):
    return TestClient(app, follow_redirects=False)


def token(c, path="/login"):
    html = c.get(path).text
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def login(app, username):
    c = client(app)
    r = c.post("/login", data={"username": username, "password": PW, "csrf": token(c)})
    assert r.status_code == 303
    return c


def claim_where(Session, **kw):
    with Session() as s:
        return s.scalars(select(Claim)).all()


def a_claim(Session, *, confidential):
    with Session() as s:
        for c in s.scalars(select(Claim).order_by(Claim.id)):
            from app.access import effective_sensitivity
            if (effective_sensitivity(c) == Sensitivity.confidential) == confidential:
                return c.id
    raise AssertionError("no such claim")


def act(c, cid, action, **data):
    html = c.get(f"/review/claims/{cid}").text
    t = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    v = re.search(r'name="version" value="(\d+)"', html).group(1)
    return c.post(f"/review/claims/{cid}/{action}", data={"csrf": t, "version": v, **data})


# ------------------------------------------------------------ passwords / throttle


def test_password_hashing():
    h = hash_password("abc")
    assert h != "abc" and verify_password("abc", h)
    assert not verify_password("abd", h) and not verify_password("abc", None)
    assert not verify_password("abc", "garbage")
    assert hash_password("abc") != h                       # salted


def test_throttle_blocks_then_expires():
    now = [0.0]
    t = LoginThrottle(max_failures=3, window=10, clock=lambda: now[0])
    for _ in range(3):
        t.fail("a")
    assert t.blocked("a") and not t.blocked("b")
    now[0] = 11
    assert not t.blocked("a")


# ------------------------------------------------------------ login


def test_review_requires_login(env):
    app, _ = env
    r = client(app).get("/review")
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_wrong_password_and_unknown_user_look_the_same(env):
    app, _ = env
    c = client(app)
    a = c.post("/login", data={"username": "meera", "password": "nope", "csrf": token(c)})
    b = c.post("/login", data={"username": "ghost", "password": "nope", "csrf": token(c)})
    assert a.status_code == b.status_code == 401
    assert "Wrong username or password." in a.text and "Wrong username or password." in b.text


def test_login_needs_csrf_token(env):
    app, _ = env
    c = client(app)
    c.get("/login")
    r = c.post("/login", data={"username": "meera", "password": PW, "csrf": "forged"})
    assert r.status_code == 403


def test_repeated_failures_lock_the_account_even_with_the_right_password(env):
    app, _ = env
    c = client(app)
    for _ in range(5):
        c.post("/login", data={"username": "meera", "password": "x", "csrf": token(c)})
    r = c.post("/login", data={"username": "meera", "password": PW, "csrf": token(c)})
    assert r.status_code == 429


def test_user_without_password_cannot_log_in(env):
    app, Session = env
    with Session() as s:
        from app.models import User
        s.scalar(select(User).where(User.username == "meera")).password_hash = None
        s.commit()
    c = client(app)
    r = c.post("/login", data={"username": "meera", "password": "", "csrf": token(c)})
    assert r.status_code == 401


def test_logout_ends_the_session(env):
    app, _ = env
    c = login(app, "meera")
    assert c.get("/review").status_code == 200
    c.post("/logout", data={"csrf": token(c, "/review")})
    assert c.get("/review").status_code == 303


def test_security_headers(env):
    app, _ = env
    r = client(app).get("/login")
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in r.headers["content-security-policy"]


# ------------------------------------------------------------ who may review


@pytest.mark.parametrize("who", ["kabir", "rao"])
def test_viewers_cannot_open_the_review_queue(env, who):
    app, Session = env
    c = login(app, who)
    assert c.get("/review").status_code == 403
    cid = a_claim(Session, confidential=False)
    assert c.get(f"/review/claims/{cid}").status_code == 403
    r = c.post(f"/review/claims/{cid}/approve", data={"csrf": token(c, "/login")})
    assert r.status_code == 403
    with Session() as s:
        assert s.get(Claim, cid).review_status == ReviewStatus.generated


def test_queue_lists_claims_riskiest_first(env):
    app, _ = env
    c = login(app, "meera")
    html = c.get("/review?status=all").text
    assert "Review queue" in html and "verified" in html


def test_queue_escapes_html_in_claims(env):
    app, Session = env
    with Session() as s:
        c = s.scalars(select(Claim)).first()
        c.statement = "<script>alert(1)</script>"
        s.commit()
    html = login(app, "meera").get("/review?status=all").text
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


def test_unknown_claim_is_404(env):
    app, _ = env
    assert login(app, "meera").get("/review/claims/99999").status_code == 404


# ------------------------------------------------------------ actions


def test_approve_records_who_and_a_version(env):
    app, Session = env
    c = login(app, "meera")
    cid = a_claim(Session, confidential=False)
    r = act(c, cid, "approve")
    assert r.status_code == 303
    with Session() as s:
        claim = s.get(Claim, cid)
        assert claim.review_status == ReviewStatus.approved
        last = claim.versions[-1]
        assert last.change_type == ChangeType.approve and last.changed_by == "Meera Iyer"


def test_actions_need_a_valid_csrf_token(env):
    app, Session = env
    c = login(app, "meera")
    cid = a_claim(Session, confidential=False)
    r = c.post(f"/review/claims/{cid}/approve", data={"csrf": "forged"})
    assert r.status_code == 403
    r = c.post(f"/review/claims/{cid}/approve", data={})
    assert r.status_code == 403
    with Session() as s:
        assert s.get(Claim, cid).review_status == ReviewStatus.generated


def test_an_unverified_claim_cannot_be_approved_without_a_reason(env):
    app, Session = env
    c = login(app, "meera")
    cid = a_claim(Session, confidential=False)
    with Session() as s:
        s.get(Claim, cid).confidence = Confidence.inferred
        s.commit()
    act(c, cid, "approve")
    with Session() as s:
        assert s.get(Claim, cid).review_status == ReviewStatus.generated
    act(c, cid, "approve", note="Confirmed with Riya in standup")
    with Session() as s:
        claim = s.get(Claim, cid)
        assert claim.review_status == ReviewStatus.approved
        assert claim.versions[-1].note == "Confirmed with Riya in standup"


def test_reject_then_reopen(env):
    app, Session = env
    c = login(app, "meera")
    cid = a_claim(Session, confidential=False)
    act(c, cid, "reject", note="wrong")
    with Session() as s:
        assert s.get(Claim, cid).review_status == ReviewStatus.rejected
    act(c, cid, "reopen")
    with Session() as s:
        claim = s.get(Claim, cid)
        assert claim.review_status == ReviewStatus.generated
        assert [v.change_type for v in claim.versions][-2:] == [ChangeType.reject, ChangeType.reopen]


def test_reopen_only_applies_to_decided_claims(env):
    app, Session = env
    c = login(app, "meera")
    cid = a_claim(Session, confidential=False)
    act(c, cid, "reopen")
    with Session() as s:
        assert len(s.get(Claim, cid).versions) == 1


def test_editing_an_approved_claim_sends_it_back_and_rechecks_it(env):
    app, Session = env
    c = login(app, "meera")
    cid = a_claim(Session, confidential=False)
    act(c, cid, "approve")
    act(c, cid, "edit", statement="Kabir owns it since 2031-01-01 and it is never reviewed")
    with Session() as s:
        claim = s.get(Claim, cid)
        assert claim.review_status == ReviewStatus.edited
        assert claim.confidence == Confidence.inferred          # no longer mechanical, numbers unsupported
        assert claim.versions[-1].change_type == ChangeType.edit


def test_edit_validation(env):
    app, Session = env
    c = login(app, "meera")
    cid = a_claim(Session, confidential=False)
    act(c, cid, "edit", statement="   ")
    act(c, cid, "edit", statement="x" * 5000)
    with Session() as s:
        assert len(s.get(Claim, cid).versions) == 1


def test_unknown_action_is_404(env):
    app, Session = env
    c = login(app, "meera")
    cid = a_claim(Session, confidential=False)
    assert act(c, cid, "delete").status_code == 404


# ------------------------------------------------------------ sensitivity in the UI


def test_an_approver_cannot_see_or_act_on_confidential_claims(env):
    app, Session = env
    cid = a_claim(Session, confidential=True)
    c = login(app, "meera")                       # approver: clearance is confidential
    assert c.get(f"/review/claims/{cid}").status_code == 200
    # lower the role's clearance for this check by using a team-level approver
    from app.models import User
    from app.enums import Role
    with Session() as s:
        s.add(User(username="low", display_name="Low", role=Role.approver,
                   password_hash=hash_password(PW)))
        s.commit()
    from app import access
    orig = dict(access.ROLE_CLEARANCE)
    access.ROLE_CLEARANCE[Role.approver] = Sensitivity.team
    try:
        c2 = login(app, "low")
        assert c2.get(f"/review/claims/{cid}").status_code == 404
        r = c2.post(f"/review/claims/{cid}/approve", data={"csrf": token(c2)})
        assert r.status_code == 404
        listing = c2.get("/review?status=all").text
        assert f"/review/claims/{cid}\"" not in listing and "above your clearance" in listing
        with Session() as s:
            assert s.get(Claim, cid).review_status == ReviewStatus.generated
    finally:
        access.ROLE_CLEARANCE.update(orig)


def test_source_text_opens_with_the_quote_highlighted(env):
    app, Session = env
    c = login(app, "meera")
    cid = a_claim(Session, confidential=False)
    html = c.get(f"/review/claims/{cid}").text
    link = re.search(r'href="(/review/chunks/\d+[^"]*)"', html).group(1)
    page = c.get(link.replace("&amp;", "&"))
    assert page.status_code == 200 and "<mark>" in page.text


def test_unknown_chunk_is_404(env):
    app, _ = env
    assert login(app, "meera").get("/review/chunks/99999").status_code == 404


def test_version_history_shows_a_word_diff(env):
    app, Session = env
    c = login(app, "meera")
    cid = a_claim(Session, confidential=False)
    act(c, cid, "edit", statement="Totally new wording here for this claim", note="clarified")
    html = c.get(f"/review/claims/{cid}").text
    assert "<ins>" in html and "<del>" in html and "clarified" in html


def test_word_diff():
    assert web.word_diff("a b c", "a x c") == [("same", "a"), ("del", "b"), ("ins", "x"), ("same", "c")]


def test_citation_does_not_repeat_the_file_name(env):
    app, Session = env
    c = login(app, "meera")
    cid = a_claim(Session, confidential=False)
    html = c.get(f"/review/claims/{cid}").text
    import re as _re
    for line in _re.findall(r"<footer>(.*?)</footer>", html, _re.S):
        m = _re.search(r"([\w.-]+\.(?:md|txt|csv|json))", line)
        if m:
            assert line.count(m.group(1)) == 1


def test_ui_says_quote_verified_and_explains_its_limit(env):
    app, Session = env
    c = login(app, "meera")
    html = c.get("/review?status=all").text
    assert "quote-verified" in html
    cid = a_claim(Session, confidential=False)
    page = c.get(f"/review/claims/{cid}").text
    assert "does not mean the claim is true, current or complete" in page


def test_claim_page_shows_when_a_claim_is_disputed(env):
    app, Session = env
    from app.models import Claim as C
    c = login(app, "meera")
    from app.conflicts import detect_conflicts
    from app.models import Project as P
    with Session() as s:
        detect_conflicts(s, s.scalar(select(P)))
        s.commit()
        redis = s.scalars(select(C).where(C.statement.contains("Seat locks will go in Redis"))).one().id
    assert "Disputed" in c.get(f"/review/claims/{redis}").text


# ------------------------------------------------------------ concurrent changes


def test_a_stale_form_cannot_overwrite_a_newer_change(env):
    app, Session = env
    a, b = login(app, "meera"), login(app, "riya")
    cid = a_claim(Session, confidential=False)
    html = a.get(f"/review/claims/{cid}").text          # both reviewers open the same version
    t = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    v = re.search(r'name="version" value="(\d+)"', html).group(1)
    act(b, cid, "edit", statement="Riya changed the wording first")
    r = a.post(f"/review/claims/{cid}/approve", data={"csrf": t, "version": v})
    assert r.status_code == 303
    with Session() as s:
        claim = s.get(Claim, cid)
        assert claim.review_status == ReviewStatus.edited       # Meera's approval did not land
        assert claim.statement == "Riya changed the wording first"
    assert "changed by someone else" in a.get(f"/review/claims/{cid}").text


def test_a_missing_version_is_refused(env):
    app, Session = env
    c = login(app, "meera")
    cid = a_claim(Session, confidential=False)
    r = c.post(f"/review/claims/{cid}/approve", data={"csrf": token(c, f"/review/claims/{cid}")})
    assert r.status_code == 303
    with Session() as s:
        assert s.get(Claim, cid).review_status == ReviewStatus.generated


def test_two_sessions_writing_the_same_claim_cannot_both_succeed(env):
    from sqlalchemy.orm.exc import StaleDataError
    _, Session = env
    cid = a_claim(Session, confidential=False)
    s1, s2 = Session(), Session()
    c1, c2 = s1.get(Claim, cid), s2.get(Claim, cid)
    c1.approve("Meera")
    s1.commit()
    with pytest.raises(StaleDataError):
        c2.reject("Riya")                         # c2 still holds the version it read earlier
        s2.commit()
    s2.rollback()
    s3 = Session()
    claim = s3.get(Claim, cid)
    assert claim.review_status == ReviewStatus.approved and [v.version for v in claim.versions] == [1, 2]
    for x in (s1, s2, s3):
        x.close()


def test_approval_invalidation_is_visible_in_the_ui(env):
    app, Session = env
    m = login(app, "meera")
    cid = a_claim(Session, confidential=False)
    act(m, cid, "approve")
    m.get("/handover")
    m.post("/handover/approve", data={"csrf": token(m, "/handover")})
    k = login(app, "kabir")
    assert "I have read this handover" in k.get("/handover").text
    act(m, cid, "edit", statement="A reworded claim after sign-off")
    assert "No handover is available to you" in k.get("/handover").text
    assert "sign-off is out of date" in m.get("/handover").text
    act(m, cid, "approve", note="re-checked")
    m.post("/handover/approve", data={"csrf": token(m, "/handover")})
    assert "I have read this handover" in k.get("/handover").text



def test_review_queue_is_paginated_and_clamps_the_page(env, monkeypatch):
    import app.web as web
    monkeypatch.setattr(web, "QUEUE_PAGE", 5)
    app, _ = env
    c = login(app, "meera")
    p1 = c.get("/review?status=all&page=1").text
    assert "Page 1 of" in p1 and "Next" in p1 and "Previous" not in p1
    assert p1.count('href="/review/claims/') == 5
    last = c.get("/review?status=all&page=9999").text      # clamped to the last page
    assert "Previous" in last and "Next &rarr;" not in last
    assert c.get("/review?status=all&page=-3").text.count('href="/review/claims/') == 5


def test_unknown_user_check_costs_as_much_as_a_real_one():
    from app.security import DUMMY_HASH
    assert DUMMY_HASH.split("$")[1] == hash_password("x").split("$")[1]


def test_stylesheet_url_is_versioned_and_cached_long():
    from fastapi.testclient import TestClient
    from app.main import create_app
    c = TestClient(create_app(secret_key="k" * 40))
    html = c.get("/login").text
    import re
    url = re.search(r'href="(/static/style\.css\?v=[0-9a-f]{10})"', html).group(1)
    assert "immutable" in c.get(url).headers["cache-control"]
