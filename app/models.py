"""Database models.

The central idea: a claim is never just text. Every claim carries its evidence, a
confidence level, a sensitivity label, a review status and a full version history.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .enums import (
    ChangeType,
    ClaimType,
    Confidence,
    HandoverStatus,
    ReviewStatus,
    Role,
    Sensitivity,
    SourceKind,
    Stance,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _enum(e):
    return SAEnum(e, native_enum=False, validate_strings=True, length=32)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(128))
    role: Mapped[Role] = mapped_column(_enum(Role))
    password_hash: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    outgoing_member: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    sources: Mapped[list[Source]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    claims: Mapped[list[Claim]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    kind: Mapped[SourceKind] = mapped_column(_enum(SourceKind))
    name: Mapped[str] = mapped_column(String(300))
    origin: Mapped[str] = mapped_column(String(500), default="upload")
    sensitivity: Mapped[Sensitivity] = mapped_column(
        _enum(Sensitivity), default=Sensitivity.team
    )
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="sources")
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="source", cascade="all, delete-orphan", order_by="Chunk.idx"
    )


class Chunk(Base):
    """A dated, addressable piece of a source: a note section, a chat message, a commit."""

    __tablename__ = "chunks"
    __table_args__ = (UniqueConstraint("source_id", "idx"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    idx: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    # Human-readable pointer back to the original, e.g. "line 12" or "commit 7c2e8d1".
    locator: Mapped[str] = mapped_column(String(200), default="")
    author: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    occurred_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sensitivity: Mapped[Sensitivity] = mapped_column(
        _enum(Sensitivity), default=Sensitivity.team
    )
    # True when a secret was masked at ingestion. The raw secret is never stored.
    redacted: Mapped[bool] = mapped_column(Boolean, default=False)

    source: Mapped[Source] = relationship(back_populates="chunks")


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    statement: Mapped[str] = mapped_column(Text)
    type: Mapped[ClaimType] = mapped_column(_enum(ClaimType))
    # Topic/value let conflict detection group claims, e.g. topic="datastore", value="PostgreSQL".
    topic: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    value: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    owner: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # Honest default: nothing is verified until the verification pass says so.
    confidence: Mapped[Confidence] = mapped_column(
        _enum(Confidence), default=Confidence.unsupported
    )
    conflict_group: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    # Which extractor produced the claim (e.g. "rules-v1", "llm:gemini-2.0-flash").
    extractor: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    # Written by the verification pass, so a reviewer can see WHY a label was given.
    support_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    verification_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sensitivity: Mapped[Sensitivity] = mapped_column(
        _enum(Sensitivity), default=Sensitivity.team
    )
    review_status: Mapped[ReviewStatus] = mapped_column(
        _enum(ReviewStatus), default=ReviewStatus.generated
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="claims")
    evidence: Mapped[list[Evidence]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )
    versions: Mapped[list[ClaimVersion]] = relationship(
        back_populates="claim",
        cascade="all, delete-orphan",
        order_by="ClaimVersion.version",
    )

    @classmethod
    def create(
        cls,
        *,
        project_id: int,
        statement: str,
        type: ClaimType,
        created_by: str = "system",
        **fields,
    ) -> "Claim":
        claim = cls(project_id=project_id, statement=statement, type=type, version=1, **fields)
        claim.versions.append(
            ClaimVersion(
                version=1,
                statement=statement,
                type=type,
                change_type=ChangeType.generated,
                changed_by=created_by,
            )
        )
        return claim

    def _bump(self, change: ChangeType, by: str, status: ReviewStatus, note: str | None) -> None:
        self.version += 1
        self.review_status = status
        self.updated_at = utcnow()
        self.versions.append(
            ClaimVersion(
                version=self.version,
                statement=self.statement,
                type=self.type,
                change_type=change,
                changed_by=by,
                note=note,
            )
        )

    def edit(self, new_statement: str, by: str, note: str | None = None) -> None:
        """Any edit sends the claim back to 'edited': it must be approved again."""
        self.statement = new_statement
        self._bump(ChangeType.edit, by, ReviewStatus.edited, note)

    def approve(self, by: str, note: str | None = None) -> None:
        self._bump(ChangeType.approve, by, ReviewStatus.approved, note)

    def reject(self, by: str, note: str | None = None) -> None:
        self._bump(ChangeType.reject, by, ReviewStatus.rejected, note)


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"))
    chunk_id: Mapped[int] = mapped_column(ForeignKey("chunks.id"))
    # The exact text quoted from the chunk. The verification pass checks it really appears there.
    snippet: Mapped[str] = mapped_column(Text)
    stance: Mapped[Stance] = mapped_column(_enum(Stance), default=Stance.supports)
    # None = not checked yet, True = snippet found in chunk, False = snippet not found.
    snippet_verified: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    claim: Mapped[Claim] = relationship(back_populates="evidence")
    chunk: Mapped[Chunk] = relationship()


class ClaimVersion(Base):
    __tablename__ = "claim_versions"
    __table_args__ = (UniqueConstraint("claim_id", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"))
    version: Mapped[int] = mapped_column(Integer)
    statement: Mapped[str] = mapped_column(Text)
    type: Mapped[ClaimType] = mapped_column(_enum(ClaimType))
    change_type: Mapped[ChangeType] = mapped_column(_enum(ChangeType))
    changed_by: Mapped[str] = mapped_column(String(128))
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    claim: Mapped[Claim] = relationship(back_populates="versions")


class Handover(Base):
    __tablename__ = "handovers"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    title: Mapped[str] = mapped_column(String(200))
    outgoing_name: Mapped[str] = mapped_column(String(128))
    incoming_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    status: Mapped[HandoverStatus] = mapped_column(
        _enum(HandoverStatus), default=HandoverStatus.draft
    )
    approved_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Acknowledgement(Base):
    __tablename__ = "acknowledgements"
    __table_args__ = (UniqueConstraint("handover_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    handover_id: Mapped[int] = mapped_column(ForeignKey("handovers.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
