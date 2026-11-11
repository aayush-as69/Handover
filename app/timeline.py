"""Decision timeline and bus-factor view, both built from claims and their evidence.

Timeline: dated items (decisions, blockers, open questions, risks, next actions), newest
last, each linked to its claim. Readers see only approved claims their role may see; a
reviewer can also include drafts, which are marked as not yet approved.

Bus factor: for each person named as the author of source passages, the claims that rest
ONLY on that person's passages. If they leave, those are the claims nobody else's records
back up. Claims with no named author (notes, task sheets) are counted, not guessed at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import effective_sensitivity, role_can_see, visible_in_handover
from .enums import REVIEWER_ROLES, ClaimType, ReviewStatus, Role
from .models import Claim

TIMELINE_TYPES = (ClaimType.decision, ClaimType.blocker, ClaimType.open_question,
                  ClaimType.risk, ClaimType.recurring_problem, ClaimType.next_action)


@dataclass
class TimelineItem:
    when: datetime | None
    claim: Claim
    approved: bool
    sources: list[str]


def _claim_date(claim: Claim) -> datetime | None:
    dates = [e.chunk.occurred_at for e in claim.evidence if e.chunk is not None and e.chunk.occurred_at]
    return min(dates) if dates else None


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def build_timeline(session: Session, project, role: Role, *, include_drafts: bool = False,
                   types: tuple[ClaimType, ...] = TIMELINE_TYPES) -> list[TimelineItem]:
    include_drafts = include_drafts and role in REVIEWER_ROLES
    q = select(Claim).where(Claim.project_id == project.id, Claim.type.in_(types),
                            Claim.review_status != ReviewStatus.rejected).order_by(Claim.id)
    items: list[TimelineItem] = []
    for c in session.scalars(q):
        approved = c.review_status == ReviewStatus.approved
        if approved:
            if not visible_in_handover(role, c):
                continue
        elif not (include_drafts and role_can_see(role, effective_sensitivity(c))):
            continue
        names = []
        for e in c.evidence:
            n = e.chunk.source.name if e.chunk is not None and e.chunk.source is not None else None
            if n and n not in names and role_can_see(role, effective_sensitivity(c)):
                names.append(n)
        items.append(TimelineItem(_claim_date(c), c, approved, names))
    dated = sorted((i for i in items if i.when), key=lambda i: (_naive(i.when), i.claim.id))
    undated = [i for i in items if not i.when]
    return dated + undated


@dataclass
class PersonRisk:
    person: str
    claims: list[Claim] = field(default_factory=list)
    total_claims_touched: int = 0

    @property
    def sole(self) -> int:
        return len(self.claims)


@dataclass
class BusFactor:
    people: list[PersonRisk]
    unattributed: int
    examined: int


def build_bus_factor(session: Session, project, role: Role) -> BusFactor:
    """Only reviewers use this (the page enforces it); claims above the role's clearance are skipped."""
    by_person: dict[str, PersonRisk] = {}
    unattributed = examined = 0
    for c in session.scalars(select(Claim).where(Claim.project_id == project.id,
                                                 Claim.review_status != ReviewStatus.rejected)
                             .order_by(Claim.id)):
        if not role_can_see(role, effective_sensitivity(c)):
            continue
        examined += 1
        authors = {e.chunk.author for e in c.evidence if e.chunk is not None and e.chunk.author}
        if not authors:
            unattributed += 1
            continue
        for a in authors:
            by_person.setdefault(a, PersonRisk(a)).total_claims_touched += 1
        if len(authors) == 1:
            by_person[next(iter(authors))].claims.append(c)
    people = sorted(by_person.values(), key=lambda p: (-p.sole, p.person))
    return BusFactor(people, unattributed, examined)
