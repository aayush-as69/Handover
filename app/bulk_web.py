"""Bulk review: approve many clean claims in one step, still as an explicit human action.

Only claims that are quote-verified, have no model doubt and no open conflict are offered. The
reviewer ticks the ones they accept (nothing is pre-ticked by the server). On submit each
claim is checked again, so a claim that changed or became disputed in the meantime is skipped.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import chunk_visible, visible_in_review
from .db import get_session
from .enums import ConflictStatus, Confidence, ReviewStatus
from .models import Claim, Conflict, User
from .semantic import has_doubt
from .web import check_csrf, project_for, render, require_reviewer

router = APIRouter()
BULK_NOTE = "Bulk approved: quote-verified, no conflict."
MAX_BULK = 100


def eligible_claims(session: Session, user: User, project) -> list[Claim]:
    disputed: set[int] = set()
    for cf in session.scalars(select(Conflict).where(
            Conflict.project_id == project.id, Conflict.status == ConflictStatus.open)):
        disputed.update(cf.claim_ids)
    out = []
    for c in session.scalars(select(Claim).where(
            Claim.project_id == project.id,
            Claim.review_status.in_([ReviewStatus.generated, ReviewStatus.edited]),
            Claim.confidence == Confidence.verified).order_by(Claim.id)):
        if c.id in disputed or has_doubt(c) or not visible_in_review(user.role, c):
            continue
        out.append(c)
    return out


@router.get("/review/bulk")
def bulk_page(request: Request, user: User = Depends(require_reviewer),
              session: Session = Depends(get_session)):
    project = project_for(session, request, user)
    claims = eligible_claims(session, user, project)[:MAX_BULK]
    cites = {}
    for c in claims:
        for e in c.evidence:
            if e.chunk is not None and chunk_visible(user.role, e.chunk):
                cites[c.id] = f"{e.chunk.source.name} · {e.chunk.locator}"
                break
    return render(request, "bulk.html", user, project=project, claims=claims, cites=cites,
                  limit=MAX_BULK)


@router.post("/review/bulk")
async def bulk_approve(request: Request, csrf: str = Form(""),
                       user: User = Depends(require_reviewer),
                       session: Session = Depends(get_session)):
    check_csrf(request, csrf)
    form = await request.form()
    try:
        wanted = {int(v) for v in form.getlist("claim_id")}
    except ValueError:
        raise HTTPException(status_code=400, detail="Bad selection.") from None
    if len(wanted) > MAX_BULK:
        raise HTTPException(status_code=400, detail=f"Select at most {MAX_BULK} claims at a time.")
    project = project_for(session, request, user)
    ok = {c.id: c for c in eligible_claims(session, user, project)}
    done = 0
    for cid in wanted:
        claim = ok.get(cid)
        if claim is None:
            continue
        claim.approve(user.display_name, BULK_NOTE)
        done += 1
    session.commit()
    skipped = len(wanted) - done
    request.session["flash"] = (f"Approved {done} claim(s)."
                                + (f" Skipped {skipped} that were no longer eligible." if skipped else ""))
    return RedirectResponse("/review/bulk", status_code=303)
