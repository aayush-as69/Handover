"""Evidence freshness: how old is the newest passage that supports a claim?

A claim can be quoted word for word and still be out of date. This module measures one
thing only: the age of the newest dated supporting passage. It does not say the claim is
wrong. Thresholds are fixed and shown to the reader: fresh up to 30 days, ageing up to 90,
stale beyond that, undated when no supporting passage carries a date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import visible_in_review
from .enums import ClaimType, ReviewStatus, Role, Stance
from .models import Claim

FRESH_DAYS = 30
AGEING_DAYS = 90
IMPORTANT_TYPES = (ClaimType.decision, ClaimType.dependency, ClaimType.owner,
                   ClaimType.risk, ClaimType.blocker)


@dataclass
class Freshness:
    state: str                      # fresh | ageing | stale | undated
    newest: datetime | None
    age_days: int | None
    supporting: int
    contradicting: int
    sources: int                    # distinct sources behind the supporting quotes
    kinds: list[str]

    @property
    def label(self) -> str:
        return {"fresh": "Recent evidence", "ageing": "Ageing evidence",
                "stale": "Possibly stale", "undated": "No dated evidence"}[self.state]


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def claim_freshness(claim: Claim, now: datetime | None = None) -> Freshness:
    now = _naive(now or datetime.now(timezone.utc))
    sup = [e for e in claim.evidence if e.stance == Stance.supports and e.chunk is not None]
    con = [e for e in claim.evidence if e.stance == Stance.contradicts]
    dates = [_naive(e.chunk.occurred_at) for e in sup if e.chunk.occurred_at]
    newest = max(dates) if dates else None
    age = max((now - newest).days, 0) if newest else None
    state = ("undated" if age is None else "fresh" if age <= FRESH_DAYS
             else "ageing" if age <= AGEING_DAYS else "stale")
    srcs = {e.chunk.source_id: e.chunk.source.kind.value for e in sup if e.chunk.source is not None}
    return Freshness(state, newest, age, len(sup), len(con), len(srcs), sorted(set(srcs.values())))


@dataclass
class DecayRow:
    claim: Claim
    fresh: Freshness
    important: bool


def decay_report(session: Session, project, role: Role,
                 now: datetime | None = None) -> list[DecayRow]:
    """Claims needing a second look, oldest evidence first. Only what the role may read."""
    rows = []
    for c in session.scalars(select(Claim).where(
            Claim.project_id == project.id, Claim.review_status != ReviewStatus.rejected)
            .order_by(Claim.id)):
        if not visible_in_review(role, c):
            continue
        f = claim_freshness(c, now)
        if f.state in ("stale", "ageing", "undated"):
            rows.append(DecayRow(c, f, c.type in IMPORTANT_TYPES))
    order = {"stale": 0, "undated": 1, "ageing": 2}
    rows.sort(key=lambda r: (order[r.fresh.state], not r.important, -(r.fresh.age_days or 0)))
    return rows
