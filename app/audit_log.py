"""One readable trail of who did what in a project.

It is assembled from records that already exist and cannot be rewritten (claim versions,
verification events, release sign-offs, acknowledgements) plus the resolution and answer
stamps on conflicts and questions. Claim events are only shown for claims the reader's
role may open, so the trail never leaks what the review queue hides.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import clearance_rank, effective_rank_sql, role_can_see
from .enums import Role
from .models import (Acknowledgement, AuditEvent, Claim, ClaimVersion, Conflict, Handover,
                     HandoverRelease, Question, Source, User, ClaimComment)

KINDS = ("claim", "release", "acknowledgement", "conflict", "question", "source")


@dataclass
class Entry:
    at: datetime
    kind: str
    actor: str
    action: str
    detail: str = ""
    claim_id: int | None = None
    link: str = ""          # where to see the thing this entry is about


_ACTIONS = {"generated": "drafted", "edit": "edited", "approve": "approved",
            "reject": "rejected", "reopen": "reopened"}


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def filter_entries(entries: list[Entry], actor: str = "", text: str = "",
                   start: datetime | None = None, end: datetime | None = None) -> list[Entry]:
    """Narrow a trail by person, free text and date range (inclusive of the end day)."""
    actor, text = actor.strip().lower(), text.strip().lower()
    keep = []
    for e in entries:
        if actor and actor not in e.actor.lower():
            continue
        if text and text not in f"{e.action} {e.detail}".lower():
            continue
        when = _naive(e.at)
        if start and when < start:
            continue
        if end and when >= end + timedelta(days=1):
            continue
        keep.append(e)
    return keep


def audit_entries(session: Session, project, role: Role, kind: str = "",
                  limit: int = 300) -> list[Entry]:
    out: list[Entry] = []
    want = lambda k: not kind or kind == k

    if want("claim"):
        rank = effective_rank_sql()
        visible = {i for (i,) in session.execute(
            select(Claim.id).where(Claim.project_id == project.id, rank <= clearance_rank(role)))}
        if visible:
            for v in session.scalars(select(ClaimVersion).where(ClaimVersion.claim_id.in_(visible))):
                out.append(Entry(v.created_at, "claim", v.changed_by,
                                 f"{_ACTIONS.get(v.change_type.value, v.change_type.value)} claim {v.claim_id} (v{v.version})",
                                 (v.note or ""), v.claim_id))
            for cm in session.scalars(select(ClaimComment).where(ClaimComment.claim_id.in_(visible))):
                out.append(Entry(cm.created_at, "claim", cm.author, f"commented on claim {cm.claim_id}",
                                 cm.body[:200], cm.claim_id))
            for e in session.scalars(select(AuditEvent).where(AuditEvent.claim_id.in_(visible))):
                try:
                    detail = json.loads(e.detail)
                    detail = ", ".join(f"{k}: {detail[k]}" for k in list(detail)[:3]) if isinstance(detail, dict) else str(detail)
                except ValueError:
                    detail = ""
                out.append(Entry(e.at, "claim", e.actor, f"{e.action.replace('_', ' ')} on claim {e.claim_id}",
                                 detail[:200], e.claim_id))

    if want("release") or want("acknowledgement"):
        handover = session.scalar(select(Handover).where(Handover.project_id == project.id))
        rels = list(session.scalars(select(HandoverRelease).where(
            HandoverRelease.handover_id == handover.id))) if handover else []
        if want("release"):
            for r in rels:
                out.append(Entry(r.approved_at, "release", r.approved_by_name,
                                 f"signed off release {r.number}", f"{len(r.entries)} claims",
                                 link="/handover/releases"))
        if want("acknowledgement") and rels:
            numbers = {r.id: r.number for r in rels}
            for a, name in session.execute(
                    select(Acknowledgement, User.display_name).join(User, User.id == Acknowledgement.user_id)
                    .where(Acknowledgement.release_id.in_(list(numbers)))):
                out.append(Entry(a.acknowledged_at, "acknowledgement", name,
                                 f"acknowledged release {numbers[a.release_id]}", link="/handover/releases"))

    if want("conflict"):
        for c in session.scalars(select(Conflict).where(Conflict.project_id == project.id,
                                                        Conflict.resolved_at.is_not(None))):
            out.append(Entry(c.resolved_at, "conflict", c.resolved_by or "unknown",
                             f"marked the “{c.topic}” conflict {c.status.value}", c.resolution or "",
                             link="/conflicts"))

    if want("question"):
        for q in session.scalars(select(Question).where(Question.project_id == project.id,
                                                        Question.answered_at.is_not(None))):
            out.append(Entry(q.answered_at, "question", q.answered_by or "unknown",
                             f"{q.status.value} a question", q.text[:160], link="/questions"))

    if want("source"):
        for s in session.scalars(select(Source).where(Source.project_id == project.id)):
            if role_can_see(role, s.sensitivity):
                out.append(Entry(s.ingested_at, "source", s.origin, f"loaded source {s.name}",
                                 f"{s.kind.value}, {s.sensitivity.value}", link="/admin/sources"))

    out.sort(key=lambda e: _naive(e.at), reverse=True)
    return out[:limit]
