"""What a claim is connected to, using only relationships the system has recorded.

For one claim: the sources and people behind its evidence, other claims that rest on the
same source, and the questions raised about it. No guessing from similar wording. Anything
the viewer's role may not read is left out, and a hidden item is never counted or named.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import chunk_visible, visible_in_review
from .enums import QuestionStatus, ReviewStatus
from .models import Chunk, Claim, Evidence, Question, User

MAX_RELATED = 12


@dataclass
class Connections:
    sources: list = field(default_factory=list)     # (source, [locators])
    people: list = field(default_factory=list)      # (name, count of passages)
    related: list = field(default_factory=list)     # (claim, shared source names)
    questions: list = field(default_factory=list)

    def empty(self) -> bool:
        return not (self.sources or self.people or self.related or self.questions)


def claim_connections(session: Session, user: User, claim: Claim) -> Connections:
    out = Connections()
    chunks = [e.chunk for e in claim.evidence if e.chunk is not None and chunk_visible(user.role, e.chunk)]

    by_source: dict[int, tuple] = {}
    people: dict[str, int] = {}
    for ch in chunks:
        src, locs = by_source.setdefault(ch.source_id, (ch.source, []))
        if ch.locator not in locs:
            locs.append(ch.locator)
        if ch.author:
            people[ch.author] = people.get(ch.author, 0) + 1
    out.sources = list(by_source.values())
    out.people = sorted(people.items(), key=lambda x: -x[1])

    if by_source:
        rows = session.scalars(
            select(Claim).join(Evidence, Evidence.claim_id == Claim.id)
            .join(Chunk, Chunk.id == Evidence.chunk_id)
            .where(Claim.project_id == claim.project_id, Claim.id != claim.id,
                   Claim.review_status != ReviewStatus.rejected,
                   Chunk.source_id.in_(list(by_source)))
            .distinct().order_by(Claim.id))
        for other in rows:
            if not visible_in_review(user.role, other):
                continue
            shared = sorted({e.chunk.source.name for e in other.evidence
                             if e.chunk is not None and e.chunk.source_id in by_source})
            out.related.append((other, shared))
            if len(out.related) >= MAX_RELATED:
                break

    for q in session.scalars(select(Question).where(
            Question.project_id == claim.project_id,
            Question.status == QuestionStatus.open).order_by(Question.id)):
        if claim.id not in q.claim_ids:
            continue
        linked = {c.id: c for c in session.scalars(select(Claim).where(Claim.id.in_(q.claim_ids)))}
        if all(visible_in_review(user.role, c) for c in linked.values()):
            out.questions.append(q)
    return out


@dataclass
class Breakdown:
    quotes: int                 # supporting quotes the role may see
    found: int                  # of those, found word for word in the source
    sources: int
    kinds: list
    contradicting: int
    semantic: str | None        # advisory model opinion, if one was recorded
    tree: list = field(default_factory=list)    # (source name, kind, [(locator, quote, chunk id)])


def evidence_breakdown(user: User, claim: Claim) -> Breakdown:
    """Plain facts about a claim's evidence. Counts, not scores: nothing here is a guess."""
    sup = [e for e in claim.evidence
           if e.stance.value == "supports" and e.chunk is not None and chunk_visible(user.role, e.chunk)]
    tree: dict[int, tuple] = {}
    for e in sup:
        src = e.chunk.source
        entry = tree.setdefault(e.chunk.source_id, (src.name, src.kind.value, []))
        entry[2].append((e.chunk.locator, e.snippet, e.chunk.id))
    return Breakdown(
        quotes=len(sup), found=sum(1 for e in sup if e.snippet_verified),
        sources=len(tree), kinds=sorted({t[1] for t in tree.values()}),
        contradicting=sum(1 for e in claim.evidence if e.stance.value == "contradicts"),
        semantic=claim.semantic_verdict, tree=list(tree.values()))
