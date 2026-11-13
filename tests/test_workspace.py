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


def test_claim_connections_show_recorded_links_and_hide_above_clearance(env):
    app, Session = env
    from app.connections import claim_connections
    with Session() as s:
        meera = s.scalar(select(User).where(User.username == "meera"))
        project = s.scalar(select(Project))
        claims = list(s.scalars(select(Claim).where(Claim.project_id == project.id)))
        with_ev = next(c for c in claims if c.evidence)
        conn = claim_connections(s, meera, with_ev)
        assert conn.sources
        assert all(o.id != with_ev.id for o, _ in conn.related)
        # An approver can never be shown a related claim above their clearance.
        from app.access import visible_in_review
        assert all(visible_in_review(meera.role, o) for o, _ in conn.related)
    page = login(app, "meera").get(f"/review/claims/{with_ev.id}")
    assert page.status_code == 200 and "Connections" in page.text


def test_freshness_states_and_decay_page(env):
    from datetime import timedelta
    from app.freshness import claim_freshness, decay_report
    app, Session = env
    now = datetime(2026, 11, 12)
    with Session() as s:
        project = s.scalar(select(Project))
        by_age = {}
        for c in s.scalars(select(Claim).where(Claim.project_id == project.id)):
            f = claim_freshness(c, now)
            by_age.setdefault(f.state, []).append(c)
            if f.newest:
                assert f.age_days == (now - f.newest).days
        # Pushing "now" far ahead turns every dated claim stale; undated ones stay undated.
        later = now + timedelta(days=400)
        assert all(claim_freshness(c, later).state in ("stale", "undated")
                   for cs in by_age.values() for c in cs)
        meera = s.scalar(select(User).where(User.username == "meera"))
        rows = decay_report(s, project, meera.role, later)
        assert rows and rows[0].fresh.state == "stale"
    assert login(app, "meera").get("/freshness").status_code == 200
    assert login(app, "kabir").get("/freshness").status_code in (403, 404)


def test_release_diff_lists_added_updated_dropped(env):
    from app.models import HandoverRelease
    from app.release_diff import release_diff
    app, Session = env
    with Session() as s:
        project = s.scalar(select(Project))
        ids = [c.id for c in s.scalars(select(Claim).where(Claim.project_id == project.id).limit(3))]
        old = HandoverRelease(handover_id=1, number=1, approved_by_id=1, approved_by_name="x",
                              approved_at=datetime(2026, 11, 1), claims_json=f"[[{ids[0]},1],[{ids[1]},1]]")
        new = HandoverRelease(handover_id=1, number=2, approved_by_id=1, approved_by_name="x",
                              approved_at=datetime(2026, 11, 8), claims_json=f"[[{ids[1]},2],[{ids[2]},1]]")
        meera = s.scalar(select(User).where(User.username == "meera"))
        d = release_diff(s, meera.role, new, old, project.id)
        assert [c.id for c, _ in d.added] == [ids[2]]
        assert [c.id for c, *_ in d.updated] == [ids[1]]
        assert [c.id for c, _ in d.removed] == [ids[0]]
        assert release_diff(s, meera.role, old, None, project.id).previous is None


def test_audit_filters_and_links(env):
    from app.audit_log import audit_entries, filter_entries
    app, Session = env
    with Session() as s:
        project = s.scalar(select(Project))
        meera = s.scalar(select(User).where(User.username == "meera"))
        entries = audit_entries(s, project, meera.role)
    assert entries
    who = entries[0].actor
    assert all(who.lower() in e.actor.lower() for e in filter_entries(entries, actor=who))
    assert filter_entries(entries, text="zzz-no-such-text") == []
    day = entries[0].at.replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0)
    assert filter_entries(entries, start=day, end=day)       # the end day counts in full
    c = login(app, "meera")
    page = c.get(f"/audit?actor={who.split()[0]}&start=2000-01-01&end=2100-01-01&q=")
    assert page.status_code == 200 and "event(s)" in page.text
    assert c.get("/audit?start=not-a-date").status_code == 200   # bad input is ignored, not an error


def test_concentration_never_exceeds_what_exists(env):
    from app.timeline import build_concentration
    app, Session = env
    with Session() as s:
        project = s.scalar(select(Project))
        meera = s.scalar(select(User).where(User.username == "meera"))
        for row in build_concentration(s, project, meera.role):
            assert 0 <= row.top_sole <= row.attributed and 0 <= row.share <= 100
    assert "Knowledge concentration" in login(app, "meera").get("/bus-factor").text \
        or "No claim has a named author" in login(app, "meera").get("/bus-factor").text


def test_onboarding_walks_through_and_respects_role(env):
    app, Session = env
    meera = login(app, "meera")
    first = meera.get("/onboarding")
    assert first.status_code == 200 and ("Step 1 of" in first.text or "nothing to walk through" in first.text)
    assert meera.get("/onboarding?step=999").status_code == 200       # past the end is clamped
    # Nothing is published yet, so a reader gets the pending page and no content.
    assert "Step 1 of" not in login(app, "kabir").get("/onboarding").text
    with Session() as s:
        for c in s.scalars(select(Claim)):
            c.review_status = ReviewStatus.approved
        s.commit()
    assert meera.post("/handover/approve", data={"csrf": token(meera, "/handover")}).status_code == 303
    kabir = login(app, "kabir")
    assert "Step 1 of" in kabir.get("/onboarding").text
    assert kabir.get("/onboarding?view_as=admin").status_code == 403
    assert "What you went through" in kabir.get("/onboarding?step=99").text


def test_quality_page_is_reviewer_only(env):
    app, Session = env
    page = login(app, "meera").get("/quality")
    assert page.status_code == 200 and "rules-v1" in page.text and "Not measured yet" in page.text
    assert login(app, "kabir").get("/quality").status_code in (403, 404)


def _set_role(Session, project_id, username, role):
    from app.models import ProjectMember
    with Session() as s:
        uid = s.scalar(select(User.id).where(User.username == username))
        row = s.scalar(select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == uid))
        row.role = role
        s.commit()


def test_a_role_can_differ_per_project(env):
    from app.enums import Role
    from app.models import ProjectMember
    app, Session = env
    pid, cid = _other_project(Session, members=["kabir", "meera"])
    _set_role(Session, pid, "kabir", Role.approver)     # a viewer by default, approver in Library App
    _set_role(Session, pid, "meera", Role.viewer)       # an approver by default, viewer in Library App

    kabir = login(app, "kabir")
    assert kabir.get("/review").status_code == 403       # demo project: still just a viewer
    kabir.post("/projects/switch", data={"project_id": pid, "csrf": token(kabir, "/projects")})
    assert kabir.get("/review").status_code == 200       # Library App: approver
    assert kabir.get(f"/review/claims/{cid}").status_code == 200

    meera = login(app, "meera")
    assert meera.get("/review").status_code == 200       # demo project: approver
    meera.post("/projects/switch", data={"project_id": pid, "csrf": token(meera, "/projects")})
    assert meera.get("/review").status_code == 403       # Library App: viewer only
    assert meera.get("/handover").status_code == 200

    # Taking effect for a request must never change the account itself.
    with Session() as s:
        roles = {u.username: u.role.value for u in s.scalars(select(User))}
    assert roles["kabir"] == "viewer" and roles["meera"] == "approver"


def test_admin_stays_admin_and_cannot_be_given_a_project_role(env):
    from app.enums import Role
    app, Session = env
    pid, _ = _other_project(Session, members=["kabir", "riya"])
    riya = login(app, "riya")
    t = token(riya, "/projects")
    with Session() as s:
        ids = {u.username: u.id for u in s.scalars(select(User))}
    # Admin is never a per-project role, and an admin's own role cannot be lowered per project.
    r = riya.post(f"/projects/{pid}/members/role", data={"user_id": ids["kabir"], "role": "admin", "csrf": t},
                  follow_redirects=True)
    assert "whole workspace" in r.text
    r = riya.post(f"/projects/{pid}/members/role", data={"user_id": ids["riya"], "role": "viewer", "csrf": t},
                  follow_redirects=True)
    assert "admin everywhere" in r.text
    assert riya.get("/admin/sources").status_code == 200
    with Session() as s:
        assert s.scalar(select(User.role).where(User.username == "kabir")) == Role.viewer


def test_admin_sets_and_clears_a_project_role_and_it_is_applied(env):
    from app.enums import Role
    app, Session = env
    pid, _ = _other_project(Session, members=["kabir"])
    riya = login(app, "riya")
    t = token(riya, "/projects")
    with Session() as s:
        kid = s.scalar(select(User.id).where(User.username == "kabir"))
    r = riya.post(f"/projects/{pid}/members/role", data={"user_id": kid, "role": "approver", "csrf": t},
                  follow_redirects=True)
    assert "is now approver here" in r.text
    kabir = login(app, "kabir")
    kabir.post("/projects/switch", data={"project_id": pid, "csrf": token(kabir, "/projects")})
    assert kabir.get("/review").status_code == 200
    assert "Your role here: approver" in kabir.get("/projects").text
    riya.post(f"/projects/{pid}/members/role", data={"user_id": kid, "role": "", "csrf": t})
    assert kabir.get("/review").status_code == 403       # back to the default viewer role
    # Only admins may do this.
    assert kabir.post(f"/projects/{pid}/members/role",
                      data={"user_id": kid, "role": "approver", "csrf": token(kabir, "/projects")}
                      ).status_code == 403


def test_project_role_is_checked_on_actions_not_just_pages(env):
    from app.enums import Role
    app, Session = env
    pid, cid = _other_project(Session, members=["meera"])
    _set_role(Session, pid, "meera", Role.viewer)
    meera = login(app, "meera")
    meera.post("/projects/switch", data={"project_id": pid, "csrf": token(meera, "/projects")})
    r = meera.post(f"/review/claims/{cid}/approve", data={"csrf": token(meera, "/projects")})
    assert r.status_code in (403, 404)
    with Session() as s:
        assert s.get(Claim, cid).review_status.value == "generated"


def test_claim_page_shows_evidence_breakdown_and_source_tree(env):
    from app.connections import evidence_breakdown
    app, Session = env
    with Session() as s:
        meera = s.scalar(select(User).where(User.username == "meera"))
        project = s.scalar(select(Project))
        claim = next(c for c in s.scalars(select(Claim).where(Claim.project_id == project.id)) if c.evidence)
        b = evidence_breakdown(meera, claim)
        assert 0 <= b.found <= b.quotes and b.sources == len(b.tree)
        cid = claim.id
    page = login(app, "meera").get(f"/review/claims/{cid}").text
    assert "Evidence breakdown" in page and "Where it comes from" in page


def test_conflict_cards_cite_their_sources(env):
    from app.conflicts import detect_conflicts
    app, Session = env
    with Session() as s:
        detect_conflicts(s, s.scalar(select(Project)))
        s.commit()
    page = login(app, "meera").get("/conflicts").text
    assert "conflict-member" in page and "class=\"cite\"" in page


def test_sources_page_shows_load_and_content_dates(env):
    page = login(env[0], "riya").get("/admin/sources").text
    assert "Newest content" in page and "Loaded" in page


def test_bulk_review_only_offers_clean_claims_and_rechecks_on_submit(env):
    from app.bulk_web import eligible_claims
    from app.enums import Confidence
    app, Session = env
    with Session() as s:
        meera = s.scalar(select(User).where(User.username == "meera"))
        project = s.scalar(select(Project))
        offered = eligible_claims(s, meera, project)
        assert offered and all(c.confidence == Confidence.verified for c in offered)
        assert all(c.review_status.value in ("generated", "edited") for c in offered)
        ids = [c.id for c in offered][:2]
        other = offered[2]
        other.confidence = Confidence.unsupported      # no longer clean
        other_id = other.id
        s.commit()
    c = login(app, "meera")
    assert "Approve clean claims together" in c.get("/review/bulk").text
    t = token(c, "/review/bulk")
    # One eligible claim, plus one that is not clean: only the clean one is approved.
    r = c.post("/review/bulk", data={"csrf": t, "claim_id": [ids[0], other_id]}, follow_redirects=True)
    assert "Approved 1 claim(s). Skipped 1" in r.text
    with Session() as s:
        assert s.get(Claim, ids[0]).review_status.value == "approved"
        assert s.get(Claim, other_id).review_status.value != "approved"
    # Not open to readers, and a bad CSRF token changes nothing.
    assert login(app, "kabir").get("/review/bulk").status_code == 403
    assert c.post("/review/bulk", data={"csrf": "bad", "claim_id": [ids[1]]}).status_code in (400, 403)
    with Session() as s:
        assert s.get(Claim, ids[1]).review_status.value != "approved"


def test_markdown_export_matches_role_and_needs_a_release_for_readers(env):
    app, Session = env
    kabir = login(app, "kabir")
    assert kabir.get("/handover/export.md").status_code == 404      # nothing published yet
    with Session() as s:
        for c in s.scalars(select(Claim)):
            c.review_status = ReviewStatus.approved
        s.commit()
    meera = login(app, "meera")
    assert meera.post("/handover/approve", data={"csrf": token(meera, "/handover")}).status_code == 303
    r = kabir.get("/handover/export.md")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert r.text.startswith("# Takeover brief:") and "does not mean the claim is true" in r.text
    assert kabir.get("/handover/export.md?view_as=admin").status_code == 403
    assert "restricted" in login(app, "rao").get("/handover/export.md").text
