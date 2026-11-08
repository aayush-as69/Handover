import pytest
from sqlalchemy import select

from app.access import effective_sensitivity
from app.conflicts import detect_conflicts, find_conflicts, visible_members
from app.enums import ClaimType, ConflictStatus, QuestionStatus, ReviewStatus, Role, Sensitivity
from app.models import Chunk, Claim, Conflict, Evidence, Project, Question, Source, User
from app.questions import answer, generate_questions
from app.redaction import redact, redact_text
from tests.test_web import PW, a_claim, act, client, env, login, token  # noqa: F401
from app.enums import SourceKind


def add_claim(session, project, statement, type=ClaimType.decision, *, topic=None, value=None,
              owner=None, sens=Sensitivity.team, kind=SourceKind.notes, status=None):
    src = Source(project_id=project.id, kind=kind, name="x.md", sensitivity=sens)
    ch = Chunk(source=src, idx=0, text=statement, locator="l1", sensitivity=sens)
    c = Claim.create(project_id=project.id, statement=statement, type=type, topic=topic,
                     value=value, owner=owner, sensitivity=sens)
    c.evidence.append(Evidence(chunk=ch, snippet=statement))
    session.add_all([src, ch, c])
    session.flush()
    if status == ReviewStatus.approved:
        c.approve("Meera Iyer")
    elif status == ReviewStatus.rejected:
        c.reject("Meera Iyer")
    return c


# ------------------------------------------------------------ conflict detection


def test_demo_conflict_is_found(session, demo_project):
    from app.extract.pipeline import run_extraction
    from app.extract.rules import RuleExtractor
    run_extraction(session, demo_project, RuleExtractor())
    cfs = detect_conflicts(session, demo_project)
    assert len(cfs) == 1 and cfs[0].topic == "datastore" and cfs[0].status == ConflictStatus.open
    texts = [session.get(Claim, i).statement for i in cfs[0].claim_ids]
    assert any("only datastore" in t for t in texts) and any("mongo" in t.lower() for t in texts)


def test_exclusive_claim_conflicts_with_a_different_technology(session, project):
    add_claim(session, project, "PostgreSQL is the only datastore.")
    add_claim(session, project, "We added a MongoDB feed.", ClaimType.risk)
    (f,) = find_conflicts(session.scalars(select(Claim)).all())
    assert "MongoDB" in f.reason and len(f.claims) == 2


@pytest.mark.parametrize("a,b", [
    ("PostgreSQL is the datastore.", "We added a MongoDB feed."),            # not exclusive
    ("PostgreSQL is the only datastore.", "Postgres backups run nightly."),  # same technology
    ("PostgreSQL is the only datastore.", "React is the frontend."),         # other category
    ("PostgreSQL is the only datastore.", "Which store: MongoDB or not?"),   # (type below)
])
def test_no_false_conflicts(session, project, a, b):
    add_claim(session, project, a)
    add_claim(session, project, b, ClaimType.open_question if "Which" in b else ClaimType.risk)
    assert find_conflicts(session.scalars(select(Claim)).all()) == []


def test_rejected_claims_do_not_conflict(session, project):
    add_claim(session, project, "PostgreSQL is the only datastore.")
    add_claim(session, project, "We added a MongoDB feed.", ClaimType.risk, status=ReviewStatus.rejected)
    assert detect_conflicts(session, project) == []


def test_explicit_topic_and_value_conflict(session, project):
    add_claim(session, project, "Launch is on Friday", topic="launch day", value="Friday")
    add_claim(session, project, "Launch is on Monday", topic="Launch Day", value="Monday")
    add_claim(session, project, "Launch is on Friday too", topic="launch day", value="friday")
    (f,) = find_conflicts(session.scalars(select(Claim)).all())
    assert len(f.claims) == 3 and "different values" in f.reason


def test_detection_is_repeatable_and_resolution_survives(session, project):
    add_claim(session, project, "PostgreSQL is the only datastore.")
    add_claim(session, project, "We added a MongoDB feed.", ClaimType.risk)
    (cf,) = detect_conflicts(session, project)
    from app.conflicts import resolve
    resolve(cf, "Meera", "Mongo feed will be removed")
    (cf,) = detect_conflicts(session, project)
    assert cf.status == ConflictStatus.resolved and len(session.scalars(select(Conflict)).all()) == 1
    add_claim(session, project, "Redis also stores sessions.", ClaimType.risk)   # new disagreement
    (cf,) = detect_conflicts(session, project)
    assert cf.status == ConflictStatus.open and cf.resolution is None


def test_conflict_goes_stale_when_the_dispute_disappears(session, project):
    add_claim(session, project, "PostgreSQL is the only datastore.")
    m = add_claim(session, project, "We added a MongoDB feed.", ClaimType.risk)
    detect_conflicts(session, project)
    m.reject("Meera")
    (cf,) = detect_conflicts(session, project)
    assert cf.status == ConflictStatus.stale


def test_resolving_needs_a_reason(session, project):
    add_claim(session, project, "PostgreSQL is the only datastore.")
    add_claim(session, project, "We added a MongoDB feed.", ClaimType.risk)
    (cf,) = detect_conflicts(session, project)
    from app.conflicts import resolve
    with pytest.raises(ValueError):
        resolve(cf, "Meera", "   ")


def test_conflict_hidden_when_clearance_leaves_fewer_than_two_claims(session, project):
    add_claim(session, project, "PostgreSQL is the only datastore.")
    add_claim(session, project, "We added a MongoDB feed.", ClaimType.risk, sens=Sensitivity.confidential)
    (cf,) = detect_conflicts(session, project)
    claims = {c.id: c for c in session.scalars(select(Claim))}
    assert len(visible_members(Role.admin, cf, claims)) == 2
    from app import access
    orig = dict(access.ROLE_CLEARANCE)
    access.ROLE_CLEARANCE[Role.approver] = Sensitivity.team
    try:
        assert visible_members(Role.approver, cf, claims) == []
    finally:
        access.ROLE_CLEARANCE.update(orig)


# ------------------------------------------------------------ questions


def kinds(session, project):
    return sorted(q.kind for q in generate_questions(session, project) if q.status == QuestionStatus.open)


def test_demo_questions_cover_the_seeded_gaps(session, demo_project):
    from app.extract.pipeline import run_extraction
    from app.extract.rules import RuleExtractor
    run_extraction(session, demo_project, RuleExtractor())
    detect_conflicts(session, demo_project)
    qs = generate_questions(session, demo_project)
    text = " ".join(q.text for q in qs)
    assert "Seat locks will go in Redis" in text                       # no reason
    assert any(q.kind == "no_owner" and "QR check-in" in q.text for q in qs)
    assert any(q.kind == "open_question" and "Refund policy" in q.text for q in qs)
    assert any(q.kind == "undocumented_promise" and "PayNest" in q.text for q in qs)
    assert any(q.kind == "conflict" for q in qs)
    # people-ownership decisions are not asked "why"
    assert not any(q.kind == "no_reason" and "Arjun keeps the frontend" in q.text for q in qs)


def test_a_reason_in_the_source_means_no_question(session, project):
    add_claim(session, project, "Use Redis for seat locks because it is fast.")
    add_claim(session, project, "Use MySQL for reports.")
    qs = generate_questions(session, project)
    assert [q.kind for q in qs] == ["no_reason"] and "MySQL" in qs[0].text


def test_github_only_risks_are_not_asked_about(session, project):
    add_claim(session, project, "Open issue #3: email fails", ClaimType.risk, kind=SourceKind.github)
    add_claim(session, project, "Gateway approval could be late.", ClaimType.risk)
    assert [q.kind for q in generate_questions(session, project)] == ["risk_no_owner"]


def test_questions_are_idempotent_and_close_when_the_gap_is_filled(session, project):
    c = add_claim(session, project, "Someone should look at QR check-in.", ClaimType.next_action)
    generate_questions(session, project)
    generate_questions(session, project)
    assert len(session.scalars(select(Question)).all()) == 1
    c.owner = "Kabir"
    (q,) = generate_questions(session, project)
    assert q.status == QuestionStatus.closed


def test_answers_survive_a_refresh_and_need_text(session, project):
    add_claim(session, project, "Someone should look at QR check-in.", ClaimType.next_action)
    (q,) = generate_questions(session, project)
    with pytest.raises(ValueError):
        answer(q, "Riya", "   ")
    with pytest.raises(ValueError):
        answer(q, "Riya", "x" * 2000)
    answer(q, "Riya", "Kabir will take it")
    (q,) = generate_questions(session, project)
    assert q.status == QuestionStatus.answered and q.answer == "Kabir will take it"


# ------------------------------------------------------------ redaction


def test_redaction_policy_by_role():
    t = "Mail a@b.example.com or call +91 98765 43210. Pledge INR 40,000. Due 2026-11-18, T7, #4."
    assert redact(Role.approver, t).text == t and redact(Role.admin, t).text == t
    v = redact(Role.viewer, t)
    assert "a@b.example.com" not in v.text and "98765" not in v.text and "INR 40,000" in v.text
    r = redact(Role.restricted, t)
    assert "INR 40,000" not in r.text and "2026-11-18" in r.text and "T7" in r.text and "#4" in r.text
    assert r.hidden == {"email", "phone", "amount"}


@pytest.mark.parametrize("text", ["Due 2026-11-18", "On 12/10/2026 we met", "issue #1234", "100 users", "v2.10.3"])
def test_redaction_leaves_dates_and_ids_alone(text):
    assert redact(Role.restricted, text).text == text


def test_redact_text_handles_empty():
    assert redact_text(Role.viewer, None) == "" and redact_text(Role.viewer, "") == ""


# ------------------------------------------------------------ the web


def approve_all_team(app, Session):
    c = login(app, "meera")
    with Session() as s:
        ids = [x.id for x in s.scalars(select(Claim)) if effective_sensitivity(x) == Sensitivity.team]
    for i in ids:
        act(c, i, "approve", note="ok")
    c.get("/handover")
    c.post("/handover/approve", data={"csrf": token(c, "/handover")})
    return c, ids


def test_handover_redacts_inside_claims_per_role(env):
    app, Session = env
    with Session() as s:
        p = s.scalar(select(Project))
        c = add_claim(s, p, "Sponsor contact is Priya, priya@sponsor.example.com, fee INR 40,000.",
                      ClaimType.contact)
        c.approve("Meera Iyer")
        cid = c.id
        s.commit()
    m = login(app, "meera")
    m.get("/handover")
    m.post("/handover/approve", data={"csrf": token(m, "/handover")})
    assert "priya@sponsor.example.com" in m.get("/handover").text
    v = login(app, "kabir").get("/handover").text
    assert "priya@sponsor.example.com" not in v and "[email hidden]" in v and "INR 40,000" in v
    r = login(app, "rao").get("/handover").text
    assert "[amount hidden]" in r and "INR 40,000" not in r and "priya@sponsor" not in r


def test_reviewer_can_preview_other_roles_but_others_cannot(env):
    app, Session = env
    with Session() as s:
        p = s.scalar(select(Project))
        add_claim(s, p, "Reach Priya at priya@sponsor.example.com", ClaimType.contact,
                  status=ReviewStatus.approved)
        s.commit()
    m = login(app, "meera")
    m.get("/handover")
    m.post("/handover/approve", data={"csrf": token(m, "/handover")})
    page = m.get("/handover?view_as=viewer").text
    assert "Previewing what a" in page and "priya@sponsor.example.com" not in page
    assert m.get("/handover?view_as=nonsense").status_code == 404
    k = login(app, "kabir")
    assert k.get("/handover?view_as=admin").status_code == 403
    assert "priya@sponsor.example.com" not in k.get("/handover?view_as=viewer").text


def test_conflict_warning_shows_only_visible_partners(env):
    app, Session = env
    with Session() as s:
        p = s.scalar(select(Project))
        add_claim(s, p, "PostgreSQL is the only datastore.", status=ReviewStatus.approved)
        add_claim(s, p, "We added a MongoDB event feed.", ClaimType.risk, status=ReviewStatus.approved)
        add_claim(s, p, "Redis stores contract data too.", ClaimType.risk, sens=Sensitivity.confidential,
                  status=ReviewStatus.approved)
        detect_conflicts(s, p)
        s.commit()
    m = login(app, "meera")
    m.get("/handover")
    m.post("/handover/approve", data={"csrf": token(m, "/handover")})
    k = login(app, "kabir").get("/handover").text
    assert "Sources disagree" in k and "MongoDB event feed" in k
    assert "Redis stores contract data" not in k            # hidden partner never mentioned


def test_questions_page_answer_flow_and_handover(env):
    app, Session = env
    with Session() as s:
        p = s.scalar(select(Project))
        c = add_claim(s, p, "Use MySQL for reports.", status=ReviewStatus.approved)
        generate_questions(s, p)
        s.commit()
        qid = s.scalars(select(Question).where(Question.text.contains("MySQL"))).first().id
    m = login(app, "riya")
    assert "Questions Before I Leave" in m.get("/questions").text
    t = token(m, "/questions")
    assert m.post(f"/questions/{qid}/answer", data={"csrf": "bad", "text": "x"}).status_code == 403
    m.post(f"/questions/{qid}/answer", data={"csrf": t, "text": "It was the only free option"})
    m.get("/handover")
    m.post("/handover/approve", data={"csrf": token(m, "/handover")})
    page = login(app, "kabir").get("/handover").text
    assert "It was the only free option" in page and "not checked against the sources" in page


def test_unapproved_claims_answers_are_not_shown(env):
    app, Session = env
    with Session() as s:
        p = s.scalar(select(Project))
        add_claim(s, p, "Use MySQL for reports.", status=ReviewStatus.approved)
        add_claim(s, p, "Use Cassandra for logs.")                         # never approved
        for q in generate_questions(s, p):
            answer(q, "Riya", "SECRET-ANSWER " + q.text[:20])
        s.commit()
    m = login(app, "meera")
    act_ids = None
    m.get("/handover")
    m.post("/handover/approve", data={"csrf": token(m, "/handover")})
    page = login(app, "kabir").get("/handover").text
    assert "Cassandra" not in page and "SECRET-ANSWER" in page and page.count("SECRET-ANSWER") == 1


def test_round3_pages_are_reviewer_only(env):
    app, Session = env
    for who in ("kabir", "rao"):
        c = login(app, who)
        for path in ("/conflicts", "/questions"):
            assert c.get(path).status_code == 403
        assert c.post("/conflicts/detect", data={"csrf": token(c, "/login")}).status_code == 403
        assert c.post("/questions/1/answer", data={"csrf": token(c, "/login"), "text": "x"}).status_code == 403
    assert client(app).get("/questions").status_code == 303


def test_conflict_resolution_form(env):
    app, Session = env
    with Session() as s:
        p = s.scalar(select(Project))
        add_claim(s, p, "PostgreSQL is the only datastore.")
        add_claim(s, p, "We added a MongoDB feed.", ClaimType.risk)
        detect_conflicts(s, p)
        s.commit()
        cid = s.scalar(select(Conflict)).id
    m = login(app, "meera")
    assert "datastore" in m.get("/conflicts").text
    t = token(m, "/conflicts")
    assert m.post(f"/conflicts/{cid}/resolve", data={"csrf": "bad", "note": "x"}).status_code == 403
    m.post(f"/conflicts/{cid}/resolve", data={"csrf": t, "note": "  "})
    with Session() as s:
        assert s.get(Conflict, cid).status == ConflictStatus.open
    m.post(f"/conflicts/{cid}/resolve", data={"csrf": t, "note": "Mongo is removed"})
    with Session() as s:
        assert s.get(Conflict, cid).status == ConflictStatus.resolved
    assert m.post("/conflicts/9999/resolve", data={"csrf": t, "note": "x"}).status_code == 404


def test_an_answer_is_withheld_unless_every_linked_claim_is_visible(env):
    app, Session = env
    with Session() as s:
        p = s.scalar(select(Project))
        for old in s.scalars(select(Claim)).all():
            old.reject("setup")                      # keep demo claims out of this scenario
        a = add_claim(s, p, "PostgreSQL is the only datastore.", status=ReviewStatus.approved)
        b = add_claim(s, p, "We added a MongoDB feed.", ClaimType.risk, status=ReviewStatus.approved)
        r = add_claim(s, p, "Redis holds contract data.", ClaimType.risk, sens=Sensitivity.confidential,
                      status=ReviewStatus.approved)
        detect_conflicts(s, p)
        mine = [q for q in generate_questions(s, p) if q.kind == "conflict" and a.id in q.claim_ids
                and r.id in q.claim_ids]
        assert len(mine) == 1 and b.id in mine[0].claim_ids
        answer(mine[0], "Riya", "CONFLICT-ANSWER")
        s.commit()
    m = login(app, "meera")
    m.get("/handover")
    m.post("/handover/approve", data={"csrf": token(m, "/handover")})
    assert "CONFLICT-ANSWER" not in login(app, "kabir").get("/handover").text
    assert "CONFLICT-ANSWER" in m.get("/handover").text


def test_questions_above_a_reviewers_clearance_are_hidden_and_closed_to_actions(env):
    app, Session = env
    from app import access
    with Session() as s:
        p = s.scalar(select(Project))
        add_claim(s, p, "Use Cassandra for contracts.", sens=Sensitivity.confidential)
        generate_questions(s, p)
        s.commit()
        qid = s.scalars(select(Question).where(Question.text.contains("Cassandra"))).first().id
        s.add(User(username="low", display_name="Low", role=Role.approver,
                   password_hash=__import__("app.security", fromlist=["x"]).hash_password(PW)))
        s.commit()
    orig = dict(access.ROLE_CLEARANCE)
    access.ROLE_CLEARANCE[Role.approver] = Sensitivity.team
    try:
        c = login(app, "low")
        assert "Cassandra" not in c.get("/questions").text
        r = c.post(f"/questions/{qid}/answer", data={"csrf": token(c, "/questions"), "text": "leak"})
        assert r.status_code == 404
    finally:
        access.ROLE_CLEARANCE.update(orig)
