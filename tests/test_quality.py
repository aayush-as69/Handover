"""The extraction-quality harness: it must score honestly, including bad extractors."""

import json
from pathlib import Path

from app.enums import ClaimType, SourceKind
from app.extract.base import ExtractorOutput
from app.extract.rules import RuleExtractor
from app.quality import EVAL_DIR, run_quality, to_markdown
from app.schemas import EvidenceIn, ExtractedClaim, ExtractionResult

GOLD = json.loads((EVAL_DIR / "gold.json").read_text(encoding="utf-8"))


def _line_with(chunks, word):
    for c in chunks:
        for line in c.text.splitlines():
            if word in line.lower():
                return c, line.strip()
    raise AssertionError(word)


class Scripted:
    """A pretend model that answers from a fixed script, so the scorer can be tested."""

    remote = False

    def __init__(self, name, plan):
        self.name, self.plan = name, plan

    def extract(self, chunks):
        claims = []
        for statement, ctype, word, fake_quote in self.plan:
            chunk, line = _line_with(chunks, word)
            claims.append(ExtractedClaim(
                statement=statement, type=ctype,
                evidence=[EvidenceIn(chunk_id=chunk.id, snippet=fake_quote or line)]))
        return ExtractorOutput(ExtractionResult(claims=claims), [])


def test_the_rule_extractor_baseline_is_stable_and_honest_about_chat():
    rep = run_quality(RuleExtractor())
    assert rep.by_source["chat"].found == 0 and rep.by_source["chat"].expected == 9
    assert rep.by_source["notes"].recall == 1.0 and rep.by_source["tasks"].recall == 1.0
    assert rep.overall.precision == 1.0
    assert "chat-sqlite" in rep.missed
    md = to_markdown(rep)
    assert "| chat | 9 | 0 | 0% |" in md and "rules-v1" in md


def test_a_good_model_is_credited_for_chat_claims_and_reasons():
    plan = [
        ("The kiosk catalogue uses SQLite because Postgres is overkill for 4k books", ClaimType.decision, "sqlite", None),
        ("Ana Rossi owns the late-fee rules", ClaimType.owner, "late-fee", None),
        ("Receipt printer driver only works on Windows 10, blocking the Ubuntu image", ClaimType.blocker, "printer", None),
    ]
    rep = run_quality(Scripted("script:good", plan))
    chat = rep.by_source["chat"]
    assert chat.found == 3 and chat.correct == 3 and chat.precision == 1.0
    assert rep.overall.reasons_kept == 1                       # the SQLite reason was kept
    assert "chat-sqlite" not in rep.missed and "chat-wifi" in rep.missed


def test_noise_lowers_precision_and_is_listed():
    plan = [
        ("The kiosk catalogue uses SQLite", ClaimType.decision, "sqlite", None),
        ("The team is having lunch", ClaimType.decision, "lunch", None),
        ("Someone wished everyone a happy Diwali", ClaimType.risk, "diwali", None),
    ]
    rep = run_quality(Scripted("script:noisy", plan))
    assert rep.by_source["chat"].produced == 3 and rep.by_source["chat"].correct == 1
    assert rep.overall.precision < 0.5
    assert any("lunch" in u for u in rep.unmatched)
    # A real quote does not make a claim worth keeping: at least one noise claim still reads as
    # quote-verified, which is why a person approves every claim.
    assert rep.verified_unmatched >= 1


def test_an_invented_quote_is_caught_by_verification_not_counted_as_verified():
    plan = [("Dev decided to adopt Kubernetes", ClaimType.decision, "sqlite",
             "we agreed to move everything to kubernetes next quarter")]
    rep = run_quality(Scripted("script:liar", plan))
    assert rep.quote_failures == 1
    assert rep.confidence.get("verified", 0) == 0
    assert rep.overall.correct == 0


def test_gold_set_is_self_consistent():
    ids = [e["id"] for e in GOLD["expected"]]
    assert len(ids) == len(set(ids))
    kinds = {s["kind"] for s in GOLD["sources"]}
    assert all(e["source"] in kinds for e in GOLD["expected"])
    for s in GOLD["sources"]:
        assert (Path(EVAL_DIR) / s["path"]).read_text(encoding="utf-8").strip()
        SourceKind(s["kind"])
