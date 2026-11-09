"""Cross-source conflict detection.

Two mechanical rules, both explained to the reviewer, neither a model's opinion:

1. Explicit topics. If claims carry a `topic` and `value` (the LLM extractor can fill these)
   and two live claims share a topic with different values, they conflict.
2. Exclusivity. A claim that says something is "the only" X (for a known category of
   technology, such as datastore or payment gateway) conflicts with any other live claim that
   mentions a different technology in that category.

A conflict is a prompt for a person. It never changes a claim's review status or confidence.
Rejected claims are ignored. Detection is repeatable: re-running updates, never duplicates,
and a resolution a person recorded is kept unless a new claim joins the dispute.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import visible_in_review
from .enums import ClaimType, ConflictStatus, ReviewStatus, Role
from .models import Claim, Conflict, Project, utcnow

# category -> (words that name the category, {canonical value: spellings})
LEXICON: dict[str, tuple[set[str], dict[str, set[str]]]] = {
    "datastore": ({"datastore", "database", "db", "storage", "data store"}, {
        "PostgreSQL": {"postgresql", "postgres"}, "MongoDB": {"mongodb", "mongo"},
        "MySQL": {"mysql"}, "SQLite": {"sqlite"}, "Redis": {"redis"},
        "DynamoDB": {"dynamodb"}, "Cassandra": {"cassandra"},
        "Elasticsearch": {"elasticsearch"}}),
    "payment gateway": ({"gateway", "payment provider", "payments provider"}, {
        "PayNest": {"paynest"}, "Stripe": {"stripe"}, "Razorpay": {"razorpay"},
        "PayPal": {"paypal"}}),
    "frontend framework": ({"frontend", "front end", "ui framework"}, {
        "React": {"react"}, "Vue": {"vue"}, "Angular": {"angular"}, "Svelte": {"svelte"}}),
    "backend framework": ({"backend", "back end", "api framework"}, {
        "FastAPI": {"fastapi"}, "Flask": {"flask"}, "Django": {"django"},
        "Express": {"express"}}),
}
_EXCLUSIVE = re.compile(r"\b(only|sole|solely|exclusively)\b", re.I)


@dataclass
class Found:
    topic: str
    key: str
    reason: str
    claims: list[Claim] = field(default_factory=list)


def _mentions(text: str, category: str) -> set[str]:
    low = text.lower()
    out = set()
    for canonical, spellings in LEXICON[category][1].items():
        if any(re.search(rf"\b{re.escape(w)}\b", low) for w in spellings):
            out.add(canonical)
    return out


def _live(session: Session, project: Project) -> list[Claim]:
    return [c for c in session.scalars(select(Claim).where(Claim.project_id == project.id)
                                       .order_by(Claim.id))
            if c.review_status != ReviewStatus.rejected]


def find_conflicts(claims: list[Claim]) -> list[Found]:
    found: list[Found] = []

    # rule 1: explicit topic/value
    by_topic: dict[str, dict[str, list[Claim]]] = {}
    for c in claims:
        if c.topic and c.value:
            by_topic.setdefault(c.topic.strip().lower(), {}).setdefault(
                c.value.strip().lower(), []).append(c)
    for topic, values in by_topic.items():
        if len(values) > 1:
            members = sorted({c.id: c for vs in values.values() for c in vs}.values(),
                             key=lambda c: c.id)
            shown = ", ".join(sorted(v for v in values))
            found.append(Found(topic, f"topic:{topic}",
                               f"Claims give different values for “{topic}”: {shown}.", members))

    # rule 2: exclusivity
    for c in claims:
        if c.type == ClaimType.open_question or not _EXCLUSIVE.search(c.statement):
            continue
        low = c.statement.lower()
        for category, (words, _) in LEXICON.items():
            own = _mentions(c.statement, category)
            if len(own) != 1 or not any(w in low for w in words):
                continue
            (value,) = own
            others = [o for o in claims if o.id != c.id and o.type != ClaimType.open_question
                      and (_mentions(o.statement, category) - own)]
            if others:
                other_values = sorted({v for o in others for v in _mentions(o.statement, category)} - own)
                found.append(Found(
                    category, f"only:{category}:{c.id}",
                    f"One claim says {value} is the only {category}, but other claims "
                    f"mention {', '.join(other_values)}.",
                    sorted([c, *others], key=lambda x: x.id)))
    return found


def detect_conflicts(session: Session, project: Project) -> list[Conflict]:
    found = find_conflicts(_live(session, project))
    existing = {c.key: c for c in session.scalars(
        select(Conflict).where(Conflict.project_id == project.id))}
    seen = set()
    for f in found:
        seen.add(f.key)
        csv = ",".join(str(c.id) for c in f.claims)
        row = existing.get(f.key)
        if row is None:
            row = Conflict(project_id=project.id, key=f.key, topic=f.topic, reason=f.reason,
                           claim_csv=csv)
            session.add(row)
        else:
            joined = set(map(int, csv.split(","))) - set(row.claim_ids)
            row.reason, row.claim_csv = f.reason, csv
            if row.status == ConflictStatus.stale or (row.status == ConflictStatus.resolved and joined):
                row.status = ConflictStatus.open       # new disagreement: look again
                row.resolution = row.resolved_by = row.resolved_at = None
    for key, row in existing.items():
        if key not in seen and row.status == ConflictStatus.open:
            row.status = ConflictStatus.stale
    session.flush()
    return [c for c in session.scalars(select(Conflict).where(Conflict.project_id == project.id)
                                       .order_by(Conflict.id))]


def resolve(conflict: Conflict, by: str, note: str) -> None:
    if not note.strip():
        raise ValueError("Say how it was resolved.")
    conflict.status, conflict.resolution = ConflictStatus.resolved, note.strip()
    conflict.resolved_by, conflict.resolved_at = by, utcnow()


def reopen(conflict: Conflict) -> None:
    conflict.status = ConflictStatus.open
    conflict.resolution = conflict.resolved_by = conflict.resolved_at = None


def visible_members(role: Role, conflict: Conflict, claims_by_id: dict[int, Claim]) -> list[Claim]:
    """Members a reviewer role may see. A conflict with fewer than two is hidden entirely."""
    members = [claims_by_id[i] for i in conflict.claim_ids if i in claims_by_id]
    shown = [c for c in members if visible_in_review(role, c)]
    return shown if len(shown) >= 2 else []
