"""Pages for the handover itself and for loading sources (admin)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

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
from .models import Acknowledgement, Source, User
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
    project = project_for(session)
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
            raise HTTPException(status_code=404, detail="Unknown role.")
        if role != user.role and user.role not in REVIEWER_ROLES:
            raise HTTPException(status_code=403, detail="Only reviewers can preview another role.")
    sections = build_sections(session, project, user, role)
    shown = {c.id for sec in sections for c in sec.claims}
    hide = lambda text: redact_text(role, text)
    rel = latest_release(session, handover)
    state = release_state(session, project, handover)
    acks = session.scalars(select(Acknowledgement).where(
        Acknowledgement.release_id == rel.id)).all() if rel else []
    ack_users = {a.user_id: session.get(User, a.user_id) for a in acks}
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
        approvals={c.id: next((v for v in reversed(c.versions)
                               if v.change_type == ChangeType.approve), None)
                   for s in sections for c in s.claims},
    )


@router.get("/handover/releases")
def release_history(request: Request, user: User = Depends(require_user),
                    session: Session = Depends(get_session)):
    if user.role not in REVIEWER_ROLES:
        raise HTTPException(status_code=403, detail="Only reviewers can see release history.")
    handover = get_handover(session, project_for(session))
    rows = []
    for r in (releases(session, handover) if handover else []):
        n_acks = len(session.scalars(select(Acknowledgement.id).where(
            Acknowledgement.release_id == r.id)).all())
        rows.append((r, len(r.entries), n_acks))
    return render(request, "releases.html", user, rows=rows)


@router.post("/handover/{action}")
def handover_action(action: str, request: Request, csrf: str = Form(""),
                    user: User = Depends(require_user), session: Session = Depends(get_session)):
    check_csrf(request, csrf)
    project = project_for(session)
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
        report = semantic_review(session, project_for(session), judge_from_env())
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
    project = project_for(session)
    import os
    return render(request, "sources.html", user, project=project, sources=project.sources,
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
        result = ingest_source(session, project_for(session), kind=k, name=name,
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
    try:
        if engine not in ("rules", "llm"):
            raise ExtractionError("unknown extraction engine")
        extractor = RuleExtractor() if engine == "rules" else llm_from_env()
        project = project_for(session)
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
