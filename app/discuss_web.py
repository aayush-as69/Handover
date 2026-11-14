"""Comments on claims, an inbox of what needs attention, and search."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .access import visible_in_handover, visible_in_review
from .bulk_web import eligible_claims
from .db import get_session
from .enums import REVIEWER_ROLES, ConflictStatus, QuestionStatus, ReviewStatus
from .freshness import decay_report
from .handover import can_view, get_handover, is_stale, latest_release
from .handover_web import require_user
from .models import (Acknowledgement, Claim, ClaimComment, Conflict, OnboardingStep, Question)
from .web import check_csrf, get_reviewable, project_for, render, require_reviewer

router = APIRouter()
MAX_COMMENT = 1000


@router.post("/review/comments/{claim_id}")
def add_comment(claim_id: int, request: Request, body: str = Form(""), csrf: str = Form(""),
                user=Depends(require_reviewer), session: Session = Depends(get_session)):
    check_csrf(request, csrf)
    claim = get_reviewable(session, user, claim_id)
    text = body.strip()
    if not text:
        request.session["flash"] = "Write something before posting."
    elif len(text) > MAX_COMMENT:
        request.session["flash"] = f"Comments can be up to {MAX_COMMENT} characters."
    else:
        session.add(ClaimComment(claim_id=claim.id, author=user.display_name, user_id=user.id, body=text))
        session.commit()
        request.session["flash"] = "Comment added."
    return RedirectResponse(f"/review/claims/{claim.id}", status_code=303)


@router.get("/inbox")
def inbox(request: Request, user=Depends(require_user), session: Session = Depends(get_session)):
    """What needs this person's attention in the current project, by their role there."""
    project = project_for(session, request, user)
    items: list[tuple[str, str, str]] = []        # (what, why it matters, link)
    reviewer = user.role in REVIEWER_ROLES
    if reviewer:
        waiting = session.scalar(select(func.count()).select_from(Claim).where(
            Claim.project_id == project.id,
            Claim.review_status.in_([ReviewStatus.generated, ReviewStatus.edited])))
        if waiting:
            clean = len(eligible_claims(session, user, project))
            items.append((f"{waiting} claim(s) waiting for review",
                          f"{clean} of them are clean and can be approved together." if clean else
                          "None are clean enough for bulk approval.", "/review"))
        conflicts = session.scalar(select(func.count()).select_from(Conflict).where(
            Conflict.project_id == project.id, Conflict.status == ConflictStatus.open))
        if conflicts:
            items.append((f"{conflicts} open conflict(s)", "Sources disagree and need a decision.", "/conflicts"))
        questions = session.scalar(select(func.count()).select_from(Question).where(
            Question.project_id == project.id, Question.status == QuestionStatus.open))
        if questions:
            items.append((f"{questions} unanswered question(s)", "Gaps the outgoing person can still fill.", "/questions"))
        stale = [r for r in decay_report(session, project, user.role) if r.fresh.state == "stale"]
        if stale:
            items.append((f"{len(stale)} claim(s) with possibly stale evidence",
                          "Their newest supporting source is over 90 days old.", "/freshness"))
        handover = get_handover(session, project)
        if handover is not None and is_stale(session, project, handover):
            items.append(("The signed-off handover is out of date",
                          "Something signed off was changed. Sign off again so readers see it.", "/handover"))
    handover = get_handover(session, project)
    release = latest_release(session, handover)
    if release is not None and can_view(user, handover) and not is_stale(session, project, handover):
        acked = session.scalar(select(Acknowledgement.id).where(
            Acknowledgement.release_id == release.id, Acknowledgement.user_id == user.id))
        if acked is None:
            items.append((f"Release {release.number} is waiting for you to acknowledge",
                          "Read the handover, then confirm. Your name and the time are recorded.",
                          "/onboarding"))
        else:
            done = session.scalar(select(func.count()).select_from(OnboardingStep).where(
                OnboardingStep.user_id == user.id, OnboardingStep.project_id == project.id,
                OnboardingStep.release_number == release.number))
            items.append((f"Release {release.number} acknowledged",
                          f"You confirmed {done} topic(s) in the guided read." if done else
                          "You have not used the guided read yet.", "/onboarding"))
    return render(request, "inbox.html", user, project=project, items=items)


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@router.get("/search")
def search(request: Request, q: str = "", user=Depends(require_user),
           session: Session = Depends(get_session)):
    """Find claims (and, for reviewers, questions) in the current project, within the role's reach."""
    project = project_for(session, request, user)
    q = " ".join(q.split())[:100]
    claims: list[Claim] = []
    questions: list[Question] = []
    if len(q) >= 2:
        reviewer = user.role in REVIEWER_ROLES
        handover = get_handover(session, project)
        readable = reviewer or (can_view(user, handover) and not is_stale(session, project, handover))
        if readable:
            rows = session.scalars(select(Claim).where(
                Claim.project_id == project.id, Claim.review_status != ReviewStatus.rejected,
                Claim.statement.ilike(_like(q), escape="\\")).order_by(Claim.id).limit(200))
            ok = visible_in_review if reviewer else visible_in_handover
            claims = [c for c in rows if ok(user.role, c)][:40]
        if reviewer:
            for qu in session.scalars(select(Question).where(
                    Question.project_id == project.id, Question.text.ilike(_like(q), escape="\\"))
                    .limit(50)):
                linked = list(session.scalars(select(Claim).where(Claim.id.in_(qu.claim_ids))))
                if all(visible_in_review(user.role, c) for c in linked):
                    questions.append(qu)
    return render(request, "search.html", user, project=project, q=q, claims=claims,
                  questions=questions, short=0 < len(q) < 2)
