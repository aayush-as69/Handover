"""Measure Handover's trust machinery and its extractor, and write a report.

    python -m tests.evals.runner --engine rules
    python -m tests.evals.runner --engine rules --out docs/evals/eval-report.md --json docs/evals/eval-report.json
    LLM_BASE_URL=... LLM_API_KEY=... LLM_MODEL=... python -m tests.evals.runner --engine llm

Four fixture files, four questions:

* claim_accuracy     - does the extractor find what a careful reader would? (engine under test)
* evidence_accuracy  - does the quote check label claims correctly? (deterministic, no model)
* hallucination      - are made-up claims dropped or kept below "verified"? (scripted model
                       output through the real pipeline) and does the engine invent claims
                       from sources with nothing in them? (engine under test)
* secret_leakage     - do secrets stay out of the database, out of what a remote model is
                       sent, and out of anything a model writes back? (deterministic)

Only claim_accuracy and the "invents claims" half of hallucination depend on the engine. The
rest check Handover's own rules, so their numbers must hold for every engine.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.enums import ClaimType, Confidence, Sensitivity, SourceKind, Stance
from app.extract.base import ExtractorOutput
from app.extract.pipeline import run_extraction
from app.ingest.service import ingest_source
from app.models import Base, Chunk, Claim, Evidence, Project, Source
from app.quality import score_claims
from app.schemas import EvidenceIn, ExtractedClaim, ExtractionResult
from app.verify import verify_claim

DIR = Path(__file__).parent

# Gates that depend on the engine; for any other engine these are reported, not enforced.
ENGINE_GATES = {"claim_accuracy.recall", "claim_accuracy.structured_recall", "claim_accuracy.precision",
                "claim_accuracy.empty_case_claims", "hallucination.invented_from_empty"}

# What the rules engine must keep achieving (a regression gate, set a little under what it
# scores today). The "must be zero / one" rows are guarantees, not targets.
THRESHOLDS = {
    "claim_accuracy.recall": 0.55,                 # rules engine reads notes and tasks, not chat
    "claim_accuracy.structured_recall": 1.0,       # notes and tasks: all expected claims found
    "claim_accuracy.precision": 0.90,
    "claim_accuracy.empty_case_claims": 0,
    "evidence_accuracy.accuracy": 1.0,
    "evidence_accuracy.false_verified": 0,
    "hallucination.catch_rate": 1.0,
    "hallucination.invented_from_empty": 0,
    "secret_leakage.leaks": 0,
}


def fixture(name: str) -> dict:
    return json.loads((DIR / f"{name}.json").read_text(encoding="utf-8"))


def _session():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)()


def _project(session, name="eval") -> Project:
    p = Project(name=name)
    session.add(p)
    session.flush()
    return p


class Scripted:
    """Stands in for a model that returns fixed output. Evidence is attached to the first chunk."""

    def __init__(self, claims: list[dict], remote: bool = True, name: str = "scripted"):
        self.claims, self.remote, self.name = claims, remote, name
        self.seen: list[str] = []

    def extract(self, chunks):
        self.seen += [c.text for c in chunks]
        out = []
        for c in self.claims:
            ev = [EvidenceIn(chunk_id=e.get("chunk_id", chunks[0].id if chunks else 0),
                             snippet=e["snippet"], stance=Stance(e.get("stance", "supports")))
                  for e in c.get("evidence", [])]
            out.append(ExtractedClaim(statement=c["statement"], type=ClaimType(c["type"]),
                                      value=c.get("value"), evidence=ev))
        return ExtractorOutput(ExtractionResult(claims=out), [])


class Recorder:
    """A remote extractor that finds nothing but records everything it was sent."""

    remote, name = True, "recorder"

    def __init__(self):
        self.seen: list[str] = []

    def extract(self, chunks):
        self.seen += [c.text for c in chunks]
        return ExtractorOutput(ExtractionResult(claims=[]), [])


# ------------------------------------------------------------------ the four evaluations


def eval_claim_accuracy(extractor) -> dict:
    fx = fixture("claim_accuracy")
    totals = {"expected": 0, "found": 0, "produced": 0, "correct": 0, "reasons_expected": 0, "reasons_kept": 0}
    cases, missed, empty_claims = [], [], 0
    by_kind: dict[str, dict[str, int]] = {}
    for case in fx["cases"]:
        with _session() as s:
            project = _project(s, case["id"])
            ingest_source(s, project, kind=SourceKind(case["kind"]), name=case["name"],
                          content=case["text"], sensitivity=Sensitivity.team, origin="evaluation")
            run_extraction(s, project, extractor)
            claims = list(s.scalars(select(Claim).where(Claim.project_id == project.id)))
            gold = {"expected": [{**e, "source": case["kind"]} for e in case["expected"]]}
            rep = score_claims(claims, gold)
        o = rep.overall
        for k in totals:
            totals[k] += getattr(o, k)
        k = by_kind.setdefault(case["kind"], {"expected": 0, "found": 0, "produced": 0, "correct": 0})
        for key in k:
            k[key] += getattr(o, key)
        missed += [f"{case['id']}/{m}" for m in rep.missed]
        if not case["expected"]:
            empty_claims += len(claims)
        cases.append({"case": case["id"], "expected": o.expected, "found": o.found, "produced": o.produced,
                      "correct": o.correct})
    recall = totals["found"] / totals["expected"] if totals["expected"] else 0.0
    precision = totals["correct"] / totals["produced"] if totals["produced"] else 0.0
    structured = [by_kind.get(k, {"expected": 0, "found": 0}) for k in ("notes", "tasks")]
    s_exp = sum(k["expected"] for k in structured)
    s_found = sum(k["found"] for k in structured)
    return {**totals, "recall": round(recall, 3), "precision": round(precision, 3), "by_kind": by_kind,
            "structured_recall": round(s_found / s_exp, 3) if s_exp else 0.0,
            "empty_case_claims": empty_claims, "missed": missed, "cases": cases}


def eval_evidence_accuracy() -> dict:
    fx = fixture("evidence_accuracy")
    rows, right, false_verified, missed_verified = [], 0, 0, 0
    labels: dict[str, dict[str, int]] = {}
    for case in fx["cases"]:
        with _session() as s:
            project = _project(s)
            src = Source(project_id=project.id, kind=SourceKind.notes, name="e.md", sensitivity=Sensitivity.team)
            chunk = Chunk(source=src, idx=0, text=case["source"], sensitivity=Sensitivity.team)
            claim = Claim.create(project_id=project.id, statement=case["claim"], type=ClaimType(case["type"]),
                                 created_by="eval", sensitivity=Sensitivity.team, extractor="llm:eval")
            for e in case["evidence"]:
                claim.evidence.append(Evidence(chunk=chunk, snippet=e["snippet"], stance=Stance(e["stance"])))
            s.add_all([src, chunk, claim])
            s.flush()
            got = verify_claim(claim).value
        want = case["expect"]
        right += got == want
        false_verified += got == "verified" and want != "verified"
        missed_verified += want == "verified" and got != "verified"
        labels.setdefault(want, {}).setdefault(got, 0)
        labels[want][got] += 1
        rows.append({"case": case["id"], "expected": want, "got": got, "ok": got == want})
    n = len(fx["cases"])
    return {"cases": rows, "n": n, "accuracy": round(right / n, 3), "false_verified": false_verified,
            "missed_verified": missed_verified, "confusion": labels}


def eval_hallucination(extractor) -> dict:
    fx = fixture("hallucination_cases")
    rows, caught = [], 0
    for case in fx["scripted"]:
        with _session() as s:
            project = _project(s)
            ingest_source(s, project, kind=SourceKind(case["source"]["kind"]), name=case["source"]["name"],
                          content=case["source"]["text"], sensitivity=Sensitivity.team, origin="evaluation")
            run_extraction(s, project, Scripted(case["claims"]))
            made = list(s.scalars(select(Claim).where(Claim.project_id == project.id)))
        labels = [c.confidence.value for c in made]
        ok = (not made) if case["must"] == "dropped" else all(c.confidence != Confidence.verified for c in made)
        caught += ok
        rows.append({"case": case["id"], "must": case["must"], "stored": labels, "ok": ok})
    invented = 0
    empty = []
    for src in fx["no_content_sources"]:
        with _session() as s:
            project = _project(s)
            ingest_source(s, project, kind=SourceKind(src["kind"]), name=src["name"], content=src["text"],
                          sensitivity=Sensitivity.team, origin="evaluation")
            run_extraction(s, project, extractor)
            made = [c.statement for c in s.scalars(select(Claim).where(Claim.project_id == project.id))]
        invented += len(made)
        empty.append({"case": src["id"], "claims": made})
    return {"cases": rows, "n": len(rows), "caught": caught, "catch_rate": round(caught / len(rows), 3),
            "invented_from_empty": invented, "empty_sources": empty}


def eval_secret_leakage() -> dict:
    fx = fixture("secret_leakage_cases")
    rows, leaks = [], 0
    for case in fx["ingest"]:
        with _session() as s:
            project = _project(s)
            ingest_source(s, project, kind=SourceKind(case["kind"]), name=case["name"], content=case["text"],
                          sensitivity=Sensitivity.team, origin="evaluation")
            stored = " ".join(c.text for c in s.scalars(select(Chunk)))
            remote = Recorder()
            run_extraction(s, project, remote)
        in_db, sent = case["secret"] in stored, any(case["secret"] in t for t in remote.seen)
        leaks += in_db + sent
        rows.append({"case": case["id"], "stored_in_database": in_db, "sent_to_remote_model": sent,
                     "ok": not (in_db or sent)})
    for case in fx["model_echo"]:
        with _session() as s:
            project = _project(s)
            ingest_source(s, project, kind=SourceKind(case["kind"]), name=case["name"], content=case["text"],
                          sensitivity=Sensitivity.team, origin="evaluation")
            run_extraction(s, project, Scripted([case["claim"]]))
            parts = []
            for c in s.scalars(select(Claim)):
                parts += [c.statement, c.value or "", c.topic or "", c.owner or ""]
            parts += [e.snippet for e in s.scalars(select(Evidence))]
        kept = case["secret"] in " ".join(parts)
        leaks += kept
        rows.append({"case": case["id"], "stored_in_claim": kept, "ok": not kept})
    return {"cases": rows, "n": len(rows), "leaks": leaks}


# ------------------------------------------------------------------ report


def run_all(extractor) -> dict:
    return {"engine": extractor.name,
            "claim_accuracy": eval_claim_accuracy(extractor),
            "evidence_accuracy": eval_evidence_accuracy(),
            "hallucination": eval_hallucination(extractor),
            "secret_leakage": eval_secret_leakage()}


def _get(result: dict, dotted: str):
    section, key = dotted.split(".")
    return result[section][key]


def check(result: dict) -> list[str]:
    """Compare a result with THRESHOLDS; returns one line per failed gate."""
    bad = []
    rules = str(result["engine"]).startswith("rules")
    for name, want in THRESHOLDS.items():
        if name in ENGINE_GATES and not rules:
            continue
        got = _get(result, name)
        low_is_good = isinstance(want, int) and want == 0 and name.split(".")[1] not in ("accuracy",)
        ok = got <= want if low_is_good else got >= want
        if not ok:
            bad.append(f"{name}: {got} (needs {'<=' if low_is_good else '>='} {want})")
    return bad


def to_markdown(r: dict) -> str:
    pct = lambda x: f"{round(x * 100)}%"
    ca, ea, ha, sl = r["claim_accuracy"], r["evidence_accuracy"], r["hallucination"], r["secret_leakage"]
    L = [f"# Evaluation report: {r['engine']}", "",
         "Generated by `python -m tests.evals.runner`. Fixtures are in `tests/evals/`; all text is invented.",
         "Two rows depend on the extraction engine; the others test Handover's own checks and must hold for any engine.", "",
         "| Measure | Result | Gate | Depends on engine |", "|---|---|---|---|",
         f"| Claims found (recall) | {pct(ca['recall'])} ({ca['found']} of {ca['expected']}) | rules >= {pct(THRESHOLDS['claim_accuracy.recall'])} | yes |",
         f"| Claims found in notes and tasks | {pct(ca['structured_recall'])} | rules 100% | yes |",
         f"| Claims that were expected (precision) | {pct(ca['precision'])} ({ca['correct']} of {ca['produced']}) | rules >= {pct(THRESHOLDS['claim_accuracy.precision'])} | yes |",
         f"| Claims invented from sources with nothing in them | {ha['invented_from_empty'] + ca['empty_case_claims']} | 0 | yes |",
         f"| Quote check gives the right label | {pct(ea['accuracy'])} ({ea['n']} cases) | 100% | no |",
         f"| Unsupported claims labelled verified | {ea['false_verified']} | 0 | no |",
         f"| Scripted hallucinations dropped or kept below verified | {ha['caught']} of {ha['n']} | all | no |",
         f"| Secret leaks (database, remote model, stored claims) | {sl['leaks']} of {sl['n']} cases | 0 | no |", ""]
    L += ["", "| Source kind | Expected | Found | Produced | Correct |", "|---|---|---|---|---|"]
    L += [f"| {k} | {v['expected']} | {v['found']} | {v['produced']} | {v['correct']} |" for k, v in sorted(ca["by_kind"].items())]
    L.append("")
    if ca["missed"]:
        L += ["Missed claims: " + ", ".join(ca["missed"]), ""]
    L += ["## Quote check", "", "| Case | Expected | Got |", "|---|---|---|"]
    L += [f"| {c['case']} | {c['expected']} | {c['got']}{'' if c['ok'] else ' (wrong)'} |" for c in ea["cases"]]
    L += ["", "## Hallucination cases", "", "| Case | Must be | Stored as | Result |", "|---|---|---|---|"]
    L += [f"| {c['case']} | {c['must'].replace('_', ' ')} | {', '.join(c['stored']) or 'nothing stored'} | {'pass' if c['ok'] else 'FAIL'} |" for c in ha["cases"]]
    L += ["", "## Secret leakage", "", "| Case | Result |", "|---|---|"]
    L += [f"| {c['case']} | {'pass' if c['ok'] else 'LEAK'} |" for c in sl["cases"]]
    L += ["", "## Limits", "",
          "- Fixtures are small and written by the author, so a high score shows the checks work on known cases, not that they catch every real-world failure.",
          "- The quote check proves a quote exists and agrees with the claim's words. It cannot judge meaning; a person still approves every claim.",
          "- The secret patterns are pattern-based. A secret in an unusual format may not be recognised; the cases above cover the common ones.", ""]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tests.evals.runner")
    ap.add_argument("--engine", choices=["rules", "llm"], default="rules")
    ap.add_argument("--out", help="write the Markdown report here")
    ap.add_argument("--json", help="write the raw numbers here")
    args = ap.parse_args(argv)
    if args.engine == "rules":
        from app.extract.rules import RuleExtractor
        result = run_all(RuleExtractor())
    else:
        from app.extract.llm import llm_from_env
        with llm_from_env() as extractor:
            result = run_all(extractor)
    text = to_markdown(result)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2), encoding="utf-8")
    failed = check(result)
    for line in failed:
        print("GATE FAILED:", line)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
