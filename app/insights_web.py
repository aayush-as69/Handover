"""Pages for conflicts and the "Questions Before I Leave" checklist (reviewers only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import visible_in_review
from .conflicts import detect_conflicts, reopen, resolve, visible_members
from .db import get_session
from .enums import ConflictStatus, QuestionStatus
from .models import Claim, Conflict, Question, User
from .questions import answer, dismiss, generate_questions
from .web import check_csrf, project_for, render, require_reviewer

router = APIRouter()


def _back(request: Request, msg: str, to: str):
    request.session["flash"] = msg
    return RedirectResponse(to, status_code=303)


def _claims(session: Session, project) -> dict[int, Claim]:
    return {c.id: c for c in session.scalars(select(Claim).where(Claim.project_id == project.id))}


# ------------------------------------------------------------------ conflicts


@router.get("/conflicts")
def conflicts_page(request: Request, user: User = Depends(require_reviewer),
                   session: Session = Depends(get_session)):
    project = project_for(session)
    claims = _claims(session, project)
    rows = []
    for cf in session.scalars(select(Conflict).where(Conflict.project_id == project.id)
                              .order_by(Conflict.id)):
        members = visible_members(user.role, cf, claims)
        if members and cf.status != ConflictStatus.stale:
            rows.append((cf, members))
    rows.sort(key=lambda r: r[0].status != ConflictStatus.open)
    return render(request, "conflicts.html", user, rows=rows)


@router.post("/conflicts/detect")
def conflicts_detect(request: Request, csrf: str = Form(""), user: User = Depends(require_reviewer),
                     session: Session = Depends(get_session)):
    check_csrf(request, csrf)
    project = project_for(session)
    detect_conflicts(session, project)
    generate_questions(session, project)
    session.commit()
    return _back(request, "Checked the sources for disagreements.", "/conflicts")


@router.post("/conflicts/{conflict_id}/{action}")
def conflict_action(conflict_id: int, action: str, request: Request, csrf: str = Form(""),
                    note: str = Form(""), user: User = Depends(require_reviewer),
                    session: Session = Depends(get_session)):
    check_csrf(request, csrf)
    project = project_for(session)
    cf = session.get(Conflict, conflict_id)
    if cf is None or cf.project_id != project.id or not visible_members(
            user.role, cf, _claims(session, project)):
        raise HTTPException(status_code=404, detail="Conflict not found.")
    if action == "resolve":
        try:
            resolve(cf, user.display_name, note[:1000])
        except ValueError as exc:
            return _back(request, str(exc), "/conflicts")
        msg = "Marked as resolved. Edit or reject the claims that are wrong."
    elif action == "reopen":
        reopen(cf)
        msg = "Reopened."
    else:
        raise HTTPException(status_code=404, detail="Unknown action.")
    generate_questions(session, project)
    session.commit()
    return _back(request, msg, "/conflicts")


# ------------------------------------------------------------------ questions


@router.get("/questions")
def questions_page(request: Request, user: User = Depends(require_reviewer),
                   session: Session = Depends(get_session)):
    project = project_for(session)
    claims = _claims(session, project)
    items = []
    for q in session.scalars(select(Question).where(Question.project_id == project.id)
                             .order_by(Question.id)):
        linked = [claims[i] for i in q.claim_ids if i in claims]
        # Every linked claim must be within the reviewer's clearance, else it is hidden.
        if linked and all(visible_in_review(user.role, c) for c in linked) and q.status != QuestionStatus.closed:
            items.append((q, linked))
    items.sort(key=lambda r: (r[0].status != QuestionStatus.open, r[0].id))
    open_n = sum(1 for q, _ in items if q.status == QuestionStatus.open)
    return render(request, "questions.html", user, items=items, open_n=open_n, total=len(items))


@router.post("/questions/refresh")
def questions_refresh(request: Request, csrf: str = Form(""), user: User = Depends(require_reviewer),
                      session: Session = Depends(get_session)):
    check_csrf(request, csrf)
    project = project_for(session)
    detect_conflicts(session, project)
    generate_questions(session, project)
    session.commit()
    return _back(request, "Questions refreshed.", "/questions")


@router.post("/questions/{question_id}/{action}")
def question_action(question_id: int, action: str, request: Request, csrf: str = Form(""),
                    text: str = Form(""), user: User = Depends(require_reviewer),
                    session: Session = Depends(get_session)):
    check_csrf(request, csrf)
    project = project_for(session)
    q = session.get(Question, question_id)
    claims = _claims(session, project)
    linked = [claims[i] for i in (q.claim_ids if q else []) if i in claims]
    if q is None or q.project_id != project.id or not linked or not all(
            visible_in_review(user.role, c) for c in linked):
        raise HTTPException(status_code=404, detail="Question not found.")
    if action == "answer":
        try:
            answer(q, user.display_name, text)
        except ValueError as exc:
            return _back(request, str(exc), "/questions")
        msg = "Answer saved. It will appear in the handover as the leaver's own words."
    elif action == "dismiss":
        dismiss(q, user.display_name)
        msg = "Dismissed."
    elif action == "reopen":
        q.status, q.answer = QuestionStatus.open, None
        msg = "Question reopened."
    else:
        raise HTTPException(status_code=404, detail="Unknown action.")
    session.commit()
    return _back(request, msg, "/questions")
