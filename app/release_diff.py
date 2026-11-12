"""What changed between two releases, from the exact (claim id, version) pairs signed off."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import visible_in_review
from .enums import ConflictStatus, Role
from .models import Claim, ClaimVersion, Conflict, HandoverRelease


@dataclass
class ReleaseDiff:
    previous: HandoverRelease | None
    added: list = field(default_factory=list)      # (claim, statement)
    removed: list = field(default_factory=list)
    updated: list = field(default_factory=list)    # (claim, old statement, new statement)
    resolved_conflicts: list = field(default_factory=list)


def _texts(session: Session, pairs: set[tuple[int, int]]) -> dict[tuple[int, int], str]:
    """Statement for each (claim id, version), in one query."""
    if not pairs:
        return {}
    out = {}
    for v in session.scalars(select(ClaimVersion).where(
            ClaimVersion.claim_id.in_({cid for cid, _ in pairs}))):
        if (v.claim_id, v.version) in pairs:
            out[(v.claim_id, v.version)] = v.statement
    return out


def release_diff(session: Session, role: Role, release: HandoverRelease,
                 previous: HandoverRelease | None, project_id: int) -> ReleaseDiff:
    d = ReleaseDiff(previous)
    new = dict(release.entries)
    old = dict(previous.entries) if previous else {}
    claims = {c.id: c for c in session.scalars(select(Claim).where(
        Claim.id.in_(set(new) | set(old))))}
    texts = _texts(session, set(new.items()) | set(old.items()))
    _text = lambda cid, ver: texts.get((cid, ver), "")
    ok = lambda cid: cid in claims and visible_in_review(role, claims[cid])
    for cid, ver in new.items():
        if not ok(cid):
            continue
        if cid not in old:
            d.added.append((claims[cid], _text(cid, ver)))
        elif old[cid] != ver:
            d.updated.append((claims[cid], _text(cid, old[cid]), _text(cid, ver)))
    for cid, ver in old.items():
        if cid not in new and ok(cid):
            d.removed.append((claims[cid], _text(cid, ver)))
    if previous:
        for cf in session.scalars(select(Conflict).where(
                Conflict.project_id == project_id, Conflict.status == ConflictStatus.resolved)):
            at = cf.resolved_at
            if at is not None and previous.approved_at.replace(tzinfo=None) < at.replace(tzinfo=None) \
                    <= release.approved_at.replace(tzinfo=None):
                d.resolved_conflicts.append(cf)
    return d
