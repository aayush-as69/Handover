"""The evaluations as a regression gate: if a change weakens a check, this fails."""

from app.extract.rules import RuleExtractor
from tests.evals import runner


def test_rules_engine_meets_every_gate():
    result = runner.run_all(RuleExtractor())
    assert runner.check(result) == []


def test_checks_hold_whatever_the_engine_does():
    """A model that invents claims from small talk fails the engine gates but not the safety ones."""
    class Inventor:
        name, remote = "inventor", False

        def extract(self, chunks):
            from app.extract.base import ExtractorOutput
            from app.schemas import EvidenceIn, ExtractedClaim, ExtractionResult
            return ExtractorOutput(ExtractionResult(claims=[ExtractedClaim(
                statement="The team decided to rewrite everything in Rust.", type="decision",
                evidence=[EvidenceIn(chunk_id=chunks[0].id, snippet="we agreed to rewrite everything in Rust")])]), [])

    result = runner.run_all(Inventor())
    assert result["hallucination"]["invented_from_empty"] > 0            # reported honestly
    assert result["hallucination"]["catch_rate"] == 1.0                  # but never trusted
    assert result["evidence_accuracy"]["false_verified"] == 0
    assert result["secret_leakage"]["leaks"] == 0
    assert runner.check(result) == []                                    # engine gates are rules-only
    result["engine"] = "rules-v1"
    assert any("invented_from_empty" in line for line in runner.check(result))


def test_a_secret_echoed_by_a_model_is_masked_and_reported():
    from sqlalchemy import select
    from app.enums import SourceKind
    from app.extract.pipeline import run_extraction
    from app.ingest.service import ingest_source
    from app.models import Claim
    case = runner.fixture("secret_leakage_cases")["model_echo"][0]
    with runner._session() as s:
        project = runner._project(s)
        ingest_source(s, project, kind=SourceKind(case["kind"]), name=case["name"], content=case["text"])
        report = run_extraction(s, project, runner.Scripted([case["claim"]]))
        statement = s.scalar(select(Claim.statement))
    assert case["secret"] not in statement and "[REDACTED" in statement
    assert report.secrets_masked >= 1 and any("masked" in w for w in report.warnings)
