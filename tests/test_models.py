import pytest
from sqlalchemy.exc import IntegrityError

from app.enums import ChangeType, ClaimType, Confidence, ReviewStatus, SourceKind
from app.models import Chunk, Claim, Source

from .conftest import make_claim


def test_new_claim_is_unsupported_and_unreviewed_by_default(session, project):
    claim = Claim.create(project_id=project.id, statement="x is true", type=ClaimType.risk)
    session.add(claim)
    session.commit()
    assert claim.confidence == Confidence.unsupported
    assert claim.review_status == ReviewStatus.generated
    assert claim.version == 1
    assert [v.change_type for v in claim.versions] == [ChangeType.generated]


def test_version_history_records_every_change(session, project):
    claim = make_claim(session, project)
    claim.edit("Seat locks use Redis with a 30s timeout", by="Meera")
    claim.approve(by="Meera")
    claim.edit("Seat locks use Redis (timeout disabled)", by="Riya")
    claim.reject(by="Meera", note="superseded")
    session.commit()

    assert [v.change_type for v in claim.versions] == [
        ChangeType.generated, ChangeType.edit, ChangeType.approve,
        ChangeType.edit, ChangeType.reject,
    ]
    assert [v.version for v in claim.versions] == [1, 2, 3, 4, 5]
    assert claim.version == 5
    # Old wording stays recoverable.
    assert claim.versions[0].statement == "Seat locks use Redis"


def test_editing_an_approved_claim_requires_approval_again(session, project):
    claim = make_claim(session, project)
    claim.approve(by="Meera")
    assert claim.review_status == ReviewStatus.approved
    claim.edit("changed wording", by="Riya")
    assert claim.review_status == ReviewStatus.edited


def test_evidence_points_back_to_the_exact_chunk(session, project):
    claim = make_claim(session, project)
    ev = claim.evidence[0]
    assert ev.snippet in ev.chunk.text
    assert ev.chunk.source.kind == SourceKind.notes
    assert ev.snippet_verified is None  # nothing is checked until the verify step runs


def test_chunk_index_is_unique_within_a_source(session, project):
    source = Source(project_id=project.id, kind=SourceKind.chat, name="chat.txt")
    session.add(source)
    session.flush()
    session.add(Chunk(source_id=source.id, idx=0, text="a"))
    session.add(Chunk(source_id=source.id, idx=0, text="b"))
    with pytest.raises(IntegrityError):
        session.commit()
