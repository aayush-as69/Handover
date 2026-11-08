""""Questions Before I Leave": gaps the outgoing person is best placed to fill.

Every question comes from a mechanical rule over the claims, so it can say exactly why it
was asked. Questions are linked to claims and inherit their sensitivity. An answer is the
person's own words: it is shown as "stated by", never as a verified fact.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .enums import ClaimType, ConflictStatus, QuestionStatus, ReviewStatus, SourceKind
from .conflicts import LEXICON, _mentions
from .models import Claim, Conflict, Project, Question, User, utcnow

_REASON = re.compile(r"\b(because|reason|since|so that|so we|due to|in order to|why)\b", re.I)
_CHOICE = re.compile(r"\b(use|using|go in|goes in|chose|choose|chosen|switch|adopt|replace|migrate|build on)\b", re.I)
_DOC_PROMISE = re.compile(r"\b(write (it )?(down|up)|document(ation)?|set ?up doc|runbook|how .* is set up)\b", re.I)


def _known_first_names(session: Session, claims: list[Claim]) -> set[str]:
    names: set[str] = set()
    for u in session.scalars(select(User)):
        names.update(p.lower() for p in u.display_name.split() if len(p) > 2)
    for c in claims:
        if c.owner:
            names.update(p.lower() for p in c.owner.split() if len(p) > 2)
    return names


def _names_someone(text: str, names: set[str]) -> bool:
    words = {w.lower() for w in re.findall(r"[A-Za-z]+", text)}
    return bool(words & names)


def _github_only(c: Claim) -> bool:
    kinds = {e.chunk.source.kind for e in c.evidence if e.chunk and e.chunk.source}
    return bool(kinds) and kinds == {SourceKind.github}


def _mentions_tech(text: str) -> bool:
    return any(_mentions(text, cat) for cat in LEXICON)


def _short(text: str, n: int = 110) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def wanted(session: Session, project: Project) -> dict[str, tuple[str, str, list[int]]]:
    """key -> (kind, question text, claim ids)."""
    claims = [c for c in session.scalars(select(Claim).where(Claim.project_id == project.id)
                                         .order_by(Claim.id))
              if c.review_status != ReviewStatus.rejected]
    names = _known_first_names(session, claims)
    out: dict[str, tuple[str, str, list[int]]] = {}

    for c in claims:
        quote = _short(c.statement)
        text_all = c.statement + " " + " ".join(e.snippet for e in c.evidence)
        if c.type == ClaimType.decision and not _REASON.search(text_all) \
                and (_CHOICE.search(c.statement) or _mentions_tech(c.statement)):
            out[f"reason:{c.id}"] = ("no_reason",
                f"Why was this decided? “{quote}” No reason appears in any source.", [c.id])
        if c.type in (ClaimType.next_action, ClaimType.blocker) and not c.owner \
                and not _names_someone(c.statement, names):
            out[f"owner:{c.id}"] = ("no_owner",
                f"Who owns this? “{quote}” No owner is named.", [c.id])
        if c.type == ClaimType.owner and re.search(r"\bno owner\b", c.statement, re.I):
            out[f"owner:{c.id}"] = ("no_owner",
                f"Who should own this? “{quote}”", [c.id])
        if c.type == ClaimType.open_question:
            out[f"open:{c.id}"] = ("open_question",
                f"Still unanswered: “{quote}” Who will answer it, and by when?", [c.id])
        if c.type in (ClaimType.risk, ClaimType.recurring_problem) and not _github_only(c) \
                and not _names_someone(c.statement, names):
            out[f"risk:{c.id}"] = ("risk_no_owner",
                f"Who is watching this risk, and what is the next step? “{quote}”", [c.id])
        if c.type == ClaimType.next_action and _DOC_PROMISE.search(c.statement):
            out[f"promise:{c.id}"] = ("undocumented_promise",
                f"This was promised but may not exist yet: “{quote}” "
                "Where will it live, and has it been started?", [c.id])

    for cf in session.scalars(select(Conflict).where(Conflict.project_id == project.id,
                                                     Conflict.status == ConflictStatus.open)):
        out[f"conflict:{cf.id}"] = ("conflict",
            f"The sources disagree about {cf.topic}. {cf.reason} Which is right today?",
            cf.claim_ids)
    return out


def generate_questions(session: Session, project: Project) -> list[Question]:
    """Create new questions, close ones that no longer apply. Answers are never overwritten."""
    want = wanted(session, project)
    rows = {q.key: q for q in session.scalars(select(Question).where(Question.project_id == project.id))}
    for key, (kind, text, ids) in want.items():
        row = rows.get(key)
        csv = ",".join(map(str, ids))
        if row is None:
            session.add(Question(project_id=project.id, key=key, kind=kind, text=text, claim_csv=csv))
        else:
            row.text, row.claim_csv = text, csv
            if row.status == QuestionStatus.closed:
                row.status = QuestionStatus.open
    for key, row in rows.items():
        if key not in want and row.status == QuestionStatus.open:
            row.status = QuestionStatus.closed
    session.flush()
    return list(session.scalars(select(Question).where(Question.project_id == project.id)
                                .order_by(Question.id)))


def answer(q: Question, by: str, text: str) -> None:
    text = " ".join(text.split())
    if not text:
        raise ValueError("Write an answer first.")
    if len(text) > 1500:
        raise ValueError("Keep the answer under 1500 characters.")
    q.status, q.answer, q.answered_by, q.answered_at = QuestionStatus.answered, text, by, utcnow()


def dismiss(q: Question, by: str) -> None:
    q.status, q.answered_by, q.answered_at = QuestionStatus.dismissed, by, utcnow()
