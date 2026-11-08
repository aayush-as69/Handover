"""Server-rendered pages: login and the review screen.

Every page re-checks the signed-in user's role and clearance through app.access. Nothing
here decides visibility on its own.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import chunk_visible, effective_sensitivity, filter_review, visible_in_review
from .db import get_session
from .enums import ChangeType, Confidence, ReviewStatus, Role
from .models import Chunk, Claim, Project, User
from .security import LoginThrottle, csrf_ok, new_csrf_token, verify_password
from .verify import verify_claim

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
throttle = LoginThrottle()

MAX_STATEMENT = 1000
MAX_NOTE = 1000
REVIEW_ROLES = (Role.admin, Role.approver)


# ------------------------------------------------------------------ helpers


def current_user(request: Request, session: Session = Depends(get_session)) -> Optional[User]:
    uid = request.session.get("uid")
    return session.get(User, uid) if uid else None


def require_reviewer(request: Request, user: Optional[User] = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    if user.role not in REVIEW_ROLES:
        raise HTTPException(status_code=403, detail="Only approvers and admins can review claims.")
    return user


def csrf_token(request: Request) -> str:
    if "csrf" not in request.session:
        request.session["csrf"] = new_csrf_token()
    return request.session["csrf"]


def check_csrf(request: Request, token: str | None) -> None:
    if not csrf_ok(request.session.get("csrf"), token):
        raise HTTPException(status_code=403, detail="Invalid or missing form token.")


def render(request: Request, name: str, user: Optional[User] = None, status_code: int = 200, **ctx):
    ctx.update(user=user, csrf=csrf_token(request), flash=request.session.pop("flash", None))
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def word_diff(old: str, new: str) -> list[tuple[str, str]]:
    a, b = old.split(), new.split()
    out: list[tuple[str, str]] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(("same", " ".join(a[i1:i2])))
        else:
            if i2 > i1:
                out.append(("del", " ".join(a[i1:i2])))
            if j2 > j1:
                out.append(("ins", " ".join(b[j1:j2])))
    return out


def project_for(session: Session) -> Project:
    project = session.scalar(select(Project).order_by(Project.id))
    if project is None:
        raise HTTPException(status_code=404, detail="No project has been loaded yet.")
    return project


def get_reviewable(session: Session, user: User, claim_id: int) -> Claim:
    claim = session.get(Claim, claim_id)
    # Same answer whether it is missing or above clearance: do not reveal that it exists.
    if claim is None or not visible_in_review(user.role, claim):
        raise HTTPException(status_code=404, detail="Claim not found.")
    return claim


# ------------------------------------------------------------------ login


@router.get("/")
def home(user: Optional[User] = Depends(current_user)):
    return RedirectResponse("/review" if user else "/login", status_code=303)


@router.get("/login")
def login_form(request: Request, user: Optional[User] = Depends(current_user)):
    return render(request, "login.html", user)


@router.post("/login")
def login(request: Request, username: str = Form(""), password: str = Form(""),
          csrf: str = Form(""), session: Session = Depends(get_session)):
    check_csrf(request, csrf)
    key = username.strip().lower()[:64]
    if throttle.blocked(key):
        return render(request, "login.html", None, 429,
                      error="Too many failed attempts. Try again in a few minutes.")
    user = session.scalar(select(User).where(User.username == key))
    # Verify even when the user is unknown, so timing does not reveal which names exist.
    ok = verify_password(password, user.password_hash if user else "pbkdf2$1$00$00")
    if not (user and ok):
        throttle.fail(key)
        return render(request, "login.html", None, 401, error="Wrong username or password.")
    throttle.reset(key)
    request.session.clear()                      # new session on login
    request.session["uid"] = user.id
    return RedirectResponse("/review" if user.role in REVIEW_ROLES else "/", status_code=303)


@router.post("/logout")
def logout(request: Request, csrf: str = Form("")):
    check_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ------------------------------------------------------------------ review queue


@router.get("/review")
def review_queue(request: Request, status: str = "open", confidence: str = "",
                 user: User = Depends(require_reviewer), session: Session = Depends(get_session)):
    project = project_for(session)
    claims = filter_review(user.role, session.scalars(
        select(Claim).where(Claim.project_id == project.id).order_by(Claim.id)).all())
    totals = {s.value: 0 for s in ReviewStatus}
    for c in claims:
        totals[c.review_status.value] += 1
    if status == "open":
        shown = [c for c in claims if c.review_status in (ReviewStatus.generated, ReviewStatus.edited)]
    elif status in totals:
        shown = [c for c in claims if c.review_status.value == status]
    else:
        status, shown = "all", claims
    if confidence in {c.value for c in Confidence}:
        shown = [c for c in shown if c.confidence.value == confidence]
    else:
        confidence = ""
    # Riskiest first: conflicting, unsupported, inferred, verified
    order = {Confidence.conflicting: 0, Confidence.unsupported: 1, Confidence.inferred: 2,
             Confidence.verified: 3}
    shown.sort(key=lambda c: (order[c.confidence], c.id))
    return render(request, "queue.html", user, project=project, claims=shown, totals=totals,
                  status=status, confidence=confidence, sens=effective_sensitivity,
                  hidden=len(session.scalars(select(Claim).where(Claim.project_id == project.id)).all())
                  - len(claims))


@router.get("/review/claims/{claim_id}")
def claim_detail(claim_id: int, request: Request, user: User = Depends(require_reviewer),
                 session: Session = Depends(get_session)):
    claim = get_reviewable(session, user, claim_id)
    evidence = [(e, chunk_visible(user.role, e.chunk)) for e in claim.evidence]
    history = []
    prev = None
    for v in claim.versions:
        history.append((v, word_diff(prev, v.statement) if prev is not None and prev != v.statement else None))
        prev = v.statement
    return render(request, "claim.html", user, claim=claim, evidence=evidence,
                  history=list(reversed(history)), sensitivity=effective_sensitivity(claim),
                  max_statement=MAX_STATEMENT)


@router.post("/review/claims/{claim_id}/{action}")
def claim_action(claim_id: int, action: str, request: Request, csrf: str = Form(""),
                 note: str = Form(""), statement: str = Form(""),
                 user: User = Depends(require_reviewer), session: Session = Depends(get_session)):
    check_csrf(request, csrf)
    claim = get_reviewable(session, user, claim_id)
    note = note.strip()[:MAX_NOTE] or None
    who = user.display_name

    def back(msg: str):
        request.session["flash"] = msg
        return RedirectResponse(f"/review/claims/{claim.id}", status_code=303)

    if action == "approve":
        if claim.review_status == ReviewStatus.approved:
            return back("Already approved.")
        if claim.confidence != Confidence.verified and not note:
            return back("This claim is not fully verified. Add a note saying why you accept it.")
        claim.approve(who, note)
        msg = "Approved."
    elif action == "reject":
        if claim.review_status == ReviewStatus.rejected:
            return back("Already rejected.")
        claim.reject(who, note)
        msg = "Rejected. It will not appear in any handover."
    elif action == "reopen":
        if claim.review_status not in (ReviewStatus.approved, ReviewStatus.rejected):
            return back("Only approved or rejected claims can be reopened.")
        claim.reopen(who, note)
        msg = "Sent back to the review queue."
    elif action == "edit":
        text = " ".join(statement.split())
        if not text:
            return back("The statement cannot be empty.")
        if len(text) > MAX_STATEMENT:
            return back(f"The statement is too long (max {MAX_STATEMENT} characters).")
        if text == claim.statement:
            return back("Nothing changed.")
        claim.edit(text, who, note)
        session.flush()
        verify_claim(claim)             # the edit may no longer match its evidence
        msg = "Saved. The edited claim must be approved again, and its confidence was re-checked."
    else:
        raise HTTPException(status_code=404, detail="Unknown action.")
    session.commit()
    return back(msg)


# ------------------------------------------------------------------ source text


@router.get("/review/chunks/{chunk_id}")
def source_text(chunk_id: int, request: Request, user: User = Depends(require_reviewer),
                session: Session = Depends(get_session), snippet: str = ""):
    chunk = session.get(Chunk, chunk_id)
    if chunk is None or not chunk_visible(user.role, chunk):
        raise HTTPException(status_code=404, detail="Source not found.")
    text, i = chunk.text, chunk.text.find(snippet) if snippet else -1
    parts = (text[:i], text[i:i + len(snippet)], text[i + len(snippet):]) if i >= 0 else (text, "", "")
    return render(request, "chunk.html", user, chunk=chunk, parts=parts)
