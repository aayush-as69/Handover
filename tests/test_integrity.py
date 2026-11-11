"""Release snapshots, uniqueness under races, append-only history, persistent lockout."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.enums import ChangeType, ClaimType, HandoverStatus, ReviewStatus, Role, Sensitivity, SourceKind
from app.handover import (HandoverError, acknowledge, approve_handover, build_sections,
                          get_or_create_handover, latest_release, release_state)
from app.ingest.service import ingest_source
from app.models import (Acknowledgement, AuditEvent, Claim, ClaimVersion, Evidence, Handover,
                        HandoverRelease, ImmutableError, Project, Source, User)
from tests.test_conflicts_questions import add_claim
from tests.test_web import PW, a_claim, act, client, env, login, token  # noqa: F401


def staff(session, name="Meera", role=Role.approver):
    u = User(username=name.lower(), display_name=name, role=role)
    session.add(u)
    session.flush()
    return u


# ------------------------------------------------------------ 1/2 one handover per project


def test_only_one_handover_per_project(session, project):
    a = get_or_create_handover(session, project)
    b = get_or_create_handover(session, project)
    assert a.id == b.id
    session.add(Handover(project_id=project.id, title="dup", outgoing_name="x"))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_creation_survives_a_lost_race(session, project, monkeypatch):
    """Another request creates the row between our check and our insert."""
    import app.handover as hv
    real = hv.get_handover
    calls = {"n": 0}

    def racy(sess, proj):
        calls["n"] += 1
        if calls["n"] == 1:                       # our first look finds nothing...
            sess.add(Handover(project_id=proj.id, title="winner", outgoing_name="x"))
            sess.flush()                          # ...but a rival inserts right after
            return None
        return real(sess, proj)

    monkeypatch.setattr(hv, "get_handover", racy)
    h = hv.get_or_create_handover(session, project)
    assert h.title == "winner"
    assert len(session.scalars(select(Handover)).all()) == 1


# ------------------------------------------------------------ 3 source dedupe


def test_identical_source_content_is_unique_per_project(session, project):
    ingest_source(session, project, kind=SourceKind.notes, name="a.md",
                  content="## Decisions\n- Use Redis for locks please.")
    session.add(Source(project_id=project.id, kind=SourceKind.notes, name="b.md",
                       content_hash=session.scalar(select(Source.content_hash))))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_ingest_survives_a_lost_dedupe_race(session, project, monkeypatch):
    content = "## Decisions\n- We will keep one datastore for everything."
    first = ingest_source(session, project, kind=SourceKind.notes, name="a.md", content=content)
    import app.ingest.service as svc
    real = session.scalar
    state = {"hide": True}

    def blind(stmt, *a, **k):                     # the pre-check misses the rival's row
        if state["hide"] and "content_hash" in str(stmt):
            state["hide"] = False
            return None
        return real(stmt, *a, **k)

    monkeypatch.setattr(session, "scalar", blind)
    second = svc.ingest_source(session, project, kind=SourceKind.notes, name="b.md", content=content)
    assert second.duplicate is True
    assert len(session.scalars(select(Source)).all()) == 1


# ------------------------------------------------------------ 4 append-only history


def test_claim_versions_capture_full_state_and_cannot_change(session, project):
    c = add_claim(session, project, "Use Redis for locks.")
    c.approve("Meera")
    c.edit("Use Redis for seat locks.", "Meera")
    session.flush()
    v1, v2, v3 = c.versions
    assert (v2.review_status, v3.review_status) == ("approved", "edited")
    assert v1.statement == "Use Redis for locks." and v3.statement == "Use Redis for seat locks."
    assert v2.confidence == "unsupported" and v2.sensitivity == "team"
    assert json.loads(v2.evidence_json)[0]["snippet"] == "Use Redis for locks."
    v2.note = "rewritten"
    with pytest.raises(ImmutableError):
        session.flush()
    session.rollback()


def test_versions_and_audit_events_cannot_be_deleted(session, project):
    c = add_claim(session, project, "Use Redis for locks.")
    from app.verify import verify_claim
    verify_claim(c)
    session.commit()
    for row in (c.versions[0], session.scalar(select(AuditEvent))):
        session.delete(row)
        with pytest.raises(ImmutableError):
            session.flush()
        session.rollback()


def test_stored_evidence_cannot_be_rewritten_or_removed(session, project):
    c = add_claim(session, project, "Use Redis for locks.")
    session.commit()
    c.evidence[0].snippet = "something else"
    with pytest.raises(ImmutableError):
        session.flush()
    session.rollback()
    ev = session.scalar(select(Evidence))
    ev.snippet_verified = True                    # the verification result may be recorded
    session.flush()
    session.delete(ev)
    with pytest.raises(ImmutableError):
        session.flush()
    session.rollback()


def test_verification_is_audited_with_the_evidence_it_checked(session, project):
    from app.verify import verify_claim
    c = add_claim(session, project, "Use Redis for locks.")
    verify_claim(c)
    session.flush()
    ev = session.scalar(select(AuditEvent))
    d = json.loads(ev.detail)
    assert ev.action == "verify" and d["confidence"] == "verified"
    assert d["evidence"][0]["verified"] is True and "word for word" in d["note"]
    verify_claim(c)                                # unchanged result: no noise
    session.flush()
    assert len(session.scalars(select(AuditEvent)).all()) == 1
    c.evidence[0].chunk.text = "different now"
    verify_claim(c)
    session.flush()
    assert [json.loads(e.detail)["confidence"] for e in session.scalars(select(AuditEvent))] == [
        "verified", "unsupported"]


# ------------------------------------------------------------ 7 releases


def make_release(session, project, claim_ids=None):
    u = staff(session)
    h = get_or_create_handover(session, project)
    return u, h, approve_handover(session, h, u)


def test_a_release_freezes_claims_and_versions(session, project):
    a = add_claim(session, project, "Use Redis for locks.", status=ReviewStatus.approved)
    u, h, r1 = make_release(session, project)
    assert r1.number == 1 and r1.entries == [(a.id, a.version)]
    assert r1.approved_by_name == "Meera"
    r1.number = 99
    with pytest.raises(ImmutableError):
        session.flush()
    session.rollback()


def test_new_releases_are_numbered_and_history_is_kept(session, project):
    add_claim(session, project, "Use Redis for locks.", status=ReviewStatus.approved)
    u, h, r1 = make_release(session, project)
    b = add_claim(session, project, "Use MySQL for reports.", status=ReviewStatus.approved)
    r2 = approve_handover(session, h, u)
    assert (r1.number, r2.number) == (1, 2) and len(r2.entries) == 2
    assert latest_release(session, h).id == r2.id
    assert len(r1.entries) == 1                    # release 1 is unchanged


def test_a_change_after_sign_off_hides_the_handover_from_readers_until_signed_off_again(session, project):
    a = add_claim(session, project, "Use Redis for locks.", status=ReviewStatus.approved)
    b = add_claim(session, project, "Use MySQL for reports.", status=ReviewStatus.approved)
    u, h, r1 = make_release(session, project)
    viewer = staff(session, "Kabir", Role.viewer)
    ids = lambda who=viewer: {c.id for s in build_sections(session, project, who) for c in s.claims}
    assert ids() == {a.id, b.id}
    a.edit("Use Redis for seat locks.", "Meera")
    assert ids() == set()                         # stale sign-off: readers see nothing at all
    assert ids(u) == {b.id}                       # reviewers still see what is still valid
    a.approve("Meera")                            # approved again, at a new version
    assert ids() == set()
    st = release_state(session, project, h)
    assert st.withdrawn == 1 and st.still_valid == 1
    approve_handover(session, h, u)
    assert ids() == {a.id, b.id}


@pytest.mark.parametrize("change", ["edit", "reject", "reopen"])
def test_every_kind_of_change_invalidates_the_sign_off(session, project, change):
    a = add_claim(session, project, "Use Redis for locks.", status=ReviewStatus.approved)
    u, h, _ = make_release(session, project)
    viewer = staff(session, "Kabir", Role.viewer)
    from app.handover import is_stale
    assert not is_stale(session, project, h)
    {"edit": lambda: a.edit("Something new here", "M"), "reject": lambda: a.reject("M"),
     "reopen": lambda: a.reopen("M")}[change]()
    assert is_stale(session, project, h)
    assert build_sections(session, project, viewer) == []
    with pytest.raises(HandoverError, match="changed after it was signed off"):
        acknowledge(session, h, viewer)


def test_approving_more_claims_does_not_invalidate_the_sign_off(session, project):
    add_claim(session, project, "Use Redis for locks.", status=ReviewStatus.approved)
    u, h, _ = make_release(session, project)
    add_claim(session, project, "Use MySQL for reports.", status=ReviewStatus.approved)
    from app.handover import is_stale
    assert not is_stale(session, project, h)


def test_claims_approved_after_release_are_not_shown_yet(session, project):
    add_claim(session, project, "Use Redis for locks.", status=ReviewStatus.approved)
    u, h, _ = make_release(session, project)
    late = add_claim(session, project, "Use MySQL for reports.", status=ReviewStatus.approved)
    viewer = staff(session, "Kabir", Role.viewer)
    assert late.id not in {c.id for s in build_sections(session, project, viewer) for c in s.claims}
    assert release_state(session, project, h).not_yet_released == 1


def test_acknowledgement_belongs_to_a_release(session, project):
    add_claim(session, project, "Use Redis for locks.", status=ReviewStatus.approved)
    u, h, r1 = make_release(session, project)
    viewer = staff(session, "Kabir", Role.viewer)
    assert acknowledge(session, h, viewer) is True and acknowledge(session, h, viewer) is False
    r2 = approve_handover(session, h, u)
    assert acknowledge(session, h, viewer) is True            # new release, new acknowledgement
    assert {a.release_id for a in session.scalars(select(Acknowledgement))} == {r1.id, r2.id}


# ------------------------------------------------------------ 6 acknowledgement race


def test_acknowledgement_survives_a_lost_race(session, project, monkeypatch):
    add_claim(session, project, "Use Redis for locks.", status=ReviewStatus.approved)
    u, h, r1 = make_release(session, project)
    viewer = staff(session, "Kabir", Role.viewer)
    real = session.scalar
    state = {"first": True}

    def blind(stmt, *a, **k):
        if "acknowledgements" in str(stmt) and state["first"]:
            state["first"] = False
            session.add(Acknowledgement(release_id=r1.id, user_id=viewer.id))   # rival wins
            session.flush()
            return None
        return real(stmt, *a, **k)

    monkeypatch.setattr(session, "scalar", blind)
    assert acknowledge(session, h, viewer) is False
    assert len(session.scalars(select(Acknowledgement)).all()) == 1


# ------------------------------------------------------------ 5 persistent lockout


def test_lockout_survives_a_restart(env):
    app, Session = env
    from app import web
    c = client(app)
    for _ in range(5):
        c.post("/login", data={"username": "meera", "password": "x", "csrf": token(c)})
    app2_client = client(__import__("app.main", fromlist=["x"]).create_app(secret_key="other"))
    # a brand-new app instance (as after a restart) sees the same database
    from app.db import get_session
    app2 = app2_client.app
    app2.dependency_overrides[get_session] = app.dependency_overrides[get_session]
    t = token(app2_client)
    r = app2_client.post("/login", data={"username": "meera", "password": PW, "csrf": t})
    assert r.status_code == 429


def test_successful_login_clears_earlier_failures(env):
    app, _ = env
    c = client(app)
    for _ in range(4):
        c.post("/login", data={"username": "meera", "password": "x", "csrf": token(c)})
    assert c.post("/login", data={"username": "meera", "password": PW, "csrf": token(c)}).status_code == 303
    c2 = client(app)
    for _ in range(4):
        c2.post("/login", data={"username": "meera", "password": "x", "csrf": token(c2)})
    assert c2.post("/login", data={"username": "meera", "password": PW, "csrf": token(c2)}).status_code == 303


def test_old_failures_expire(env):
    app, Session = env
    from app.models import LoginAttempt
    from app.models import utcnow
    with Session() as s:
        for _ in range(9):
            s.add(LoginAttempt(key="meera", at=utcnow() - timedelta(hours=2)))
        s.commit()
    c = client(app)
    assert c.post("/login", data={"username": "meera", "password": PW, "csrf": token(c)}).status_code == 303


def test_release_history_page_is_reviewer_only(env):
    app, Session = env
    m = login(app, "meera")
    m.get("/handover")
    ids = [a_claim(Session, confidential=False)]
    act(m, ids[0], "approve")
    m.post("/handover/approve", data={"csrf": token(m, "/handover")})
    assert "Release history" in m.get("/handover/releases").text
    assert login(app, "kabir").get("/handover/releases").status_code == 403


# ------------------------------------------------------------ database-level immutability

def test_database_rejects_direct_mutation_of_audit_history(session, project):
    from app.models import Handover, HandoverRelease
    from app.verify import verify_claim

    claim = add_claim(session, project, "Use Redis for locks.")
    verify_claim(claim)
    reviewer = staff(session)
    handover = Handover(project_id=project.id, title="Handover",
                        outgoing_name="Riya", status=HandoverStatus.approved,
                        approved_by_id=reviewer.id)
    session.add(handover)
    session.flush()
    release = HandoverRelease(
        handover_id=handover.id, number=1, approved_by_id=reviewer.id,
        approved_by_name=reviewer.display_name, claims_json="[]",
    )
    session.add(release)
    session.commit()

    event_id = session.scalar(select(AuditEvent.id).limit(1))
    version_id = session.scalar(select(ClaimVersion.id).limit(1))
    release_id = release.id

    with pytest.raises(DBAPIError):
        session.execute(text("UPDATE audit_events SET actor='tampered' WHERE id=:id"),
                        {"id": event_id})
    session.rollback()
    with pytest.raises(DBAPIError):
        session.execute(text("DELETE FROM claim_versions WHERE id=:id"), {"id": version_id})
    session.rollback()
    with pytest.raises(DBAPIError):
        session.execute(text("UPDATE handover_releases SET claims_json='[]' WHERE id=:id"),
                        {"id": release_id})
    session.rollback()


def test_database_protects_stored_evidence_except_verification_flag(session, project):
    from app.models import Evidence

    add_claim(session, project, "Use Redis for locks.")
    session.commit()
    evidence = session.scalar(select(Evidence))
    evidence.snippet_verified = True
    session.commit()

    with pytest.raises(DBAPIError):
        session.execute(text("UPDATE evidence SET snippet='rewritten' WHERE id=:id"),
                        {"id": evidence.id})
    session.rollback()
    with pytest.raises(DBAPIError):
        session.execute(text("DELETE FROM evidence WHERE id=:id"), {"id": evidence.id})
    session.rollback()


def test_sensitivity_changes_create_a_reviewable_version(session, project):
    claim = add_claim(session, project, "Use Redis for locks.")
    claim.set_sensitivity(Sensitivity.restricted, "Meera", "Raised sensitivity after review")
    session.commit()

    assert claim.review_status == ReviewStatus.edited
    assert claim.versions[-1].sensitivity == "restricted"
    assert claim.versions[-1].note == "Raised sensitivity after review"
    assert json.loads(claim.versions[-1].evidence_json)[0]["snippet"] == "Use Redis for locks."
