"""Multiple projects, the audit log, the decision timeline and the bus-factor view."""

from datetime import datetime

from alembic import command
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from app.access import effective_sensitivity
from app.audit_log import audit_entries
from app.db import alembic_config, migrate
from app.enums import ClaimType, ReviewStatus, Role, Sensitivity, SourceKind
from app.models import Chunk, Claim, Evidence, Project, ProjectMember, Source, User
from app.projects import accessible_projects, add_member
from app.timeline import build_bus_factor, build_timeline
from tests.test_web import PW, act, client, env, login, token  # noqa: F401


def _other_project(Session, *, with_claim=True, members=()):
    with Session() as s:
        p = Project(name="Library App", outgoing_member="Dev Patel")
        s.add(p)
        s.flush()
        cid = None
        if with_claim:
            src = Source(project_id=p.id, kind=SourceKind.notes, name="lib.md", sensitivity=Sensitivity.team)
            ch = Chunk(source=src, idx=0, text="We chose SQLite for the library catalogue.",
                       locator="line 1", sensitivity=Sensitivity.team, author="Dev Patel",
                       occurred_at=datetime(2026, 10, 2))
            c = Claim.create(project_id=p.id, statement="Catalogue uses SQLite", type=ClaimType.decision,
                             sensitivity=Sensitivity.team)
            c.evidence.append(Evidence(chunk=ch, snippet="We chose SQLite for the library catalogue"))
            s.add_all([src, ch, c])
            s.flush()
            cid = c.id
        for username in members:
            add_member(s, p, s.scalar(select(User).where(User.username == username)), "test")
        s.commit()
        return p.id, cid


def test_a_person_without_membership_cannot_reach_another_project(env):
    app, Session = env
    pid, cid = _other_project(Session)
    c = login(app, "meera")                                   # approver, member of the demo only
    assert c.get(f"/review/claims/{cid}").status_code == 404
    r = c.post("/projects/switch", data={"project_id": pid, "csrf": token(c, "/projects")})
    assert r.status_code == 404
    assert "Library App" not in c.get("/projects").text
    assert "Library App" not in c.get("/review").text


def test_membership_grants_access_and_switching_changes_what_is_shown(env):
    app, Session = env
    pid, cid = _other_project(Session, members=["meera"])
    c = login(app, "meera")
    assert "Library App" in c.get("/projects").text
    assert c.get(f"/review/claims/{cid}").status_code == 200
    before = c.get("/review").text
    assert "Catalogue uses SQLite" not in before
    r = c.post("/projects/switch", data={"project_id": pid, "csrf": token(c, "/projects")})
    assert r.status_code == 303
    after = c.get("/review").text
    assert "Catalogue uses SQLite" in after
    assert "Seat locks" not in after                           # the demo project's data stays out


def test_chunks_of_another_project_are_not_readable_without_membership(env):
    app, Session = env
    _other_project(Session)
    with Session() as s:
        chunk_id = s.scalar(select(Chunk.id).join(Source).join(Project).where(Project.name == "Library App"))
    assert login(app, "meera").get(f"/review/chunks/{chunk_id}").status_code == 404
    assert login(app, "riya").get(f"/review/chunks/{chunk_id}").status_code == 200   # admin


def test_someone_with_no_projects_gets_a_plain_message_not_data(env):
    app, Session = env
    with Session() as s:
        s.add(User(username="newbie", display_name="Newbie", role=Role.approver,
                   password_hash=__import__("app.security", fromlist=["x"]).hash_password(PW)))
        s.commit()
    c = login(app, "newbie")
    assert c.get("/review").status_code == 404
    assert "not been added" in c.get("/review").text
    assert c.get("/projects").status_code == 200


def test_only_admins_create_projects_and_manage_people(env):
    app, Session = env
    m = login(app, "meera")
    assert m.post("/projects/new", data={"name": "X", "csrf": token(m, "/projects")}).status_code == 403
    a = login(app, "riya")
    r = a.post("/projects/new", data={"name": "Robotics Club", "outgoing": "Sam",
                                      "csrf": token(a, "/projects")})
    assert r.status_code == 303
    with Session() as s:
        proj = s.scalar(select(Project).where(Project.name == "Robotics Club"))
        kabir = s.scalar(select(User).where(User.username == "kabir"))
        pid, kid = proj.id, kabir.id
        assert not [p for p in accessible_projects(s, kabir) if p.id == pid]
    a.post(f"/projects/{pid}/members/add", data={"user_id": kid, "csrf": token(a, "/projects")})
    with Session() as s:
        assert [p.id for p in accessible_projects(s, s.get(User, kid)) if p.id == pid]
    a.post(f"/projects/{pid}/members/remove", data={"user_id": kid, "csrf": token(a, "/projects")})
    with Session() as s:
        assert not [p for p in accessible_projects(s, s.get(User, kid)) if p.id == pid]
    # duplicate names are refused
    a.post("/projects/new", data={"name": "robotics club", "csrf": token(a, "/projects")})
    with Session() as s:
        assert len(s.scalars(select(Project).where(Project.name.ilike("robotics club"))).all()) == 1


def test_removed_member_loses_the_project_on_their_next_request(env):
    app, Session = env
    pid, _ = _other_project(Session, members=["meera"])
    c = login(app, "meera")
    c.post("/projects/switch", data={"project_id": pid, "csrf": token(c, "/projects")})
    assert "Catalogue uses SQLite" in c.get("/review").text
    with Session() as s:
        s.execute(text("DELETE FROM project_members WHERE project_id=:p"), {"p": pid})
        s.commit()
    page = c.get("/review").text                                # falls back to the demo project
    assert "Catalogue uses SQLite" not in page


# ------------------------------------------------------------------ audit log and releases


def test_audit_log_is_for_reviewers_and_shows_approvals_and_acknowledgements(env):
    app, Session = env
    assert login(app, "kabir").get("/audit").status_code == 403
    m = login(app, "meera")
    with Session() as s:
        cid = s.scalar(select(Claim.id).where(Claim.confidence == "verified").order_by(Claim.id))
    act(m, cid, "approve")
    m.post("/handover/approve", data={"csrf": token(m, "/handover")})
    k = login(app, "kabir")
    k.post("/handover/acknowledge", data={"csrf": token(k, "/handover")})
    page = m.get("/audit").text
    assert "Meera Iyer" in page and "approved claim" in page
    assert "signed off release 1" in page
    assert "Kabir Mehta" in page and "acknowledged release 1" in page
    assert "Kabir Mehta" in m.get("/audit?kind=acknowledgement").text
    assert "signed off release 1" not in m.get("/audit?kind=acknowledgement").text


def test_release_history_names_who_acknowledged(env):
    app, Session = env
    m = login(app, "meera")
    with Session() as s:
        cid = s.scalar(select(Claim.id).where(Claim.confidence == "verified").order_by(Claim.id))
    act(m, cid, "approve")
    m.post("/handover/approve", data={"csrf": token(m, "/handover")})
    assert "nobody yet" in m.get("/handover/releases").text
    k = login(app, "kabir")
    k.post("/handover/acknowledge", data={"csrf": token(k, "/handover")})
    page = m.get("/handover/releases").text
    assert "Kabir Mehta" in page and "nobody yet" not in page


def test_audit_entries_hide_claims_above_the_role_clearance(env):
    _, Session = env
    with Session() as s:
        project = s.scalar(select(Project))
        conf = next(c for c in s.scalars(select(Claim)) if effective_sensitivity(c) == Sensitivity.confidential)
        team = next(c for c in s.scalars(select(Claim)) if effective_sensitivity(c) == Sensitivity.team)
        shown = {e.claim_id for e in audit_entries(s, project, Role.viewer, "claim")}
        assert team.id in shown and conf.id not in shown
        assert conf.id in {e.claim_id for e in audit_entries(s, project, Role.admin, "claim")}


def test_audit_log_is_scoped_to_the_current_project(env):
    app, Session = env
    pid, cid = _other_project(Session, members=["meera"])
    m = login(app, "meera")
    assert "Catalogue uses" not in m.get("/audit").text and f"claim {cid} " not in m.get("/audit").text
    m.post("/projects/switch", data={"project_id": pid, "csrf": token(m, "/projects")})
    assert f"drafted claim {cid}" in m.get("/audit").text


# ------------------------------------------------------------------ timeline


def _approve_and_sign(app, Session, ids):
    m = login(app, "meera")
    for cid in ids:
        act(m, cid, "approve", note="checked")
    m.post("/handover/approve", data={"csrf": token(m, "/handover")})
    return m


def test_timeline_waits_for_a_sign_off_for_readers(env):
    app, Session = env
    k = login(app, "kabir")
    assert "Catalogue" not in k.get("/timeline").text
    assert "Decision timeline" not in k.get("/timeline").text          # the pending page


def test_timeline_shows_approved_dated_claims_in_order_and_respects_role(env):
    app, Session = env
    with Session() as s:
        decisions = [c for c in s.scalars(select(Claim).where(Claim.type == ClaimType.decision).order_by(Claim.id))]
        team = [c.id for c in decisions if effective_sensitivity(c) != Sensitivity.confidential]
        conf = [c.id for c in decisions if effective_sensitivity(c) == Sensitivity.confidential]
    assert team
    ids = team + conf
    _approve_and_sign(app, Session, ids)
    with Session() as s:
        items = build_timeline(s, s.scalar(select(Project)), Role.viewer)
        assert items and all(i.approved for i in items)
        dated = [i.when for i in items if i.when]
        assert dated == sorted(dated)                                # oldest first
        assert all(i.claim.review_status == ReviewStatus.approved for i in items)
        viewer_ids = {i.claim.id for i in items}
        assert not viewer_ids & set(conf) or all(
            effective_sensitivity(s.get(Claim, i)) != Sensitivity.confidential for i in viewer_ids & set(conf))
        rao = {i.claim.id for i in build_timeline(s, s.scalar(select(Project)), Role.restricted)}
        assert all(effective_sensitivity(s.get(Claim, i)).value in ("public", "team") for i in rao)
    page = login(app, "kabir").get("/timeline").text
    assert "Decision timeline" in page
    assert login(app, "kabir").get("/timeline?type=decision").status_code == 200


def test_drafts_appear_only_for_reviewers_who_ask(env):
    app, Session = env
    with Session() as s:
        project = s.scalar(select(Project))
        none = build_timeline(s, project, Role.approver)
        some = build_timeline(s, project, Role.approver, include_drafts=True)
        assert none == [] and some and not any(i.approved for i in some)
        # a viewer asking for drafts still gets only approved claims
        assert build_timeline(s, project, Role.viewer, include_drafts=True) == []
    k = login(app, "kabir")
    assert "not approved yet" not in k.get("/timeline?drafts=1").text
    assert "not approved yet" in login(app, "meera").get("/timeline?drafts=1").text


def test_rejected_claims_never_reach_the_timeline(env):
    app, Session = env
    with Session() as s:
        cid = s.scalar(select(Claim.id).where(Claim.type == ClaimType.decision).order_by(Claim.id))
    m = login(app, "meera")
    act(m, cid, "reject", note="wrong")
    with Session() as s:
        assert cid not in {i.claim.id for i in build_timeline(s, s.scalar(select(Project)), Role.admin, include_drafts=True)}


# ------------------------------------------------------------------ bus factor


def test_bus_factor_counts_claims_resting_on_one_persons_records(env):
    _, Session = env
    with Session() as s:
        p = Project(name="BF")
        s.add(p)
        s.flush()
        src = Source(project_id=p.id, kind=SourceKind.chat, name="c", sensitivity=Sensitivity.team)
        a = Chunk(source=src, idx=0, text="a", author="Asha", sensitivity=Sensitivity.team)
        b = Chunk(source=src, idx=1, text="b", author="Bo", sensitivity=Sensitivity.team)
        n = Chunk(source=src, idx=2, text="n", author=None, sensitivity=Sensitivity.team)
        only_a = Claim.create(project_id=p.id, statement="only Asha knows", type=ClaimType.risk, sensitivity=Sensitivity.team)
        only_a.evidence.append(Evidence(chunk=a, snippet="a"))
        both = Claim.create(project_id=p.id, statement="shared", type=ClaimType.risk, sensitivity=Sensitivity.team)
        both.evidence += [Evidence(chunk=a, snippet="a"), Evidence(chunk=b, snippet="b")]
        anon = Claim.create(project_id=p.id, statement="no author", type=ClaimType.risk, sensitivity=Sensitivity.team)
        anon.evidence.append(Evidence(chunk=n, snippet="n"))
        rejected = Claim.create(project_id=p.id, statement="gone", type=ClaimType.risk, sensitivity=Sensitivity.team)
        rejected.evidence.append(Evidence(chunk=a, snippet="a"))
        rejected.reject("t")
        s.add_all([src, a, b, n, only_a, both, anon, rejected])
        s.commit()
        r = build_bus_factor(s, p, Role.admin)
        by = {x.person: x for x in r.people}
        assert [c.statement for c in by["Asha"].claims] == ["only Asha knows"]
        assert by["Asha"].total_claims_touched == 2 and by["Bo"].sole == 0
        assert r.unattributed == 1 and r.examined == 3
        assert r.people[0].person == "Asha"                         # biggest risk first


def test_bus_factor_page_is_reviewer_only_and_skips_confidential_for_lower_clearance(env):
    app, Session = env
    assert login(app, "kabir").get("/bus-factor").status_code == 403
    page = login(app, "meera").get("/bus-factor").text
    assert "Bus-factor view" in page and "Riya Sharma" in page
    with Session() as s:
        project = s.scalar(select(Project))
        lowered = build_bus_factor(s, project, Role.restricted)
        full = build_bus_factor(s, project, Role.admin)
        assert lowered.examined < full.examined


# ------------------------------------------------------------------ migration


def test_migration_gives_existing_users_access_to_existing_projects(tmp_path):
    from sqlalchemy import create_engine
    eng = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with eng.begin() as conn:
        command.upgrade(alembic_config(conn), "0002")
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO projects (name, description, created_at) VALUES ('Old','',CURRENT_TIMESTAMP)"))
        for n in ("a", "b"):
            conn.execute(text("INSERT INTO users (username, display_name, role, session_version) "
                              f"VALUES ('{n}','{n}','viewer',1)"))
    migrate(eng)
    with eng.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM project_members")).scalar() == 2


def test_guide_page_is_role_aware(env):
    app, _ = env
    reviewer = login(app, "meera").get("/guide")
    assert reviewer.status_code == 200
    assert "How Handover works" in reviewer.text and "/conflicts" in reviewer.text
    viewer = login(app, "kabir").get("/guide")
    assert viewer.status_code == 200
    assert "/conflicts" not in viewer.text and "acknowledge" in viewer.text
    assert client(app).get("/guide").status_code in (303, 401)


def test_takeover_brief_respects_role_and_release(env):
    app, Session = env
    meera = login(app, "meera")
    # Nothing is signed off yet: readers get the pending page, reviewers a draft preview.
    assert "Draft preview" in meera.get("/handover/brief").text
    kabir = login(app, "kabir")
    assert "Where to start" not in kabir.get("/handover/brief").text
    with Session() as s:
        for c in s.scalars(select(Claim)):
            c.review_status = ReviewStatus.approved
        s.commit()
    r = meera.post("/handover/approve", data={"csrf": token(meera, "/handover")})
    assert r.status_code == 303
    page = kabir.get("/handover/brief")
    assert page.status_code == 200 and "Where to start" in page.text
    restricted = login(app, "rao").get("/handover/brief").text
    assert restricted.count("pill") <= page.text.count("pill")
    assert kabir.get("/handover/brief?view_as=admin").status_code == 403
