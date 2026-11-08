"""Parsers: raw text -> dated, addressable chunks.

Every chunk keeps a human-readable locator (a section, a chat line, a commit) so a citation
can always point back to the exact place in the original.

Dates are naive and treated as UTC. Chat dates are read as day/month/year unless the file
clearly uses month/day/year.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from ..enums import SourceKind
from .errors import IngestError

MAX_CHUNK_CHARS = 1500


@dataclass
class ParsedChunk:
    text: str
    locator: str
    author: Optional[str] = None
    occurred_at: Optional[datetime] = None


@dataclass
class ParseResult:
    chunks: list[ParsedChunk]
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- notes


_DATE = re.compile(r"\bDate:\s*(\d{4})-(\d{2})-(\d{2})")


def _split_long(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    cur = ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        while len(para) > limit:
            cut = para.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(para[:cut].strip())
            para = para[cut:].strip()
        if not para:
            continue
        if cur and len(cur) + 2 + len(para) > limit:
            parts.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        parts.append(cur)
    return parts


def parse_notes(text: str, name: str) -> ParseResult:
    warnings: list[str] = []
    when = None
    m = _DATE.search(text)
    if m:
        try:
            when = datetime(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            warnings.append("the 'Date:' line is not a valid date; chunks have no timestamp")

    sections: list[tuple[str, list[str]]] = []
    heading = "Overview"
    buf: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            sections.append((heading, buf))
            heading, buf = line[3:].strip(), [line]
        else:
            if line.startswith("# ") and not sections and not any(b.strip() for b in buf):
                heading = line[2:].strip()
            buf.append(line)
    sections.append((heading, buf))

    chunks: list[ParsedChunk] = []
    for heading, lines in sections:
        body = "\n".join(lines).strip()
        if not body:
            continue
        pieces = _split_long(body)
        for i, piece in enumerate(pieces):
            suffix = f" (part {i + 1})" if len(pieces) > 1 else ""
            chunks.append(
                ParsedChunk(text=piece, locator=f"{name} › {heading}{suffix}", occurred_at=when)
            )
    if not chunks:
        raise IngestError("the notes file contains no readable text")
    return ParseResult(chunks, warnings)


# ---------------------------------------------------------------- chat


_CHAT = re.compile(
    r"^\[(\d{1,2})/(\d{1,2})/(\d{4}),\s*(\d{1,2}):(\d{2})\]\s*([^:]{1,80}):\s?(.*)$"
)


def parse_chat(text: str, name: str) -> ParseResult:
    warnings: list[str] = []
    msgs: list[dict] = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        m = _CHAT.match(line)
        if m:
            msgs.append(
                {
                    "n": n,
                    "nums": tuple(int(x) for x in m.groups()[:5]) + (int(m[3]),),
                    "a": int(m[1]),
                    "b": int(m[2]),
                    "year": int(m[3]),
                    "hour": int(m[4]),
                    "minute": int(m[5]),
                    "author": m[6].strip(),
                    "text": m[7],
                }
            )
        elif msgs:
            msgs[-1]["text"] += "\n" + line.strip()  # a message that spans several lines
        else:
            warnings.append(f"line {n}: skipped, it is not part of a message")

    if not msgs:
        raise IngestError(
            "no chat messages recognised (expected lines like "
            "'[dd/mm/yyyy, hh:mm] Name: message')"
        )

    # dd/mm by default; switch to mm/dd only when the file proves it.
    month_first = any(m["b"] > 12 for m in msgs) and not any(m["a"] > 12 for m in msgs)

    chunks: list[ParsedChunk] = []
    for m in msgs:
        day, month = (m["b"], m["a"]) if month_first else (m["a"], m["b"])
        try:
            when: Optional[datetime] = datetime(m["year"], month, day, m["hour"], m["minute"])
        except ValueError:
            when = None
            warnings.append(f"line {m['n']}: invalid date or time, kept without a timestamp")
        chunks.append(
            ParsedChunk(
                text=m["text"], locator=f"{name} line {m['n']}", author=m["author"],
                occurred_at=when,
            )
        )
    return ParseResult(chunks, warnings)


# ---------------------------------------------------------------- tasks


def parse_tasks(text: str, name: str) -> ParseResult:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise IngestError("the task file has no header row")
    fields = {f.strip().lower(): f for f in reader.fieldnames if f}
    missing = {"id", "title"} - set(fields)
    if missing:
        raise IngestError(f"the task file is missing required column(s): {', '.join(sorted(missing))}")

    def get(row: dict, key: str) -> str:
        col = fields.get(key)
        return (row.get(col) or "").strip() if col else ""

    warnings: list[str] = []
    seen: set[str] = set()
    chunks: list[ParsedChunk] = []
    for n, row in enumerate(reader, 2):  # row 1 is the header
        if not any((v or "").strip() for v in row.values() if not isinstance(v, list)):
            continue
        task_id = get(row, "id")
        if task_id in seen:
            warnings.append(f"row {n}: duplicate task id {task_id}")
        seen.add(task_id)
        owner = get(row, "owner") or "UNASSIGNED"
        line = (
            f"{task_id}: {get(row, 'title')} | owner: {owner} | status: {get(row, 'status') or 'unknown'}"
            f" | due: {get(row, 'due') or 'none'}"
        )
        if get(row, "notes"):
            line += f" | notes: {get(row, 'notes')}"
        chunks.append(ParsedChunk(text=line, locator=f"{name} row {n} ({task_id})"))
    if not chunks:
        raise IngestError("the task file has no task rows")
    return ParseResult(chunks, warnings)


# ---------------------------------------------------------------- github


def _iso(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            timezone.utc
        ).replace(tzinfo=None)
    except ValueError:
        return None


def parse_github(text: str, name: str) -> ParseResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise IngestError("the GitHub file is not valid JSON")
    if not isinstance(data, dict) or not any(
        isinstance(data.get(k), list) for k in ("commits", "issues", "pulls")
    ):
        raise IngestError("the GitHub file needs at least one of: commits, issues, pulls")

    items: list[tuple[Optional[datetime], int, ParsedChunk]] = []
    for c in data.get("commits") or []:
        files = ", ".join(c.get("files") or [])
        body = f"commit {c.get('sha', '?')} by {c.get('author', 'unknown')}: {c.get('message', '')}"
        if files:
            body += f". Files: {files}"
        when = _iso(c.get("date"))
        items.append((when, 0, ParsedChunk(body, f"commit {c.get('sha', '?')}", c.get("author"), when)))
    for i in data.get("issues") or []:
        assignees = ", ".join(i.get("assignees") or []) or "none"
        body = (
            f"issue #{i.get('number')} [{i.get('state', '?')}] {i.get('title', '')}: {i.get('body', '')}"
            f" Opened by {i.get('author', 'unknown')}. Assignees: {assignees}."
        )
        when = _iso(i.get("created"))
        items.append((when, 1, ParsedChunk(body, f"issue #{i.get('number')}", i.get("author"), when)))
    for p in data.get("pulls") or []:
        body = (
            f"pull request #{p.get('number')} [{p.get('state', '?')}] {p.get('title', '')}: "
            f"{p.get('body', '')} Opened by {p.get('author', 'unknown')}."
        )
        when = _iso(p.get("created"))
        items.append((when, 2, ParsedChunk(body, f"pull request #{p.get('number')}", p.get("author"), when)))

    if not items:
        raise IngestError("the GitHub file contains no commits, issues or pull requests")
    items.sort(key=lambda t: (t[0] or datetime.min, t[1]))
    return ParseResult([c for _, _, c in items], [])


PARSERS: dict[SourceKind, Callable[[str, str], ParseResult]] = {
    SourceKind.notes: parse_notes,
    SourceKind.chat: parse_chat,
    SourceKind.tasks: parse_tasks,
    SourceKind.github: parse_github,
}
