"""Database models.

The central idea: a claim is never just text. Every claim carries its evidence, a
confidence level, a sensitivity label, a review status and a full version history.
"""

from __future__ import annotations

import json
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
    event,
    inspect as sa_inspect,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .enums import (
    ChangeType,
    ClaimType,
    Confidence,
    ConflictStatus,
    HandoverStatus,
    QuestionStatus,
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
    # Incremented whenever credentials are rotated; older signed cookies then become invalid.
    session_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)


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


class ProjectMember(Base):
    """Who may work in a project. Admins reach every project; everyone else needs a row here."""

    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    added_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # The role this person has in this project. None means "use their default role".
    role: Mapped[Optional[Role]] = mapped_column(_enum(Role), nullable=True)


class Source(Base):
    __tablename__ = "sources"
    # Two simultaneous uploads of the same content cannot both be stored.
    __table_args__ = (UniqueConstraint("project_id", "content_hash"),)

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
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
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

    source: Mapped[Source] = relationship(back_populates="chunks", lazy="selectin")


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
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
    # Optional advisory second opinion from a model (see app/semantic.py). It can only add a
    # warning for the reviewer; it never changes the confidence label.
    semantic_verdict: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    semantic_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sensitivity: Mapped[Sensitivity] = mapped_column(
        _enum(Sensitivity), default=Sensitivity.team
    )
    review_status: Mapped[ReviewStatus] = mapped_column(
        _enum(ReviewStatus), default=ReviewStatus.generated, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    # Optimistic locking: every write says "only if nobody changed it since I read it".
    # We bump `version` ourselves (one version per recorded change), so SQLAlchemy must not.
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="claims")
    evidence: Mapped[list[Evidence]] = relationship(
        back_populates="claim", cascade="all, delete-orphan", lazy="selectin"
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(
        cascade="save-update", order_by="AuditEvent.id"
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
        claim.versions.append(claim._version_row(1, ChangeType.generated, created_by, None,
                                                 ReviewStatus.generated))
        return claim

    def evidence_snapshot(self) -> str:
        return json.dumps([
            {"chunk_id": e.chunk_id if e.chunk_id is not None else getattr(e.chunk, "id", None),
             "snippet": e.snippet, "stance": e.stance.value if e.stance else "supports",
             "verified": e.snippet_verified}
            for e in self.evidence
        ])

    def _version_row(self, version: int, change: ChangeType, by: str, note: str | None,
                     status: ReviewStatus) -> "ClaimVersion":
        return ClaimVersion(
            version=version, statement=self.statement, type=self.type, change_type=change,
            changed_by=by, note=note, review_status=status.value,
            confidence=(self.confidence or Confidence.unsupported).value,
            sensitivity=(self.sensitivity or Sensitivity.team).value,
            evidence_json=self.evidence_snapshot(),
        )

    def _bump(self, change: ChangeType, by: str, status: ReviewStatus, note: str | None) -> None:
        self.version += 1
        self.review_status = status
        self.updated_at = utcnow()
        self.versions.append(self._version_row(self.version, change, by, note, status))

    def edit(self, new_statement: str, by: str, note: str | None = None) -> None:
        """Any edit sends the claim back to 'edited': it must be approved again."""
        self.statement = new_statement
        self.semantic_verdict = self.semantic_note = None     # the old opinion was about old words
        self._bump(ChangeType.edit, by, ReviewStatus.edited, note)

    def set_sensitivity(self, sensitivity: Sensitivity, by: str,
                        note: str | None = None) -> bool:
        """Record a sensitivity change as a reviewable claim revision."""
        if self.sensitivity == sensitivity:
            return False
        self.sensitivity = sensitivity
        self._bump(ChangeType.edit, by, ReviewStatus.edited, note or "Sensitivity changed")
        return True

    def approve(self, by: str, note: str | None = None) -> None:
        self._bump(ChangeType.approve, by, ReviewStatus.approved, note)

    def reject(self, by: str, note: str | None = None) -> None:
        self._bump(ChangeType.reject, by, ReviewStatus.rejected, note)

    def reopen(self, by: str, note: str | None = None) -> None:
        """Send a decided claim back to the queue (it leaves any handover until approved again)."""
        self._bump(ChangeType.reopen, by, ReviewStatus.generated, note)


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), index=True)
    chunk_id: Mapped[int] = mapped_column(ForeignKey("chunks.id"), index=True)
    # The exact text quoted from the chunk. The verification pass checks it really appears there.
    snippet: Mapped[str] = mapped_column(Text)
    stance: Mapped[Stance] = mapped_column(_enum(Stance), default=Stance.supports)
    # None = not checked yet, True = snippet found in chunk, False = snippet not found.
    snippet_verified: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    claim: Mapped[Claim] = relationship(back_populates="evidence")
    chunk: Mapped[Chunk] = relationship(lazy="selectin")


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
    # The claim's full state as it was after this change. Append-only: see the guards below.
    review_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    confidence: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    sensitivity: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    evidence_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    claim: Mapped[Claim] = relationship(back_populates="versions")


class Handover(Base):
    """One per project (enforced). Its signed-off snapshots are HandoverRelease rows."""

    __tablename__ = "handovers"
    __table_args__ = (UniqueConstraint("project_id"),)

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


class HandoverRelease(Base):
    """An immutable sign-off: which claims, at which versions, who approved and when.

    The claim text itself is not copied. Claim versions are append-only, so
    (claim id, version) names exactly what was signed off.
    """

    __tablename__ = "handover_releases"
    __table_args__ = (UniqueConstraint("handover_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    handover_id: Mapped[int] = mapped_column(ForeignKey("handovers.id"))
    number: Mapped[int] = mapped_column(Integer)
    approved_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_by_name: Mapped[str] = mapped_column(String(128))
    approved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    claims_json: Mapped[str] = mapped_column(Text)        # [[claim_id, version], ...]

    @property
    def entries(self) -> list[tuple[int, int]]:
        return [(int(a), int(b)) for a, b in json.loads(self.claims_json)]


class Acknowledgement(Base):
    """A person confirming they read one specific release."""

    __tablename__ = "acknowledgements"
    __table_args__ = (UniqueConstraint("release_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("handover_releases.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


def _ids(csv: str) -> list[int]:
    return [int(x) for x in csv.split(",") if x]


class Conflict(Base):
    """Claims whose sources disagree. Detected mechanically; a person resolves it."""

    __tablename__ = "conflicts"
    __table_args__ = (UniqueConstraint("project_id", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    key: Mapped[str] = mapped_column(String(160))
    topic: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(Text)
    claim_csv: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ConflictStatus] = mapped_column(_enum(ConflictStatus),
                                                   default=ConflictStatus.open)
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    @property
    def claim_ids(self) -> list[int]:
        return _ids(self.claim_csv)


class Question(Base):
    """A gap the outgoing person should fill before leaving ("Questions Before I Leave")."""

    __tablename__ = "questions"
    __table_args__ = (UniqueConstraint("project_id", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    key: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    claim_csv: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[QuestionStatus] = mapped_column(_enum(QuestionStatus),
                                                   default=QuestionStatus.open)
    answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    answered_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    @property
    def claim_ids(self) -> list[int]:
        return _ids(self.claim_csv)


class AuditEvent(Base):
    """Append-only record of events that are not content edits (verification results...)."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    actor: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text)             # JSON


class LoginAttempt(Base):
    """A failed sign-in, kept in the database so lockouts survive restarts and many workers."""

    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# ---------------------------------------------------------------- append-only guards


class ImmutableError(RuntimeError):
    """Raised when code tries to change or delete a record that must never change."""


def _forbid(mapper, connection, target):
    raise ImmutableError(f"{type(target).__name__} records are append-only")


for _model in (ClaimVersion, AuditEvent, HandoverRelease):
    event.listen(_model, "before_update", _forbid)
    event.listen(_model, "before_delete", _forbid)


def _evidence_guard(mapper, connection, target):
    state = sa_inspect(target)
    for attr in ("claim_id", "chunk_id", "snippet", "stance"):
        if state.attrs[attr].history.has_changes():
            raise ImmutableError(f"evidence {attr} cannot change after it is stored")


event.listen(Evidence, "before_update", _evidence_guard)
event.listen(Evidence, "before_delete", _forbid)


class Job(Base):
    """A slow task run in the background, so a web request does not have to wait for it.

    Runs inside the web process on a worker thread. It does not survive a restart: a job
    still queued or running at startup is marked failed rather than left looking busy.
    """

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))               # "extract_llm"
    status: Mapped[str] = mapped_column(String(16), default="queued")   # queued|running|done|failed
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    chunks_total: Mapped[int] = mapped_column(Integer, default=0)
    claims_created: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")


class Team(Base):
    """A named group of people, so a whole team can be added to a project in one step.

    Adding a team copies its current members into the project. It is not a live link: people
    added to the team later are not added to the project automatically.
    """

    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)


class OnboardingStep(Base):
    """A topic of the guided takeover that a person confirmed they have read.

    Tied to the release they read, so a newer release starts the walkthrough again.
    """

    __tablename__ = "onboarding_steps"
    __table_args__ = (UniqueConstraint("user_id", "project_id", "release_number", "step_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    release_number: Mapped[int] = mapped_column(Integer, default=0)    # 0 = unsigned draft
    step_key: Mapped[str] = mapped_column(String(32))
    done_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ClaimComment(Base):
    """A reviewer's discussion note on a claim. Separate from the approval note."""

    __tablename__ = "claim_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), index=True)
    author: Mapped[str] = mapped_column(String(128))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
