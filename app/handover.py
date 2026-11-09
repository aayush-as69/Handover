"""Handover logic: sign-off, role-filtered sections and acknowledgement.

The handover is a live view over APPROVED claims, filtered through app.access for the
viewer's role. Because it is computed on every request, rejecting or reopening a claim (or
editing it, which sends it back for approval) removes it from every view immediately.
Only an approver or admin can sign the handover off, and nobody else sees anything until
they do.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .access import filter_handover
from .enums import REVIEWER_ROLES, ClaimType, HandoverStatus, ReviewStatus, Role
from .models import Acknowledgement, Claim, Handover, HandoverRelease, Project, User, utcnow

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
    return session.scalar(select(Handover).where(Handover.project_id == project.id))


def get_or_create_handover(session: Session, project: Project) -> Handover:
    """Race-safe: if two requests create it at once, the unique constraint lets one win."""
    h = get_handover(session, project)
    if h is not None:
        return h
    try:
        with session.begin_nested():
            session.add(Handover(project_id=project.id, title=f"{project.name} handover",
                                 outgoing_name=project.outgoing_member or "the outgoing member"))
    except IntegrityError:
        pass                                    # someone else created it first
    return get_handover(session, project)


def latest_release(session: Session, handover: Handover | None) -> HandoverRelease | None:
    if handover is None:
        return None
    return session.scalar(select(HandoverRelease).where(HandoverRelease.handover_id == handover.id)
                          .order_by(HandoverRelease.number.desc()))


def releases(session: Session, handover: Handover) -> list[HandoverRelease]:
    return list(session.scalars(select(HandoverRelease).where(HandoverRelease.handover_id == handover.id)
                                .order_by(HandoverRelease.number.desc())))


def can_view(user: User, handover: Handover | None) -> bool:
    """Reviewers may preview a draft. Everyone else needs a published release."""
    if handover is None:
        return False
    return user.role in REVIEWER_ROLES or handover.status == HandoverStatus.approved


def approve_handover(session: Session, handover: Handover, user: User) -> HandoverRelease:
    """Sign off: freeze the currently approved claims into a new numbered release."""
    if user.role not in REVIEWER_ROLES:
        raise HandoverError("Only approvers and admins can sign off a handover.")
    approved = session.scalars(select(Claim).where(
        Claim.project_id == handover.project_id,
        Claim.review_status == ReviewStatus.approved).order_by(Claim.id)).all()
    if not approved:
        raise HandoverError("Approve at least one claim before signing off the handover.")
    last = latest_release(session, handover)
    release = HandoverRelease(
        handover_id=handover.id, number=(last.number + 1) if last else 1,
        approved_by_id=user.id, approved_by_name=user.display_name,
        claims_json=json.dumps([[c.id, c.version] for c in approved]))
    try:
        with session.begin_nested():
            session.add(release)
    except IntegrityError:
        raise HandoverError("Someone signed off at the same moment. Refresh and check the result.")
    handover.status = HandoverStatus.approved
    handover.approved_by_id, handover.approved_at = user.id, release.approved_at or utcnow()
    session.flush()
    return release


def withdraw_handover(session: Session, handover: Handover, user: User) -> None:
    if user.role not in REVIEWER_ROLES:
        raise HandoverError("Only approvers and admins can withdraw a handover.")
    handover.status = HandoverStatus.draft
    session.flush()


@dataclass
class ReleaseState:
    release: HandoverRelease | None
    still_valid: int = 0           # claims in the release that are unchanged and still approved
    withdrawn: int = 0             # claims in the release that were edited, rejected or reopened since
    not_yet_released: int = 0      # approved now, but not part of the release


def release_state(session: Session, project: Project, handover: Handover | None) -> ReleaseState:
    rel = latest_release(session, handover)
    approved = {c.id: c for c in session.scalars(select(Claim).where(
        Claim.project_id == project.id, Claim.review_status == ReviewStatus.approved))}
    if rel is None:
        return ReleaseState(None, 0, 0, len(approved))
    valid = {cid for cid, ver in rel.entries if cid in approved and approved[cid].version == ver}
    return ReleaseState(rel, len(valid), len(rel.entries) - len(valid),
                        len([c for c in approved if c not in {cid for cid, _ in rel.entries}]))


def is_stale(session: Session, project: Project, handover: Handover | None) -> bool:
    """True when something signed off has since been edited, rejected or reopened.

    A sign-off covers exactly what was approved at that moment. Once any of it changes, the
    sign-off no longer describes what readers would see, so non-reviewers see nothing until
    a reviewer signs off again. Derived on every read, so no code path can forget to apply it.
    """
    if handover is None or handover.status != HandoverStatus.approved:
        return False
    return release_state(session, project, handover).withdrawn > 0


def _view_claims(session: Session, project: Project, handover: Handover) -> list[Claim]:
    """What is shown. A published handover shows its latest release, minus anything changed
    since (fail closed). An unpublished draft previews the currently approved claims."""
    if handover.status != HandoverStatus.approved:
        return list(session.scalars(select(Claim).where(
            Claim.project_id == project.id, Claim.review_status == ReviewStatus.approved)
            .order_by(Claim.id)))
    rel = latest_release(session, handover)
    if rel is None:
        return []
    claims = {c.id: c for c in session.scalars(select(Claim).where(
        Claim.id.in_([cid for cid, _ in rel.entries])))}
    return [claims[cid] for cid, ver in rel.entries
            if cid in claims and claims[cid].version == ver
            and claims[cid].review_status == ReviewStatus.approved]


def build_sections(session: Session, project: Project, user: User,
                   role: Role | None = None) -> list[Section]:
    """Sections for `role` (defaults to the user's own). Only reviewers may ask for another."""
    role = role or user.role
    if role != user.role and user.role not in REVIEWER_ROLES:
        raise HandoverError("Only reviewers can preview another role.")
    handover = get_handover(session, project)
    if handover is None or not can_view(user, handover):
        return []
    if user.role not in REVIEWER_ROLES and is_stale(session, project, handover):
        return []
    claims = filter_handover(role, _view_claims(session, project, handover))
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
    """Record that this person read the latest release. False if already recorded.

    Safe under double clicks and parallel requests: the unique constraint decides.
    """
    rel = latest_release(session, handover)
    if not can_view(user, handover) or handover.status != HandoverStatus.approved or rel is None:
        raise HandoverError("There is no signed-off handover to acknowledge.")
    project = session.get(Project, handover.project_id)
    if is_stale(session, project, handover):
        raise HandoverError("The handover changed after it was signed off. Wait for the new sign-off.")
    if session.scalar(select(Acknowledgement).where(
            Acknowledgement.release_id == rel.id, Acknowledgement.user_id == user.id)):
        return False
    try:
        with session.begin_nested():
            session.add(Acknowledgement(release_id=rel.id, user_id=user.id))
    except IntegrityError:
        return False
    return True


def conflict_notes(session: Session, project: Project, shown: set[int]) -> dict[int, list[tuple[str, str]]]:
    """For claims on this page: other claims they conflict with, but only ones also on the page.

    Returns claim id -> [(other statement, resolution or "")]. A partner the viewer cannot
    see is never mentioned, so a warning cannot reveal hidden information.
    """
    from .enums import ConflictStatus
    from .models import Conflict

    claims = {c.id: c for c in session.scalars(select(Claim).where(Claim.project_id == project.id))}
    notes: dict[int, list[tuple[str, str]]] = {}
    for cf in session.scalars(select(Conflict).where(
            Conflict.project_id == project.id, Conflict.status != ConflictStatus.stale)):
        resolution = f"Resolved by {cf.resolved_by}: {cf.resolution}" if cf.status == ConflictStatus.resolved else ""
        members = [i for i in cf.claim_ids if i in shown]
        for i in members:
            for j in members:
                if i != j:
                    notes.setdefault(i, []).append((claims[j].statement, resolution))
    return notes


def answered_questions(session: Session, project: Project, shown: set[int]) -> list:
    """Answers from the outgoing person, only where every linked claim is on this page."""
    from .enums import QuestionStatus
    from .models import Question

    return [q for q in session.scalars(select(Question).where(
                Question.project_id == project.id, Question.status == QuestionStatus.answered)
                .order_by(Question.id))
            if q.claim_ids and all(i in shown for i in q.claim_ids)]
