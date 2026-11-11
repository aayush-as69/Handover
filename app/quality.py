"""Measure how well an extractor reads a labelled set of source files.

A small synthetic project (data/eval) comes with a list of claims a careful reader should
find. An extractor is run over it in a throwaway database and its output is scored:

* recall     - how many of the expected claims were found
* precision  - how many of the claims it produced match an expected one
* reason recall - for decisions, how often the stated reason was kept
* verified_unmatched - claims the mechanical check labelled "quote-verified" that match no
  expected claim. Verification proves a quote exists, not that the claim matters, so this
  number shows how much a human still has to filter.

Matching is by claim type and key words, so it rewards what was found, not exact wording.
Usage:
    python -m app.quality --engine rules
    LLM_BASE_URL=... LLM_API_KEY=... LLM_MODEL=... python -m app.quality --engine llm
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from .enums import Confidence, Sensitivity, SourceKind
from .extract.pipeline import run_extraction
from .ingest.service import ingest_source
from .models import Base, Claim, Project

EVAL_DIR = Path(__file__).resolve().parents[1] / "data" / "eval"


@dataclass
class Score:
    expected: int = 0
    found: int = 0
    produced: int = 0
    correct: int = 0
    reasons_expected: int = 0
    reasons_kept: int = 0

    @property
    def recall(self) -> float:
        return self.found / self.expected if self.expected else 0.0

    @property
    def precision(self) -> float:
        return self.correct / self.produced if self.produced else 0.0


@dataclass
class QualityReport:
    engine: str
    overall: Score = field(default_factory=Score)
    by_source: dict[str, Score] = field(default_factory=dict)
    missed: list[str] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    confidence: dict[str, int] = field(default_factory=dict)
    verified_unmatched: int = 0
    quote_failures: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        def sc(s: Score) -> dict:
            return {"expected": s.expected, "found": s.found, "produced": s.produced,
                    "correct": s.correct, "recall": round(s.recall, 3), "precision": round(s.precision, 3),
                    "reasons_expected": s.reasons_expected, "reasons_kept": s.reasons_kept}
        return {"engine": self.engine, "overall": sc(self.overall),
                "by_source": {k: sc(v) for k, v in self.by_source.items()},
                "missed": self.missed, "unmatched_claims": self.unmatched,
                "confidence": self.confidence, "verified_unmatched": self.verified_unmatched,
                "quote_failures": self.quote_failures, "warnings": self.warnings}


def _words(text: str) -> str:
    return re.sub(r"[^a-z0-9\- ]+", " ", text.lower())


def _matches(claim: Claim, exp: dict) -> bool:
    """Same type, all key words present, and backed by the kind of source the answer lives in."""
    kinds = {e.chunk.source.kind.value for e in claim.evidence if e.chunk is not None}
    return (claim.type.value in exp["types"] and exp["source"] in kinds
            and all(k in _words(claim.statement) for k in exp["all"]))


def _source_kind_of(claim: Claim) -> str:
    kinds = {e.chunk.source.kind.value for e in claim.evidence if e.chunk is not None}
    return next(iter(kinds)) if len(kinds) == 1 else "mixed"


def score_claims(claims: list[Claim], gold: dict) -> QualityReport:
    rep = QualityReport(engine="")
    expected = gold["expected"]
    taken: dict[str, Claim] = {}
    matched_ids: set[int] = set()
    for exp in expected:
        for c in claims:
            if c.id not in matched_ids and _matches(c, exp):
                taken[exp["id"]] = c
                matched_ids.add(c.id)
                break
    for exp in expected:
        s = rep.by_source.setdefault(exp["source"], Score())
        s.expected += 1
        rep.overall.expected += 1
        hit = taken.get(exp["id"])
        if hit is not None:
            s.found += 1
            rep.overall.found += 1
        else:
            rep.missed.append(exp["id"])
        if exp.get("reason_any"):
            s.reasons_expected += 1
            rep.overall.reasons_expected += 1
            if hit is not None and any(w in _words(hit.statement) for w in exp["reason_any"]):
                s.reasons_kept += 1
                rep.overall.reasons_kept += 1
    # A claim is "correct" if it matches any expected claim, even one already found by another claim.
    for c in claims:
        ok = any(_matches(c, e) for e in expected)
        kind = _source_kind_of(c)
        s = rep.by_source.setdefault(kind, Score())
        s.produced += 1
        rep.overall.produced += 1
        if ok:
            s.correct += 1
            rep.overall.correct += 1
        else:
            rep.unmatched.append(f"[{c.type.value}] {c.statement}")
            if c.confidence == Confidence.verified:
                rep.verified_unmatched += 1
    for c in claims:
        rep.confidence[c.confidence.value] = rep.confidence.get(c.confidence.value, 0) + 1
    return rep


def run_quality(extractor, gold_dir: Path = EVAL_DIR) -> QualityReport:
    gold = json.loads((gold_dir / "gold.json").read_text(encoding="utf-8"))
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        project = Project(name=gold["name"])
        session.add(project)
        session.flush()
        for src in gold["sources"]:
            ingest_source(session, project, kind=SourceKind(src["kind"]), name=src["path"],
                          content=(gold_dir / src["path"]).read_text(encoding="utf-8"),
                          sensitivity=Sensitivity.team, origin="evaluation")
        extraction = run_extraction(session, project, extractor)
        claims = list(session.scalars(select(Claim).where(Claim.project_id == project.id)))
        rep = score_claims(claims, gold)
        rep.engine = extractor.name
        rep.quote_failures = extraction.snippets_failed
        rep.warnings = list(extraction.warnings)
        return rep


def to_markdown(rep: QualityReport) -> str:
    pct = lambda x: f"{round(x * 100)}%"
    lines = [f"# Extraction quality: {rep.engine}", "",
             "Measured on the synthetic library-kiosk set in `data/eval` "
             f"({rep.overall.expected} expected claims).", "",
             "| Source | Expected | Found | Recall | Produced | Correct | Precision |",
             "|---|---|---|---|---|---|---|"]
    for name, s in [*sorted(rep.by_source.items()), ("**all**", rep.overall)]:
        lines.append(f"| {name} | {s.expected} | {s.found} | {pct(s.recall)} | {s.produced} | "
                     f"{s.correct} | {pct(s.precision)} |")
    o = rep.overall
    lines += ["", f"- Decision reasons kept: {o.reasons_kept} of {o.reasons_expected}",
              f"- Confidence labels given: {', '.join(f'{k} {v}' for k, v in sorted(rep.confidence.items())) or 'none'}",
              f"- Quotes that could not be found in their source: {rep.quote_failures}",
              f"- Claims labelled quote-verified that match nothing expected: {rep.verified_unmatched}"]
    if rep.missed:
        lines += ["", "Missed: " + ", ".join(rep.missed)]
    if rep.unmatched:
        lines += ["", "Produced but not expected:", *[f"- {u}" for u in rep.unmatched[:15]]]
    for w in rep.warnings:
        lines += ["", f"Note: {w}"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m app.quality")
    ap.add_argument("--engine", choices=["rules", "llm"], default="rules")
    ap.add_argument("--out", help="write the Markdown report here")
    ap.add_argument("--json", help="write the raw numbers here")
    args = ap.parse_args(argv)
    if args.engine == "rules":
        from .extract.rules import RuleExtractor
        rep = run_quality(RuleExtractor())
    else:
        from .extract.llm import llm_from_env
        with llm_from_env() as extractor:
            rep = run_quality(extractor)
    text = to_markdown(rep)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(rep.as_dict(), indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
