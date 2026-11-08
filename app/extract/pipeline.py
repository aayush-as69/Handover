"""Run an extractor over a project's chunks and store the result as draft claims.

Guarantees:
* A remote extractor never sees confidential chunks unless the caller opts in.
* Evidence must point at a chunk the extractor was actually given. Anything else is dropped.
* A claim with no valid evidence is dropped, not stored.
* Re-running does not duplicate claims.
* Stored claims start as 'generated' / 'unsupported': nothing is trusted until verified and
  approved by a human.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..enums import SENSITIVITY_RANK, Sensitivity
from ..models import Chunk, Claim, Evidence, Project, Source
from .base import ChunkView, Extractor


@dataclass
class ExtractionReport:
    extractor: str
    claims_created: int = 0
    duplicates_skipped: int = 0
    dropped_no_evidence: int = 0
    dropped_unknown_chunk: int = 0
    chunks_sent: int = 0
    confidential_chunks_withheld: int = 0
    warnings: list[str] = field(default_factory=list)


def _higher(a: Sensitivity, b: Sensitivity) -> Sensitivity:
    return a if SENSITIVITY_RANK[a] >= SENSITIVITY_RANK[b] else b


def _key(claim_type, statement: str) -> tuple:
    return (claim_type, re.sub(r"\W+", " ", statement.lower()).strip())


def collect_chunks(
    session: Session, project: Project, *, allow_confidential: bool
) -> tuple[list[ChunkView], int]:
    rows = session.scalars(
        select(Chunk)
        .join(Source)
        .where(Source.project_id == project.id)
        .order_by(Source.id, Chunk.idx)
    ).all()
    views: list[ChunkView] = []
    withheld = 0
    for c in rows:
        level = _higher(c.sensitivity, c.source.sensitivity)
        if level == Sensitivity.confidential and not allow_confidential:
            withheld += 1
            continue
        views.append(
            ChunkView(
                id=c.id, source_name=c.source.name, source_kind=c.source.kind,
                locator=c.locator, author=c.author, occurred_at=c.occurred_at,
                text=c.text, sensitivity=level,
            )
        )
    return views, withheld


def run_extraction(
    session: Session,
    project: Project,
    extractor: Extractor,
    *,
    include_confidential: bool = False,
) -> ExtractionReport:
    report = ExtractionReport(extractor=extractor.name)
    allow = (not extractor.remote) or include_confidential
    views, report.confidential_chunks_withheld = collect_chunks(
        session, project, allow_confidential=allow
    )
    report.chunks_sent = len(views)
    if report.confidential_chunks_withheld:
        report.warnings.append(
            f"{report.confidential_chunks_withheld} confidential chunk(s) were not sent to "
            f"{extractor.name} because it is a remote extractor"
        )

    output = extractor.extract(views)   # may raise ExtractionError: nothing is written then
    report.warnings += output.warnings

    given = {v.id: v for v in views}
    # Query the database rather than project.claims, which can be a stale cached list.
    existing = session.execute(
        select(Claim.type, Claim.statement).where(Claim.project_id == project.id)
    ).all()
    seen = {_key(t, s) for t, s in existing}

    for ec in output.result.claims:
        evidence = [e for e in ec.evidence if e.chunk_id in given]
        report.dropped_unknown_chunk += len(ec.evidence) - len(evidence)
        if not evidence:
            report.dropped_no_evidence += 1
            continue
        key = _key(ec.type, ec.statement)
        if key in seen:
            report.duplicates_skipped += 1
            continue
        seen.add(key)

        level = Sensitivity.team
        for e in evidence:
            level = _higher(level, given[e.chunk_id].sensitivity)
        claim = Claim.create(
            project_id=project.id, statement=ec.statement.strip(), type=ec.type,
            created_by=extractor.name, topic=ec.topic, value=ec.value, owner=ec.owner,
            sensitivity=level,
        )
        for e in evidence:
            claim.evidence.append(
                Evidence(chunk_id=e.chunk_id, snippet=e.snippet.strip()[:500], stance=e.stance)
            )
        session.add(claim)
        report.claims_created += 1

    session.flush()
    return report
