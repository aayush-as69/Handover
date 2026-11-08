"""Ingestion service: parse, mask secrets, store.

Order matters. A source is fully parsed BEFORE anything is written, so a bad file leaves no
half-ingested source behind. Secrets are masked BEFORE chunks are stored, so a raw secret
never reaches the database.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..enums import SENSITIVITY_RANK, Sensitivity, SourceKind
from ..models import Chunk, Project, Source
from .errors import IngestError
from .github import fetch_public_repo
from .parsers import PARSERS
from .redact import redact

MAX_BYTES = 2_000_000


@dataclass
class IngestResult:
    source: Source
    chunk_count: int
    redacted_chunks: int
    warnings: list[str] = field(default_factory=list)
    duplicate: bool = False


def decode_upload(data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise IngestError(f"the file is larger than {MAX_BYTES // 1_000_000} MB")
    if b"\x00" in data:
        raise IngestError("the file looks binary; upload a text file")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise IngestError("the file is not valid UTF-8 text")


def _higher(a: Sensitivity, b: Sensitivity) -> Sensitivity:
    return a if SENSITIVITY_RANK[a] >= SENSITIVITY_RANK[b] else b


def ingest_source(
    session: Session,
    project: Project,
    *,
    kind: SourceKind,
    name: str,
    content: str,
    sensitivity: Sensitivity = Sensitivity.team,
    origin: str = "upload",
) -> IngestResult:
    if not content.strip():
        raise IngestError("the source is empty")
    if len(content.encode("utf-8")) > MAX_BYTES:
        raise IngestError(f"the source is larger than {MAX_BYTES // 1_000_000} MB")

    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    existing = session.scalar(
        select(Source).where(Source.project_id == project.id, Source.content_hash == digest)
    )
    if existing is not None:
        return IngestResult(existing, len(existing.chunks),
                            sum(c.redacted for c in existing.chunks), duplicate=True)

    parsed = PARSERS[kind](content, name)  # raises IngestError before anything is written

    source = Source(
        project_id=project.id, kind=kind, name=name, origin=origin,
        sensitivity=sensitivity, content_hash=digest,
    )
    redacted_count = 0
    for idx, pc in enumerate(parsed.chunks):
        masked = redact(pc.text)
        if masked.redacted:
            redacted_count += 1
        source.chunks.append(
            Chunk(
                idx=idx,
                text=masked.text,
                locator=pc.locator,
                author=pc.author,
                occurred_at=pc.occurred_at,
                # A message that contained a secret is confidential, whatever its source says.
                sensitivity=_higher(
                    sensitivity, Sensitivity.confidential if masked.redacted else sensitivity
                ),
                redacted=masked.redacted,
            )
        )
    try:
        # A savepoint, so losing a race to an identical upload undoes only this insert.
        with session.begin_nested():
            session.add(source)
    except IntegrityError:
        existing = session.scalar(
            select(Source).where(Source.project_id == project.id, Source.content_hash == digest))
        if existing is None:
            raise
        return IngestResult(existing, len(existing.chunks),
                            sum(c.redacted for c in existing.chunks), duplicate=True)
    return IngestResult(source, len(source.chunks), redacted_count, parsed.warnings)


def ingest_github_repo(
    session: Session,
    project: Project,
    owner: str,
    repo: str,
    *,
    client: httpx.Client | None = None,
) -> IngestResult:
    snapshot = fetch_public_repo(owner, repo, client=client)
    return ingest_source(
        session,
        project,
        kind=SourceKind.github,
        name=f"{owner}/{repo}",
        content=json.dumps(snapshot),
        sensitivity=Sensitivity.public,
        origin=f"https://github.com/{owner}/{repo}",
    )
