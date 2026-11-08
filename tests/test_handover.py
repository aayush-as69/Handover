import html
import io

import pytest
from sqlalchemy import select

from app.enums import HandoverStatus, Role, Sensitivity
from app.handover import (HandoverError, acknowledge, approve_handover, build_sections,
                          can_view, get_or_create_handover, withdraw_handover)
from app.models import Acknowledgement, Claim, Project, Source, User
from app.security import hash_password
from tests.test_web import PW, a_claim, act, client, env, login, token  # noqa: F401


def user(Session, name):
    with Session() as s:
        return s.scalar(select(User).where(User.username == name))


def approve_claims(app, Session, ids, who="meera"):
    c = login(app, who)
    for i in ids:
        act(c, i, "approve")
    return c


def public_ids(Session):
    from app.access import effective_sensitivity
    with Session() as s:
        return [c.id for c in s.scalars(select(Claim).order_by(Claim.id))
                if effective_sensitivity(c) == Sensitivity.team]


def conf_id(Session):
    return a_claim(Session, confidential=True)


# ------------------------------------------------------------ core rules


def test_non_reviewers_see_nothing_until_signoff(env):
    app, Session = env
    ids = public_ids(Session)[:3]
    approve_claims(app, Session, ids)
    k = login(app, "kabir")
    page = k.get("/handover")
    assert "No handover has been shared" in page.text
    with Session() as s:
        assert not any(s.get(Claim, i).statement in page.text for i in ids)
    assert 'class="evidence' not in page.text
    m = login(app, "meera")
    m.post("/handover/approve", data={"csrf": token(m, "/handover")})
    assert "Your first week" in k.get("/handover").text or "Decisions" in k.get("/handover").text


def test_only_reviewers_can_sign_off(env):
    app, Session = env
    approve_claims(app, Session, public_ids(Session)[:2])
    login(app, "meera").get("/handover")            # creates the draft
    k = login(app, "kabir")
    r = k.post("/handover/approve", data={"csrf": token(k, "/handover")})
    assert r.status_code == 303
    with Session() as s:
        assert s.scalar(select(Project)).id and \
            get_or_create_handover(s, s.scalar(select(Project))).status == HandoverStatus.draft


def test_cannot_sign_off_an_empty_handover(env):
    app, Session = env
    m = login(app, "meera")
    m.post("/handover/approve", data={"csrf": token(m, "/handover")})
    with Session() as s:
        h = get_or_create_handover(s, s.scalar(select(Project)))
        assert h.status == HandoverStatus.draft
        with pytest.raises(HandoverError):
            approve_handover(s, h, s.scalar(select(User).where(User.username == "meera")))


def test_viewer_sees_only_approved_claims_within_clearance(env):
    app, Session = env
    team = public_ids(Session)[:2]
    secret = conf_id(Session)
    approve_claims(app, Session, team + [secret])
    m = login(app, "meera")
    m.post("/handover/approve", data={"csrf": token(m, "/handover")})
    with Session() as s:
        claims = {c.id: c.statement for c in s.scalars(select(Claim))}
        viewer = s.scalar(select(User).where(User.username == "kabir"))
        restricted = s.scalar(select(User).where(User.username == "rao"))
        proj = s.scalar(select(Project))
        shown = {c.id for sec in build_sections(s, proj, viewer) for c in sec.claims}
        assert shown == set(team)                 # confidential approved claim hidden from viewer
        shown_r = {c.id for sec in build_sections(s, proj, restricted) for c in sec.claims}
        assert shown_r <= set(team)
        reviewer = s.scalar(select(User).where(User.username == "meera"))
        assert secret in {c.id for sec in build_sections(s, proj, reviewer) for c in sec.claims}
    html = login(app, "kabir").get("/handover").text
    assert claims[secret] not in html


def test_unapproved_claims_never_appear(env):
    app, Session = env
    ids = public_ids(Session)
    approve_claims(app, Session, ids[:1])
    m = login(app, "meera")
    m.post("/handover/approve", data={"csrf": token(m, "/handover")})
    with Session() as s:
        others = [c.statement for c in s.scalars(select(Claim)) if c.id != ids[0]]
    html = login(app, "kabir").get("/handover").text
    assert not any(o in html for o in others)


def test_rejecting_or_editing_a_claim_removes_it_at_once(env):
    app, Session = env
    ids = public_ids(Session)[:2]
    m = approve_claims(app, Session, ids)
    m.post("/handover/approve", data={"csrf": token(m, "/handover")})
    with Session() as s:
        s1, s2 = (s.get(Claim, i).statement for i in ids)
    k = login(app, "kabir")
    page = k.get("/handover").text
    assert html.escape(s1) in page and html.escape(s2) in page
    act(m, ids[0], "reject")
    act(m, ids[1], "edit", statement="A completely different statement now")
    page = k.get("/handover").text
    assert html.escape(s1) not in page and html.escape(s2) not in page
    assert "A completely different statement now" not in page
    with Session() as s:
        proj = s.scalar(select(Project))
        viewer = s.scalar(select(User).where(User.username == "kabir"))
        assert build_sections(s, proj, viewer) == []


def test_withdraw_hides_it_again(env):
    app, Session = env
    m = approve_claims(app, Session, public_ids(Session)[:2])
    m.post("/handover/approve", data={"csrf": token(m, "/handover")})
    k = login(app, "kabir")
    assert "No handover has been shared" not in k.get("/handover").text
    m.post("/handover/withdraw", data={"csrf": token(m, "/handover")})
    assert "No handover has been shared" in k.get("/handover").text


def test_handover_actions_need_csrf(env):
    app, Session = env
    m = approve_claims(app, Session, public_ids(Session)[:2])
    assert m.post("/handover/approve", data={"csrf": "bad"}).status_code == 403
    assert m.post("/handover/approve", data={}).status_code == 403


def test_acknowledgement_is_recorded_once(env):
    app, Session = env
    m = approve_claims(app, Session, public_ids(Session)[:2])
    m.post("/handover/approve", data={"csrf": token(m, "/handover")})
    k = login(app, "kabir")
    k.post("/handover/acknowledge", data={"csrf": token(k, "/handover")})
    k.post("/handover/acknowledge", data={"csrf": token(k, "/handover")})
    with Session() as s:
        assert len(s.scalars(select(Acknowledgement)).all()) == 1
    assert "Kabir" in m.get("/handover").text           # visible to reviewers


def test_cannot_acknowledge_before_signoff(env):
    app, Session = env
    m = approve_claims(app, Session, public_ids(Session)[:2])
    k = login(app, "kabir")
    k.get("/handover")
    k.post("/handover/acknowledge", data={"csrf": token(k, "/handover")})
    with Session() as s:
        assert s.scalars(select(Acknowledgement)).all() == []


def test_reviewer_sees_draft_preview_and_pending_count(env):
    app, Session = env
    m = approve_claims(app, Session, public_ids(Session)[:2])
    html = m.get("/handover").text
    assert "Draft preview" in html and "waiting for review" in html


def test_login_lands_non_reviewers_on_the_handover(env):
    app, _ = env
    c = client(app)
    r = c.post("/login", data={"username": "kabir", "password": PW, "csrf": token(c)})
    assert r.headers["location"] == "/handover"


def test_handover_requires_login(env):
    app, _ = env
    assert client(app).get("/handover").status_code == 303


# ------------------------------------------------------------ sources (admin)


def upload(c, name, body, kind="notes", sens="team", csrf=None):
    return c.post("/admin/sources/upload",
                  data={"csrf": csrf or token(c, "/admin/sources"), "kind": kind, "sensitivity": sens},
                  files={"file": (name, io.BytesIO(body), "text/plain")})


def test_only_admins_can_manage_sources(env):
    app, _ = env
    for who in ("meera", "kabir", "rao"):
        c = login(app, who)
        assert c.get("/admin/sources").status_code == 403
        r = c.post("/admin/sources/upload", data={"csrf": token(c, "/login"), "kind": "notes"},
                   files={"file": ("a.md", b"## Decisions\n- x", "text/plain")})
        assert r.status_code == 403


def test_admin_uploads_a_source_and_secrets_are_masked(env):
    app, Session = env
    c = login(app, "riya")
    fake = "sk_live_" + "A1b2C3d4E5f6G7h8I9j0K1l2"
    body = f"## Decisions\n- We chose Stripe for payments.\n- Key for staging is {fake}\n".encode()
    r = upload(c, "extra.md", body)
    assert r.status_code == 303
    with Session() as s:
        src = s.scalar(select(Source).where(Source.name == "extra.md"))
        assert src is not None
        assert all(fake not in ch.text for ch in src.chunks)


def test_upload_rejects_bad_input_cleanly(env):
    app, Session = env
    c = login(app, "riya")
    with Session() as s:
        before = len(s.scalars(select(Source)).all())
    upload(c, "bin.md", b"\x00\x01\x02")
    upload(c, "empty.md", b"   ")
    upload(c, "x.md", b"hello", kind="nonsense")
    upload(c, "x.md", b"hello", sens="top-secret")
    upload(c, "x.md", b"hello", csrf="forged")
    with Session() as s:
        assert len(s.scalars(select(Source)).all()) == before


def test_upload_filename_cannot_traverse_paths(env):
    app, Session = env
    c = login(app, "riya")
    upload(c, "../../etc/evil.md", b"## Decisions\n- Use Redis for locks please.")
    with Session() as s:
        names = [x.name for x in s.scalars(select(Source))]
    assert "evil.md" in names and not any("/" in n or ".." in n for n in names)


def test_extraction_button_creates_draft_claims_only(env):
    app, Session = env
    c = login(app, "riya")
    upload(c, "more.md", b"## Decisions\n- We will use Stripe for card payments in launch.\n")
    with Session() as s:
        before = len(s.scalars(select(Claim)).all())
    r = c.post("/admin/sources/extract", data={"csrf": token(c, "/admin/sources"), "engine": "rules"})
    assert r.status_code == 303
    with Session() as s:
        new = s.scalars(select(Claim).order_by(Claim.id.desc())).first()
        assert len(s.scalars(select(Claim)).all()) > before
        assert new.review_status.value == "generated"


def test_llm_extraction_without_config_fails_politely(env, monkeypatch):
    app, _ = env
    for n in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(n, raising=False)
    c = login(app, "riya")
    r = c.post("/admin/sources/extract", data={"csrf": token(c, "/admin/sources"), "engine": "llm"})
    assert r.status_code == 303 and r.headers["location"] == "/admin/sources"
    assert "Extraction failed" in c.get("/admin/sources").text
    r = c.post("/admin/sources/extract", data={"csrf": token(c, "/admin/sources"), "engine": "evil"})
    assert r.status_code == 303


# ------------------------------------------------------------ demo bootstrap


def test_bootstrap_demo_is_repeatable_and_approves_nothing(session):
    from app.demo import bootstrap_demo
    bootstrap_demo(session, "pw-" + "1234")
    n = len(session.scalars(select(Claim)).all())
    bootstrap_demo(session, "pw-" + "1234")
    assert len(session.scalars(select(Claim)).all()) == n > 0
    assert {c.review_status.value for c in session.scalars(select(Claim))} == {"generated"}
    assert all(u.password_hash for u in session.scalars(select(User)))


def test_nobody_can_acknowledge_a_draft_not_even_a_reviewer(env):
    _, Session = env
    with Session() as s:
        h = get_or_create_handover(s, s.scalar(select(Project)))
        for name in ("meera", "kabir"):
            with pytest.raises(HandoverError):
                acknowledge(s, h, s.scalar(select(User).where(User.username == name)))
