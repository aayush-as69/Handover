"""Server-rendered pages: login and the review screen.

Every page re-checks the signed-in user's role and clearance through app.access. Nothing
here decides visibility on its own.
"""

from __future__ import annotations

import difflib
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from .access import (chunk_visible, clearance_rank, effective_rank_sql, effective_sensitivity,
                     sensitivity_from_rank, visible_in_review)
from .db import get_session
from .enums import REVIEWER_ROLES, Confidence, ReviewStatus
from .models import Chunk, Claim, Project, User
from .projects import can_access_project
from .security import (clear_login_failures_for, client_ip, csrf_ok, login_allowed, new_csrf_token,
                       record_login_failure_for, verify_password, DUMMY_HASH)
from .verify import verify_claim

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@lru_cache(maxsize=None)
def asset_url(name: str) -> str:
    """Static file URL stamped with a hash of its contents, so browsers can cache it for a long
    time yet fetch the new file the moment it changes."""
    import hashlib
    data = (Path(__file__).parent / "static" / name).read_bytes()
    return f"/static/{name}?v={hashlib.sha256(data).hexdigest()[:10]}"


templates.env.globals["asset_url"] = asset_url
CONFIDENCE_LABELS = {"verified": "quote-verified", "inferred": "inferred",
                     "conflicting": "conflicting", "unsupported": "unsupported"}
templates.env.globals["conf_label"] = lambda c: CONFIDENCE_LABELS[getattr(c, "value", c)]

MAX_STATEMENT = 1000
MAX_NOTE = 1000
REVIEW_ROLES = REVIEWER_ROLES


# ------------------------------------------------------------------ helpers


def current_user(request: Request, session: Session = Depends(get_session)) -> Optional[User]:
    uid = request.session.get("uid")
    if not uid:
        return None
    user = session.get(User, uid)
    # Cookies issued before session-version support (or before a password reset) are stale.
    if user is None or request.session.get("session_version") != user.session_version:
        request.session.clear()
        return None
    return user


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


def project_for(session: Session, request: Request, user: User) -> Project:
    """The project this person is working in: their chosen one if they may use it, else the
    first they may use. Never a project they have no access to."""
    from .projects import resolve_project
    wanted = request.session.get("project_id")
    project = resolve_project(session, user, wanted if isinstance(wanted, int) else None)
    if project is None:
        raise HTTPException(status_code=404, detail="You have not been added to a project yet.")
    request.session["project_id"] = project.id
    return project


def _flash_stale(request: Request) -> None:
    request.session["flash"] = ("Someone else changed this claim at the same moment, so your change "
                                "was not saved. Review the latest version and try again.")


def get_reviewable(session: Session, user: User, claim_id: int) -> Claim:
    claim = session.get(Claim, claim_id)
    # Same answer whether it is missing or above clearance: do not reveal that it exists.
    if claim is None or not visible_in_review(user.role, claim) or not can_access_project(
            session, user, claim.project_id):
        raise HTTPException(status_code=404, detail="Claim not found.")
    return claim


# ------------------------------------------------------------------ login


def landing(user: Optional[User]) -> str:
    if user is None:
        return "/login"
    return "/review" if user.role in REVIEW_ROLES else "/handover"


@router.get("/")
def home(request: Request, user: Optional[User] = Depends(current_user)):
    if user is None:
        return render(request, "landing.html", None)
    return RedirectResponse(landing(user), status_code=303)


def render_login(request: Request, user: Optional[User] = None,
                status_code: int = 200, **ctx):
    cfg = request.app.state.cfg
    demo_password = cfg.demo_password if cfg.demo_mode and cfg.demo_password else ""
    return render(request, "login.html", user, status_code,
                  demo_password=demo_password, **ctx)


@router.get("/login")
def login_form(request: Request, user: Optional[User] = Depends(current_user)):
    return render_login(request, user)


@router.post("/login")
def login(request: Request, username: str = Form(""), password: str = Form(""),
          csrf: str = Form(""), session: Session = Depends(get_session)):
    check_csrf(request, csrf)
    key = username.strip().lower()[:64]
    cfg = request.app.state.cfg
    ip = client_ip(request, cfg.trust_proxy, cfg.edge_shared_secret)
    if not login_allowed(session, key, ip):
        return render_login(request, None, 429,
                            error="Too many failed attempts. Try again in a few minutes.")
    user = session.scalar(select(User).where(User.username == key))
    # Verify even when the user is unknown, so timing does not reveal which names exist.
    ok = verify_password(password, user.password_hash if user else DUMMY_HASH)
    if not (user and ok):
        record_login_failure_for(session, key, ip)
        return render_login(request, None, 401, error="Wrong username or password.")
    clear_login_failures_for(session, key, ip)    # the address keeps its volume count; it decays
    request.session.clear()                      # new session on login
    request.session["uid"] = user.id
    request.session["session_version"] = user.session_version
    return RedirectResponse(landing(user), status_code=303)


@router.post("/logout")
def logout(request: Request, csrf: str = Form("")):
    check_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ------------------------------------------------------------------ review queue


QUEUE_PAGE = 50


@router.get("/review")
def review_queue(request: Request, status: str = "open", confidence: str = "", page: int = 1,
                 user: User = Depends(require_reviewer), session: Session = Depends(get_session)):
    """Filtering by clearance, status and confidence, counting, ordering and paging all happen in
    the database; only the page being shown is loaded."""
    project = project_for(session, request, user)
    rank = effective_rank_sql().label("rank")
    clearance = clearance_rank(user.role)
    base = select(Claim.id, Claim.review_status, rank).where(Claim.project_id == project.id).subquery()
    visible = select(base.c.id, base.c.review_status).where(base.c.rank <= clearance).subquery()

    totals = {s.value: 0 for s in ReviewStatus}
    for st, n in session.execute(select(visible.c.review_status, func.count()).group_by(visible.c.review_status)):
        totals[st.value] = n
    hidden = session.scalar(select(func.count()).select_from(base).where(base.c.rank > clearance)) or 0

    query = select(Claim, rank).where(Claim.project_id == project.id)
    query = query.where(rank <= clearance)
    if status == "open":
        query = query.where(Claim.review_status.in_([ReviewStatus.generated, ReviewStatus.edited]))
    elif status in totals:
        query = query.where(Claim.review_status == ReviewStatus(status))
    else:
        status = "all"
    if confidence in {c.value for c in Confidence}:
        query = query.where(Claim.confidence == Confidence(confidence))
    else:
        confidence = ""
    matching = session.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    # Riskiest first: conflicting, unsupported, inferred, verified
    risk = case((Claim.confidence == Confidence.conflicting, 0),
                (Claim.confidence == Confidence.unsupported, 1),
                (Claim.confidence == Confidence.inferred, 2), else_=3)
    pages = max(1, -(-matching // QUEUE_PAGE))
    page = min(max(page, 1), pages)
    rows = session.execute(query.order_by(risk, Claim.id).limit(QUEUE_PAGE)
                           .offset((page - 1) * QUEUE_PAGE)).all()
    level = {c.id: sensitivity_from_rank(r) for c, r in rows}
    return render(request, "queue.html", user, project=project, claims=[c for c, _ in rows],
                  totals=totals, status=status, confidence=confidence, sens=lambda c: level[c.id],
                  hidden=hidden, page=page, pages=pages, matching=matching)


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
    from .conflicts import visible_members
    from .enums import ConflictStatus
    from .models import Conflict
    # Conflicts are few; read them, keep those naming this claim, and load only their members.
    mine = [cf for cf in session.scalars(select(Conflict).where(
        Conflict.project_id == claim.project_id, Conflict.status != ConflictStatus.stale))
        if claim.id in cf.claim_ids]
    wanted = {i for cf in mine for i in cf.claim_ids}
    members = {c.id: c for c in session.scalars(select(Claim).where(
        Claim.project_id == claim.project_id, Claim.id.in_(wanted)))} if wanted else {}
    disputes = []
    for cf in mine:
        others = [m for m in visible_members(user.role, cf, members) if m.id != claim.id]
        if others:
            disputes.append((cf, others))
    from .connections import claim_connections
    from .freshness import claim_freshness
    return render(request, "claim.html", user, claim=claim, evidence=evidence, disputes=disputes,
                  connections=claim_connections(session, user, claim), freshness=claim_freshness(claim),
                  history=list(reversed(history)), sensitivity=effective_sensitivity(claim),
                  max_statement=MAX_STATEMENT)


@router.post("/review/claims/{claim_id}/{action}")
def claim_action(claim_id: int, action: str, request: Request, csrf: str = Form(""),
                 note: str = Form(""), statement: str = Form(""), version: str = Form(""),
                 user: User = Depends(require_reviewer), session: Session = Depends(get_session)):
    check_csrf(request, csrf)
    claim = get_reviewable(session, user, claim_id)
    note = note.strip()[:MAX_NOTE] or None
    who = user.display_name

    if version.strip() != str(claim.version):
        request.session["flash"] = ("This claim was changed by someone else while you were looking at "
                                    "it. Review the latest version and try again.")
        return RedirectResponse(f"/review/claims/{claim.id}", status_code=303)

    def back(msg: str):
        request.session["flash"] = msg
        return RedirectResponse(f"/review/claims/{claim.id}", status_code=303)

    if action == "approve":
        if claim.review_status == ReviewStatus.approved:
            return back("Already approved.")
        from .semantic import has_doubt
        if (claim.confidence != Confidence.verified or has_doubt(claim)) and not note:
            return back("This claim is not fully verified, or a model doubted it. Add a note saying why you accept it.")
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
    try:
        session.commit()
    except StaleDataError:
        session.rollback()
        _flash_stale(request)
        return RedirectResponse(f"/review/claims/{claim.id}", status_code=303)
    return back(msg)


# ------------------------------------------------------------------ source text


@router.get("/review/chunks/{chunk_id}")
def source_text(chunk_id: int, request: Request, user: User = Depends(require_reviewer),
                session: Session = Depends(get_session), snippet: str = ""):
    chunk = session.get(Chunk, chunk_id)
    if chunk is None or not chunk_visible(user.role, chunk) or not can_access_project(
            session, user, chunk.source.project_id):
        raise HTTPException(status_code=404, detail="Source not found.")
    text, i = chunk.text, chunk.text.find(snippet) if snippet else -1
    parts = (text[:i], text[i:i + len(snippet)], text[i + len(snippet):]) if i >= 0 else (text, "", "")
    return render(request, "chunk.html", user, chunk=chunk, parts=parts)
