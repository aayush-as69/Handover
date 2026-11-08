import pytest
from sqlalchemy import select

from app.enums import ClaimType, Confidence, ReviewStatus, Sensitivity, SourceKind, Stance
from app.extract import ExtractorOutput
from app.extract.pipeline import run_extraction
from app.extract.rules import RuleExtractor
from app.models import Chunk, Claim, Evidence, Source
from app.schemas import EvidenceIn, ExtractedClaim, ExtractionResult
from app.verify import snippet_in_text, verify_claim, verify_claims, verify_project


# ------------------------------------------------------------ the quote check


@pytest.mark.parametrize("snippet,text,expected", [
    ("Seat locks will go in Redis", "## Decisions\n- Seat locks will go in Redis. (Riya)", True),
    # layout differences change no words
    ("Payments move to Kabir after the handover.",
     "- Payments move to Kabir\n  after the handover.", True),
    ("Payments move to Kabir\n  after the handover.",
     "- Payments move to Kabir after the handover.", True),
    # typography
    ("it’s temporary, I’ll move it", "it's temporary, I'll move it to postgres", True),
    ('"Seat locks will go in Redis"', "Seat locks will go in Redis.", True),
    # skipping text with an ellipsis, in order
    ("Seat locks ... in Redis", "Seat locks will go in Redis", True),
    ("in Redis ... Seat locks", "Seat locks will go in Redis", False),
    ("Seat locks will go in Redis…", "Seat locks will go in Redis. (Riya)", True),
    # real differences are not tolerated
    ("Locks are stored in Redis", "Seat locks will go in Redis", False),
    ("seat locks will go in redis", "Seat locks will go in Redis", False),   # case matters
    ("Seat locks will go in Mongo", "Seat locks will go in Redis", False),
    # too short to mean anything, unless it is the whole chunk
    ("Redis", "Seat locks will go in Redis", False),
    ("Redis", "Redis", True),
    ("", "anything", False),
    ("   ", "anything", False),
])
def test_quote_check(snippet, text, expected):
    assert snippet_in_text(snippet, text) is expected


# ------------------------------------------------------------ labels


def claim_with(session, project, statement, chunk_text, snippet, *, stance=Stance.supports,
               extractor=None, extra=()):
    source = Source(project_id=project.id, kind=SourceKind.notes, name="n.md")
    chunk = Chunk(source=source, idx=0, text=chunk_text, locator="n.md › Decisions")
    claim = Claim.create(project_id=project.id, statement=statement, type=ClaimType.decision,
                         extractor=extractor)
    claim.evidence.append(Evidence(chunk=chunk, snippet=snippet, stance=stance))
    for snip, st in extra:
        claim.evidence.append(Evidence(chunk=chunk, snippet=snip, stance=st))
    session.add_all([source, chunk, claim])
    session.flush()
    return claim


def test_a_matching_quote_makes_a_claim_verified(session, project):
    c = claim_with(session, project, "Seat locks will go in Redis",
                   "## Decisions\n- Seat locks will go in Redis. (Riya)", "Seat locks will go in Redis")
    assert verify_claim(c) == Confidence.verified
    assert c.support_score == 1.0
    assert c.evidence[0].snippet_verified is True
    assert c.verified_at is not None and "found word for word" in c.verification_note


def test_an_invented_quote_makes_a_claim_unsupported(session, project):
    c = claim_with(session, project, "Seat locks are stored in Redis",
                   "Seat locks will go in Redis", "Locks are stored in Redis")
    assert verify_claim(c) == Confidence.unsupported
    assert c.evidence[0].snippet_verified is False
    assert "word for word" in c.verification_note


def test_no_evidence_at_all_is_unsupported(session, project):
    c = Claim.create(project_id=project.id, statement="Something is true", type=ClaimType.risk)
    session.add(c)
    session.flush()
    assert verify_claim(c) == Confidence.unsupported
    assert c.verification_note == "No evidence is attached."


@pytest.mark.parametrize("statement,why", [
    ("Seat locks use Redis with a 30 second timeout", "30"),            # invented number
    ("Seat locks will not go in Redis", "negation"),                    # flipped meaning
    ("Kabir approved moving everything to Kubernetes", "key terms"),    # drifted far away
])
def test_a_claim_that_says_more_than_its_quote_is_only_inferred(session, project, statement, why):
    c = claim_with(session, project, statement, "Seat locks will go in Redis",
                   "Seat locks will go in Redis")
    assert verify_claim(c) == Confidence.inferred
    assert why in c.verification_note


def test_an_invented_date_is_caught_even_when_the_words_match(session, project):
    c = claim_with(session, project, "Riya writes the setup doc by 2026-11-18",
                   "Riya: write the setup doc.", "Riya: write the setup doc.")
    assert verify_claim(c) == Confidence.inferred
    assert "2026" in c.verification_note and "18" in c.verification_note


def test_a_verified_quote_that_contradicts_makes_the_claim_conflicting(session, project):
    c = claim_with(
        session, project, "PostgreSQL is the only datastore",
        "PostgreSQL is the only datastore. [later] added a mongo event feed prototype",
        "PostgreSQL is the only datastore",
        extra=[("added a mongo event feed prototype", Stance.contradicts)],
    )
    assert verify_claim(c) == Confidence.conflicting
    assert "contradict" in c.verification_note


def test_a_contradicting_quote_that_cannot_be_found_does_not_count(session, project):
    c = claim_with(session, project, "PostgreSQL is the only datastore",
                   "PostgreSQL is the only datastore", "PostgreSQL is the only datastore",
                   extra=[("a quote nobody ever wrote", Stance.contradicts)])
    assert verify_claim(c) == Confidence.verified
    assert "1 other quote(s) could not be found" in c.verification_note


def test_rule_built_claims_need_only_a_real_quote(session, project):
    c = claim_with(session, project, "Task T7 (QR check-in at the venue) has no owner",
                   "T7: QR check-in at the venue | owner: UNASSIGNED | status: todo",
                   "T7: QR check-in at the venue | owner: UNASSIGNED", extractor="rules-v1")
    assert verify_claim(c) == Confidence.verified
    assert "mechanically" in c.verification_note


def test_a_human_edit_ends_the_mechanical_free_pass(session, project):
    c = claim_with(session, project, "Task T7 (QR check-in at the venue) has no owner",
                   "T7: QR check-in at the venue | owner: UNASSIGNED | status: todo",
                   "T7: QR check-in at the venue | owner: UNASSIGNED", extractor="rules-v1")
    c.edit("Task T7 is owned by Kabir since 2026-11-09", by="Meera")
    assert verify_claim(c) == Confidence.inferred


def test_verifying_changes_the_label_but_never_the_review_status(session, project):
    c = claim_with(session, project, "Seat locks will go in Redis",
                   "Seat locks will go in Redis", "Seat locks will go in Redis")
    c.approve(by="Meera")
    verify_claim(c)
    verify_claim(c)                                  # safe to repeat
    assert c.review_status == ReviewStatus.approved and c.confidence == Confidence.verified
    c.evidence[0].snippet = "this was tampered with later"
    assert verify_claim(c) == Confidence.unsupported
    assert c.review_status == ReviewStatus.approved  # a human still decides what to do about it


def test_verify_project_relabels_every_claim(session, project):
    claim_with(session, project, "Seat locks will go in Redis", "Seat locks will go in Redis",
               "Seat locks will go in Redis")
    claim_with(session, project, "Totally different claim", "Seat locks will go in Redis",
               "this quote does not exist anywhere")
    report = verify_project(session, project)
    assert report.counts == {"verified": 1, "unsupported": 1}
    assert report.snippets_checked == 2 and report.snippets_failed == 1


# ------------------------------------------------------------ through the pipeline


def test_every_rule_extracted_claim_on_the_demo_is_verified(session, demo_project):
    report = run_extraction(session, demo_project, RuleExtractor())
    session.commit()
    assert report.confidence_counts == {"verified": report.claims_created}
    assert report.snippets_failed == 0
    for c in session.scalars(select(Claim)).all():
        assert c.extractor == "rules-v1" and c.verified_at is not None
        assert all(e.snippet_verified is True for e in c.evidence)


class FakeModel:
    name, remote = "fake-llm", True

    def __init__(self, claims):
        self.claims = claims

    def extract(self, chunks):
        return ExtractorOutput(ExtractionResult(claims=self.claims))


def test_a_model_cannot_pass_off_invented_quotes_as_evidence(session, demo_project):
    chunk = session.scalars(select(Chunk).where(Chunk.text.contains("PostgreSQL is the only"))).one()
    ev = lambda snip: [EvidenceIn(chunk_id=chunk.id, snippet=snip)]
    model = FakeModel([
        ExtractedClaim(statement="PostgreSQL is the only datastore", type=ClaimType.decision,
                       evidence=ev("PostgreSQL is the only datastore")),
        ExtractedClaim(statement="The team picked MongoDB for speed", type=ClaimType.decision,
                       evidence=ev("We chose MongoDB because it is faster")),       # invented
        ExtractedClaim(statement="Postgres was chosen for transactions", type=ClaimType.decision,
                       evidence=ev("Postgres was chosen for its transactions")),    # paraphrase
    ])
    report = run_extraction(session, demo_project, model)
    session.commit()
    assert report.confidence_counts == {"verified": 1, "unsupported": 2}
    assert report.snippets_failed == 2
    assert any("could not be found" in w for w in report.warnings)
    by_statement = {c.statement: c for c in session.scalars(select(Claim)).all()}
    assert by_statement["PostgreSQL is the only datastore"].confidence == Confidence.verified
    assert by_statement["The team picked MongoDB for speed"].confidence == Confidence.unsupported
    # nothing is approved automatically, whatever the label
    assert {c.review_status for c in by_statement.values()} == {ReviewStatus.generated}
