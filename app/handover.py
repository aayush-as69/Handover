"""Handover logic: sign-off, role-filtered sections and acknowledgement.

The handover is a live view over APPROVED claims, filtered through app.access for the
viewer's role. Because it is computed on every request, rejecting or reopening a claim (or
editing it, which sends it back for approval) removes it from every view immediately.
Only an approver or admin can sign the handover off, and nobody else sees anything until
they do.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import filter_handover
from .enums import REVIEWER_ROLES, ClaimType, HandoverStatus, ReviewStatus
from .models import Acknowledgement, Claim, Handover, Project, User, utcnow

SECTIONS: list[tuple[str, str, list[ClaimType]]] = [
    ("first-week", "Your first week",
     [ClaimType.blocker, ClaimType.next_action, ClaimType.open_question]),
    ("decisions", "Decisions and why they were made", [ClaimType.decision]),
    ("risks", "Risks and recurring problems", [ClaimType.risk, ClaimType.recurring_problem]),
    ("dependencies", "Dependencies", [ClaimType.dependency]),
    ("people", "Who owns what, and who to ask", [ClaimType.owner, ClaimType.contact]),
]


class HandoverError(ValueError):
    """The action is not allowed. The message is safe to show."""


@dataclass
class Section:
    key: str
    title: str
    claims: list[Claim]


def get_handover(session: Session, project: Project) -> Handover | None:
    return session.scalar(select(Handover).where(Handover.project_id == project.id)
                          .order_by(Handover.id))


def get_or_create_handover(session: Session, project: Project) -> Handover:
    h = get_handover(session, project)
    if h is None:
        h = Handover(project_id=project.id, title=f"{project.name} handover",
                     outgoing_name=project.outgoing_member or "the outgoing member")
        session.add(h)
        session.flush()
    return h


def can_view(user: User, handover: Handover | None) -> bool:
    """Reviewers may preview a draft. Everyone else needs a signed-off handover."""
    if handover is None:
        return False
    return user.role in REVIEWER_ROLES or handover.status == HandoverStatus.approved


def approve_handover(session: Session, handover: Handover, user: User) -> None:
    if user.role not in REVIEWER_ROLES:
        raise HandoverError("Only approvers and admins can sign off a handover.")
    approved = session.scalars(select(Claim).where(
        Claim.project_id == handover.project_id,
        Claim.review_status == ReviewStatus.approved)).all()
    if not approved:
        raise HandoverError("Approve at least one claim before signing off the handover.")
    handover.status = HandoverStatus.approved
    handover.approved_by_id = user.id
    handover.approved_at = utcnow()
    session.flush()


def withdraw_handover(session: Session, handover: Handover, user: User) -> None:
    if user.role not in REVIEWER_ROLES:
        raise HandoverError("Only approvers and admins can withdraw a handover.")
    handover.status = HandoverStatus.draft
    session.flush()


def build_sections(session: Session, project: Project, user: User) -> list[Section]:
    claims = filter_handover(user.role, session.scalars(
        select(Claim).where(Claim.project_id == project.id).order_by(Claim.id)).all())
    out = []
    for key, title, types in SECTIONS:
        items = [c for t in types for c in claims if c.type == t]
        if items:
            out.append(Section(key, title, items))
    return out


def pending_count(session: Session, project: Project) -> int:
    return len(session.scalars(select(Claim.id).where(
        Claim.project_id == project.id,
        Claim.review_status.in_([ReviewStatus.generated, ReviewStatus.edited]))).all())


def acknowledge(session: Session, handover: Handover, user: User) -> bool:
    """Record that this person has read the handover. Returns False if already recorded."""
    if not can_view(user, handover) or handover.status != HandoverStatus.approved:
        raise HandoverError("There is no signed-off handover to acknowledge.")
    existing = session.scalar(select(Acknowledgement).where(
        Acknowledgement.handover_id == handover.id, Acknowledgement.user_id == user.id))
    if existing:
        return False
    session.add(Acknowledgement(handover_id=handover.id, user_id=user.id))
    session.flush()
    return True
