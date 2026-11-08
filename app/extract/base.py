from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Protocol, Sequence

from ..enums import Sensitivity, SourceKind
from ..schemas import ExtractionResult


class ExtractionError(RuntimeError):
    """The extractor could not do its job. The message is safe to show to the user."""


@dataclass(frozen=True)
class ChunkView:
    """What an extractor sees of a chunk. Deliberately independent of the database."""

    id: int
    source_name: str
    source_kind: SourceKind
    locator: str
    author: Optional[str]
    occurred_at: Optional[datetime]
    text: str
    sensitivity: Sensitivity


@dataclass
class ExtractorOutput:
    result: ExtractionResult
    warnings: list[str] = field(default_factory=list)


class Extractor(Protocol):
    name: str
    # A remote extractor sends text to a third party. By default it never sees confidential
    # chunks. A local extractor runs on this server, so nothing leaves it.
    remote: bool

    def extract(self, chunks: Sequence[ChunkView]) -> ExtractorOutput: ...
