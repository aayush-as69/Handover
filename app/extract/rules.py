"""Rule-based baseline extractor. Local, deterministic, needs no API key.

It reads only what is explicitly structured: note sections (Decisions, Risks, ...), task rows,
GitHub issues and pull requests, and commits whose own message says they are temporary or
unfinished. It does NOT interpret free text, so chat messages are skipped. Use an LLM extractor
to read chat. Every snippet it returns is copied verbatim from the chunk.
"""

from __future__ import annotations

import re
from typing import Optional, Sequence

from ..enums import ClaimType, SourceKind
from ..schemas import EvidenceIn, ExtractedClaim, ExtractionResult
from .base import ChunkView, ExtractorOutput

_SECTION_TYPES = {
    "decisions": ClaimType.decision,
    "open questions": ClaimType.open_question,
    "risks": ClaimType.risk,
    "dependencies": ClaimType.dependency,
    "contacts": ClaimType.contact,
    "next actions": ClaimType.next_action,
}
_BULLET = re.compile(r"^- .*(?:\n[ ]{2,}\S.*)*", re.M)
_OWNER_PREFIX = re.compile(r"^([A-Z][a-z]+(?: [A-Z][a-z]+)?): ")
_OWNER_SUFFIX = re.compile(r"\(([A-Z][a-z]+)\)\s*$")
_TASK = re.compile(
    r"^(?P<id>[^:|]+): (?P<title>.*?) \| owner: (?P<owner>.*?) \| status: (?P<status>.*?)"
    r" \| due: (?P<due>[^|]*?)(?: \| notes: (?P<notes>.*))?$",
    re.S,
)
_ISSUE = re.compile(r"^issue #(\d+) \[(\w+)\] (.*?): ", re.S)
_PULL = re.compile(r"^pull request #(\d+) \[(\w+)\] (.*?): ", re.S)
_COMMIT = re.compile(r"^commit (\w+) by (.*?): (.*?)(?:\. Files: .*)?$", re.S)
_UNFINISHED = re.compile(r"\b(temp|temporary|wip|hack|fixme|workaround|prototype|not wired)\b", re.I)


def _ev(chunk: ChunkView, snippet: str) -> list[EvidenceIn]:
    return [EvidenceIn(chunk_id=chunk.id, snippet=snippet[:500])]


def _norm(text: str) -> str:
    return " ".join(text.split())


def _section_type(chunk: ChunkView) -> Optional[ClaimType]:
    if " › " not in chunk.locator:
        return None
    heading = re.sub(r"\s*\(part \d+\)$", "", chunk.locator.split(" › ", 1)[1]).strip().lower()
    if heading.startswith("known fragile"):
        return ClaimType.risk
    return _SECTION_TYPES.get(heading)


def _from_notes(chunk: ChunkView) -> list[ExtractedClaim]:
    ctype = _section_type(chunk)
    if ctype is None:
        return []
    claims = []
    for m in _BULLET.finditer(chunk.text):
        raw = m.group()[2:]
        statement = _norm(raw)
        owner = None
        if ctype == ClaimType.next_action:
            mo = _OWNER_PREFIX.match(statement)
            owner = mo.group(1) if mo else None
        elif ctype == ClaimType.decision:
            mo = _OWNER_SUFFIX.search(statement)
            owner = mo.group(1) if mo else None
        claims.append(
            ExtractedClaim(statement=statement, type=ctype, owner=owner, evidence=_ev(chunk, raw))
        )
    return claims


def _from_task(chunk: ChunkView) -> list[ExtractedClaim]:
    m = _TASK.match(chunk.text)
    if not m:
        return []
    tid, title = m["id"].strip(), m["title"].strip()
    owner, status, due = m["owner"].strip(), m["status"].strip().lower(), m["due"].strip()
    notes = (m["notes"] or "").strip()
    named_owner = None if owner == "UNASSIGNED" else owner
    claims: list[ExtractedClaim] = []

    if owner == "UNASSIGNED" and status != "done":
        claims.append(ExtractedClaim(
            statement=f"Task {tid} ({title}) has no owner",
            type=ClaimType.owner,
            evidence=_ev(chunk, f"{tid}: {title} | owner: UNASSIGNED"),
        ))
    if status == "blocked":
        claims.append(ExtractedClaim(
            statement=f"Task {tid} ({title}) is blocked" + (f": {notes}" if notes else ""),
            type=ClaimType.blocker, owner=named_owner, evidence=_ev(chunk, chunk.text),
        ))
    elif status in ("in_progress", "todo") and named_owner:
        verb = "is working on" if status == "in_progress" else "still has to do"
        claims.append(ExtractedClaim(
            statement=f"{named_owner} {verb} task {tid} ({title}), due {due}"
            + (f". {notes}" if notes else ""),
            type=ClaimType.next_action, owner=named_owner, evidence=_ev(chunk, chunk.text),
        ))
    return claims


def _from_github(chunk: ChunkView) -> list[ExtractedClaim]:
    text = chunk.text
    if (m := _ISSUE.match(text)) and m[2] == "open":
        return [ExtractedClaim(
            statement=f"Open issue #{m[1]}: {m[3]}", type=ClaimType.risk,
            evidence=_ev(chunk, text[: m.end() - 2]),
        )]
    if (m := _PULL.match(text)) and m[2] == "open":
        return [ExtractedClaim(
            statement=f"Pull request #{m[1]} is still open: {m[3]}", type=ClaimType.next_action,
            evidence=_ev(chunk, text[: m.end() - 2]),
        )]
    if (m := _COMMIT.match(text)) and _UNFINISHED.search(m[3]):
        return [ExtractedClaim(
            statement=f"Commit {m[1]} is marked as temporary or unfinished: {m[3]}",
            type=ClaimType.risk, evidence=_ev(chunk, m[3]),
        )]
    return []


class RuleExtractor:
    name = "rules-v1"
    remote = False

    def extract(self, chunks: Sequence[ChunkView]) -> ExtractorOutput:
        claims: list[ExtractedClaim] = []
        skipped_chat = 0
        for chunk in chunks:
            if chunk.source_kind == SourceKind.notes:
                claims += _from_notes(chunk)
            elif chunk.source_kind == SourceKind.tasks:
                claims += _from_task(chunk)
            elif chunk.source_kind == SourceKind.github:
                claims += _from_github(chunk)
            elif chunk.source_kind == SourceKind.chat:
                skipped_chat += 1
        warnings = []
        if skipped_chat:
            warnings.append(
                f"{skipped_chat} chat messages were not interpreted: the rule-based extractor "
                "only reads structured sources. Use an LLM extractor to read chat."
            )
        return ExtractorOutput(ExtractionResult(claims=claims), warnings)
