"""Takeover brief: one page that tells the incoming owner where to start.

Built only from the claims the viewer's role may read in the released handover, so it can
never show more than the handover page does. Nothing is invented: each line is a claim,
a recorded conflict or an outgoing-person question. Priorities follow fixed rules, not a
model's opinion: unresolved conflicts, then blockers, then risks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .enums import ClaimType, Confidence
from .handover import Section


@dataclass
class Health:
    total: int = 0
    verified: int = 0
    needs_care: int = 0        # inferred, conflicting or unsupported
    risks: int = 0
    open_conflicts: int = 0
    open_questions: int = 0
    single_source_people: int = 0

    @property
    def verified_pct(self) -> int:
        return round(100 * self.verified / self.total) if self.total else 0


@dataclass
class StartItem:
    claim: object
    reason: str


@dataclass
class Brief:
    health: Health
    start_here: list[StartItem] = field(default_factory=list)
    decisions: list = field(default_factory=list)
    people: list = field(default_factory=list)
    risks: list = field(default_factory=list)
    questions: list = field(default_factory=list)       # claims of type open_question
    answered: list = field(default_factory=list)        # (question text, answer, who)
    unanswered: list = field(default_factory=list)      # question rows still open
    actions: list = field(default_factory=list)
    depends_on: list = field(default_factory=list)      # (person, [claims])


def _authors(claim) -> set[str]:
    return {e.chunk.author for e in claim.evidence if e.chunk is not None and e.chunk.author}


def build_brief(sections: list[Section], conflict_notes: dict, question_rows: list,
                answers: list) -> Brief:
    claims = [c for s in sections for c in s.claims]
    by_type = lambda *t: [c for c in claims if c.type in t]

    # People who are the only recorded source for several shown claims.
    sole: dict[str, list] = {}
    for c in claims:
        who = _authors(c)
        if len(who) == 1 and c.evidence and all(e.chunk is not None and e.chunk.author for e in c.evidence):
            sole.setdefault(next(iter(who)), []).append(c)
    depends = sorted(((p, cs) for p, cs in sole.items() if len(cs) >= 2),
                     key=lambda x: -len(x[1]))

    open_conflict_ids = {cid for cid, notes in conflict_notes.items()
                         if any(not res for _, res in notes)}
    brief = Brief(health=Health(
        total=len(claims),
        verified=sum(c.confidence == Confidence.verified for c in claims),
        needs_care=sum(c.confidence != Confidence.verified for c in claims),
        risks=len(by_type(ClaimType.risk, ClaimType.recurring_problem)),
        open_conflicts=len(open_conflict_ids),
        open_questions=len(by_type(ClaimType.open_question)) + len(question_rows),
        single_source_people=len(depends)))

    seen: set[int] = set()

    def add(c, reason):
        if c.id not in seen and len(brief.start_here) < 5:
            seen.add(c.id)
            brief.start_here.append(StartItem(c, reason))

    for c in claims:
        if c.id in open_conflict_ids:
            add(c, "Sources disagree and nobody has resolved it")
    for c in by_type(ClaimType.blocker):
        add(c, "Currently blocking work")
    for c in by_type(ClaimType.risk):
        add(c, "Known risk")

    brief.decisions = by_type(ClaimType.decision)
    brief.people = by_type(ClaimType.owner, ClaimType.contact)
    brief.risks = by_type(ClaimType.risk, ClaimType.recurring_problem, ClaimType.blocker)
    brief.questions = by_type(ClaimType.open_question)
    brief.unanswered = question_rows
    brief.answered = [(q.text, q.answer, q.answered_by) for q in answers]
    brief.actions = by_type(ClaimType.next_action)
    brief.depends_on = depends
    return brief
