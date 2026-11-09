"""Access rules. These live in the core, not in the UI, so every view goes through them.

Rules:
* A claim's effective sensitivity is the HIGHEST of its own label and every piece of
  evidence behind it (chunk and source). A claim derived from a confidential message is
  confidential, even if someone labelled the claim itself 'team'. Fail closed.
* A handover view only ever contains APPROVED claims. Generated, edited and rejected
  claims are never shown as organisational truth.
* Rejected claims never appear in any handover view, for any role.
* Only approvers and admins may use the review queue, and only within their clearance.
"""

from __future__ import annotations

from typing import Iterable

from .enums import ROLE_CLEARANCE, SENSITIVITY_RANK, ReviewStatus, Role, Sensitivity
from sqlalchemy import case, func, select

from .models import Chunk, Claim, Evidence, Source


def role_can_see(role: Role, sensitivity: Sensitivity) -> bool:
    return SENSITIVITY_RANK[sensitivity] <= SENSITIVITY_RANK[ROLE_CLEARANCE[role]]


def effective_sensitivity(claim: Claim) -> Sensitivity:
    levels = [claim.sensitivity]
    for ev in claim.evidence:
        if ev.chunk is not None:
            levels.append(ev.chunk.sensitivity)
            if ev.chunk.source is not None:
                levels.append(ev.chunk.source.sensitivity)
    return max(levels, key=lambda s: SENSITIVITY_RANK[s])


def chunk_visible(role: Role, chunk: Chunk) -> bool:
    """Whether a role may open the original source text behind a citation."""
    level = max(
        chunk.sensitivity,
        chunk.source.sensitivity if chunk.source is not None else chunk.sensitivity,
        key=lambda s: SENSITIVITY_RANK[s],
    )
    return role_can_see(role, level)


def visible_in_handover(role: Role, claim: Claim) -> bool:
    return claim.review_status == ReviewStatus.approved and role_can_see(
        role, effective_sensitivity(claim)
    )


def visible_in_review(role: Role, claim: Claim) -> bool:
    if role not in (Role.admin, Role.approver):
        return False
    return role_can_see(role, effective_sensitivity(claim))


def filter_handover(role: Role, claims: Iterable[Claim]) -> list[Claim]:
    return [c for c in claims if visible_in_handover(role, c)]


def filter_review(role: Role, claims: Iterable[Claim]) -> list[Claim]:
    return [c for c in claims if visible_in_review(role, c)]


# ---------------------------------------------------------------- the same rule, in SQL
# The review queue filters, counts and pages inside the database instead of loading every
# claim. This must agree with effective_sensitivity(); a test compares them claim by claim.

_BY_RANK = {rank: sens for sens, rank in SENSITIVITY_RANK.items()}


def _rank(column):
    # An unknown value ranks above everything (fail closed).
    return case(*[(column == sens, rank) for sens, rank in SENSITIVITY_RANK.items()],
                else_=max(SENSITIVITY_RANK.values()) + 1)


def effective_rank_sql():
    """SQL expression: the highest rank among a claim, its evidence chunks and their sources."""
    chunk_max = (select(func.max(_rank(Chunk.sensitivity))).select_from(Evidence)
                 .join(Chunk, Evidence.chunk_id == Chunk.id)
                 .where(Evidence.claim_id == Claim.id).scalar_subquery())
    source_max = (select(func.max(_rank(Source.sensitivity))).select_from(Evidence)
                  .join(Chunk, Evidence.chunk_id == Chunk.id).join(Source, Chunk.source_id == Source.id)
                  .where(Evidence.claim_id == Claim.id).scalar_subquery())
    own = _rank(Claim.sensitivity)
    a, b, c = own, func.coalesce(chunk_max, 0), func.coalesce(source_max, 0)
    step = case((a >= b, a), else_=b)
    return case((step >= c, step), else_=c)


def sensitivity_from_rank(rank: int) -> Sensitivity:
    return _BY_RANK.get(rank, Sensitivity.confidential)


def clearance_rank(role: Role) -> int:
    return SENSITIVITY_RANK[ROLE_CLEARANCE[role]]
