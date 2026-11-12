"""Pages for the handover itself and for loading sources (admin)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .access import effective_sensitivity
from .conflicts import detect_conflicts
from .db import get_session
from .enums import REVIEWER_ROLES, ChangeType, Role, Sensitivity, SourceKind
from .extract import ExtractionError
from .extract.llm import llm_from_env
from .extract.pipeline import run_extraction
from .extract.rules import RuleExtractor
from .handover import (HandoverError, acknowledge, is_stale, answered_questions, conflict_notes,
                       latest_release, release_state, releases, approve_handover, build_sections, can_view,
                       get_handover, get_or_create_handover, pending_count, withdraw_handover)
from .questions import generate_questions
from .ingest.errors import IngestError
from .ingest.service import MAX_BYTES, decode_upload, ingest_source
from .models import Acknowledgement, User
from .redaction import redact_text
from .web import check_csrf, current_user, project_for, render

router = APIRouter()


def require_user(user: Optional[User] = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != Role.admin:
        raise HTTPException(status_code=403, detail="Only admins can load sources.")
    return user


def _flash(request: Request, msg: str, to: str):
    request.session["flash"] = msg
    return RedirectResponse(to, status_code=303)


# ------------------------------------------------------------------ the handover


@router.get("/handover")
def handover_page(request: Request, user: User = Depends(require_user),
                  session: Session = Depends(get_session), view_as: str = ""):
    project = project_for(session, request, user)
    handover = get_handover(session, project)
    if handover is None and user.role in REVIEWER_ROLES:
        handover = get_or_create_handover(session, project)
        session.commit()
    if not can_view(user, handover) or (
            user.role not in REVIEWER_ROLES and is_stale(session, project, handover)):
        # Same page whether nothing exists, it is not signed off, or the sign-off went stale.
        return render(request, "handover_pending.html", user, project=project)
    role = user.role
    if view_as:
        try:
            role = Role(view_as)
        except ValueError:
            raise HTTPException(status_code=404, detail="Unknown role.") from None
        if role != user.role and user.role not in REVIEWER_ROLES:
            raise HTTPException(status_code=403, detail="Only reviewers can preview another role.")
    sections = build_sections(session, project, user, role)
    shown = {c.id for sec in sections for c in sec.claims}
    hide = lambda text: redact_text(role, text)
    rel = latest_release(session, handover)
    state = release_state(session, project, handover)
    acks = session.scalars(select(Acknowledgement).where(
        Acknowledgement.release_id == rel.id)).all() if rel else []
    ack_users = {u.id: u for u in session.scalars(
        select(User).where(User.id.in_([a.user_id for a in acks])))} if acks else {}
    is_reviewer = user.role in REVIEWER_ROLES
    return render(
        request, "handover.html", user, project=project, handover=handover, sections=sections,
        release=rel, state=state, stale=is_stale(session, project, handover),
        acked=any(a.user_id == user.id for a in acks), is_reviewer=is_reviewer,
        acks=[(ack_users[a.user_id].display_name, a.acknowledged_at) for a in acks]
        if is_reviewer else [],
        pending=pending_count(session, project) if is_reviewer else 0,
        sens=effective_sensitivity, view_role=role, previewing=role != user.role,
        roles=[r.value for r in Role], hide=hide,
        conflicts=conflict_notes(session, project, shown),
        answers=answered_questions(session, project, shown),
        approvals=_latest_approvals(session, [c.id for s in sections for c in s.claims]),
    )


def _latest_approvals(session, claim_ids):
    """The newest approval record for each claim, in one query (not one per claim)."""
    from .models import ClaimVersion
    out = {cid: None for cid in claim_ids}
    if claim_ids:
        for v in session.scalars(select(ClaimVersion).where(
                ClaimVersion.claim_id.in_(claim_ids), ClaimVersion.change_type == ChangeType.approve)
                .order_by(ClaimVersion.claim_id, ClaimVersion.version, ClaimVersion.id)):
            out[v.claim_id] = v
    return out


def _brief_inputs(request, user, session, view_as):
    """Everything the brief and the walkthrough need, or None when nothing is published yet."""
    from .enums import QuestionStatus
    from .models import Question
    project = project_for(session, request, user)
    handover = get_handover(session, project)
    if handover is None and user.role in REVIEWER_ROLES:
        handover = get_or_create_handover(session, project)
        session.commit()
    if not can_view(user, handover) or (
            user.role not in REVIEWER_ROLES and is_stale(session, project, handover)):
        return None
    role = user.role
    if view_as:
        try:
            role = Role(view_as)
        except ValueError:
            raise HTTPException(status_code=404, detail="Unknown role.") from None
        if role != user.role and user.role not in REVIEWER_ROLES:
            raise HTTPException(status_code=403, detail="Only reviewers can preview another role.")
    sections = build_sections(session, project, user, role)
    shown = {c.id for sec in sections for c in sec.claims}
    open_rows = [q for q in session.scalars(select(Question).where(
        Question.project_id == project.id, Question.status == QuestionStatus.open)
        .order_by(Question.id)) if q.claim_ids and all(i in shown for i in q.claim_ids)]
    from .brief import build_brief
    brief = build_brief(sections, conflict_notes(session, project, shown), open_rows,
                        answered_questions(session, project, shown))
    return project, handover, role, brief


@router.get("/handover/brief")
def takeover_brief(request: Request, user: User = Depends(require_user),
                   session: Session = Depends(get_session), view_as: str = ""):
    data = _brief_inputs(request, user, session, view_as)
    if data is None:
        return render(request, "handover_pending.html", user, project=project_for(session, request, user))
    project, handover, role, brief = data
    return render(request, "brief.html", user, project=project, handover=handover,
                  release=latest_release(session, handover), brief=brief, view_role=role,
                  previewing=role != user.role, sens=effective_sensitivity,
                  hide=lambda text: redact_text(role, text))


ONBOARDING_STEPS = (
    ("Where things stand", "start", "start_here"),
    ("Decisions you inherit", "decisions", "decisions"),
    ("Risks and blockers", "risks", "risks"),
    ("People and ownership", "people", "people"),
    ("Open questions", "questions", "questions"),
    ("Next actions", "actions", "actions"),
)


@router.get("/onboarding")
def onboarding(request: Request, step: int = 1, user: User = Depends(require_user),
               session: Session = Depends(get_session), view_as: str = ""):
    """A guided read of the brief, one topic at a time. Nothing is stored: the step is in the URL."""
    data = _brief_inputs(request, user, session, view_as)
    if data is None:
        return render(request, "handover_pending.html", user, project=project_for(session, request, user))
    project, handover, role, brief = data
    steps = []
    for title, key, attr in ONBOARDING_STEPS:
        items = getattr(brief, attr)
        if key == "start":
            items = [i.claim for i in items]
        if key == "questions":
            items = list(items) + list(brief.unanswered)
        if key == "people":
            items = list(items)
        if items:
            steps.append((title, key, items))
    words = sum(len(redact_text(role, getattr(i, "statement", getattr(i, "text", ""))).split())
                for _, _, items in steps for i in items)
    total = len(steps)
    step = max(1, min(step, total + 1)) if total else 1
    return render(request, "onboarding.html", user, project=project, brief=brief,
                  release=latest_release(session, handover), steps=steps, step=step, total=total,
                  minutes=max(1, round(words / 200)), view_role=role, previewing=role != user.role,
                  hide=lambda text: redact_text(role, text),
                  query=f"&view_as={role.value}" if role != user.role else "")


@router.get("/handover/releases")
def release_history(request: Request, user: User = Depends(require_user),
                    session: Session = Depends(get_session)):
    if user.role not in REVIEWER_ROLES:
        raise HTTPException(status_code=403, detail="Only reviewers can see release history.")
    handover = get_handover(session, project_for(session, request, user))
    from sqlalchemy import func
    rels = releases(session, handover) if handover else []
    counts = dict(session.execute(
        select(Acknowledgement.release_id, func.count()).where(
            Acknowledgement.release_id.in_([r.id for r in rels]))
        .group_by(Acknowledgement.release_id)).all()) if rels else {}
    names: dict[int, list[tuple[str, object]]] = {r.id: [] for r in rels}
    if rels:
        for a, who in session.execute(
                select(Acknowledgement, User.display_name).join(User, User.id == Acknowledgement.user_id)
                .where(Acknowledgement.release_id.in_([r.id for r in rels]))
                .order_by(Acknowledgement.acknowledged_at)):
            names[a.release_id].append((who, a.acknowledged_at))
    rows = [(r, len(r.entries), counts.get(r.id, 0), names[r.id]) for r in rels]
    from .release_diff import release_diff
    changes = release_diff(session, user.role, rels[0], rels[1] if len(rels) > 1 else None,
                           handover.project_id) if rels else None
    return render(request, "releases.html", user, rows=rows, changes=changes,
                  latest=rels[0] if rels else None)


@router.post("/handover/{action}")
def handover_action(action: str, request: Request, csrf: str = Form(""),
                    user: User = Depends(require_user), session: Session = Depends(get_session)):
    check_csrf(request, csrf)
    project = project_for(session, request, user)
    handover = get_handover(session, project)
    if handover is None and user.role in REVIEWER_ROLES:
        handover = get_or_create_handover(session, project)
    if handover is None:
        raise HTTPException(status_code=404, detail="No handover exists yet.")
    try:
        if action == "approve":
            approve_handover(session, handover, user)
            msg = "Handover signed off. People with access can now read it."
        elif action == "withdraw":
            withdraw_handover(session, handover, user)
            msg = "Handover withdrawn. Only reviewers can see it now."
        elif action == "acknowledge":
            msg = ("Thanks. Your acknowledgement is recorded."
                   if acknowledge(session, handover, user) else "Already acknowledged.")
        else:
            raise HTTPException(status_code=404, detail="Unknown action.")
    except HandoverError as exc:
        session.rollback()
        return _flash(request, str(exc), "/handover")
    session.commit()
    return _flash(request, msg, "/handover")


@router.post("/admin/sources/semantic")
def semantic_check(request: Request, csrf: str = Form(""), user: User = Depends(require_admin),
                   session: Session = Depends(get_session)):
    check_csrf(request, csrf)
    from .semantic import judge_from_env, semantic_review
    try:
        with judge_from_env() as judge:
            report = semantic_review(session, project_for(session, request, user), judge)
    except ExtractionError as exc:
        session.rollback()
        return _flash(request, f"Semantic check failed: {exc}", "/admin/sources")
    session.commit()
    msg = (f"Checked {report.checked} claim(s): {report.doubted} doubted, {report.skipped} skipped "
           "(confidential or built straight from a quote). Doubts are advisory; nothing was changed.")
    return _flash(request, msg + "".join(" " + w for w in report.warnings[:2]), "/review")


# ------------------------------------------------------------------ sources (admin)


@router.get("/admin/sources")
def sources_page(request: Request, user: User = Depends(require_admin),
                 session: Session = Depends(get_session)):
    project = project_for(session, request, user)
    import os
    from .models import Job
    recent_jobs = list(session.scalars(select(Job).where(Job.project_id == project.id)
                                       .order_by(Job.id.desc()).limit(5)))
    return render(request, "sources.html", user, project=project, sources=project.sources,
                  jobs=recent_jobs, jobs_active=any(j.status in ("queued", "running") for j in recent_jobs),
                  kinds=[k.value for k in SourceKind], levels=[s.value for s in Sensitivity],
                  llm_ready=all(os.environ.get(n) for n in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")),
                  max_mb=MAX_BYTES // 1_000_000)


@router.post("/admin/sources/upload")
async def upload_source(request: Request, kind: str = Form(""), sensitivity: str = Form("team"),
                        csrf: str = Form(""), file: UploadFile = File(...),
                        user: User = Depends(require_admin),
                        session: Session = Depends(get_session)):
    check_csrf(request, csrf)
    try:
        k, level = SourceKind(kind), Sensitivity(sensitivity)
    except ValueError:
        return _flash(request, "Choose a valid source type and sensitivity.", "/admin/sources")
    data = await file.read(MAX_BYTES + 1)
    name = (file.filename or "upload").replace("\\", "/").split("/")[-1][:200]
    try:
        result = ingest_source(session, project_for(session, request, user), kind=k, name=name,
                               content=decode_upload(data), sensitivity=level,
                               origin=f"upload by {user.username}")
    except IngestError as exc:
        session.rollback()
        return _flash(request, f"Could not read {name}: {exc}", "/admin/sources")
    session.commit()
    if result.duplicate:
        msg = f"{name} was already loaded (identical content). Nothing changed."
    else:
        msg = f"Loaded {name}: {result.chunk_count} passages"
        if result.redacted_chunks:
            msg += f", {result.redacted_chunks} contained a secret that was masked"
        msg += "."
        msg += "".join(" " + w for w in result.warnings[:3])
    return _flash(request, msg, "/admin/sources")


@router.post("/admin/sources/extract")
def extract_claims(request: Request, engine: str = Form("rules"), csrf: str = Form(""),
                   user: User = Depends(require_admin), session: Session = Depends(get_session)):
    check_csrf(request, csrf)
    if engine == "llm":
        # Model calls are slow: run them in the background and let the page show progress.
        from . import jobs
        project = project_for(session, request, user)
        if jobs.active_job(session, project.id, "extract_llm"):
            return _flash(request, "An LLM extraction is already running. Wait for it to finish.",
                          "/admin/sources")
        try:
            with llm_from_env():    # fail now, with a clear message, if the settings are missing
                pass
        except ExtractionError as exc:
            return _flash(request, f"Extraction failed: {exc}", "/admin/sources")
        job = jobs.create_job(session, project, "extract_llm", user.username)
        session.commit()
        jobs.start_thread(sessionmaker(bind=session.get_bind(), expire_on_commit=False), job.id)
        return _flash(request, "LLM extraction started in the background. Status is shown below.",
                      "/admin/sources")
    try:
        if engine not in ("rules", "llm"):
            raise ExtractionError("unknown extraction engine")
        project = project_for(session, request, user)
        if engine == "rules":
            report = run_extraction(session, project, RuleExtractor())
        else:
            with llm_from_env() as extractor:
                report = run_extraction(session, project, extractor)
        detect_conflicts(session, project)
        generate_questions(session, project)
    except ExtractionError as exc:
        session.rollback()
        return _flash(request, f"Extraction failed: {exc}", "/admin/sources")
    session.commit()
    counts = ", ".join(f"{n} {k}" for k, n in sorted(report.confidence_counts.items())) or "none"
    msg = (f"Extracted with {report.extractor}: {report.claims_created} new draft claims "
           f"({counts}), {report.duplicates_skipped} duplicates skipped. "
           "Nothing is approved until a reviewer does it.")
    return _flash(request, msg, "/review")
