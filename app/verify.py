"""Verification pass: decide how far each claim can be trusted, from mechanical checks.

Labels (never set by a model):
  verified     At least one supporting quote was found WORD FOR WORD in its source, and the
               claim's key terms, numbers and negation agree with the quotes. (Claims built by
               the rule-based extractor are derived mechanically from the quote, so the quote
               check alone is enough.)
  inferred     Quotes were found, but the claim says more than they do: terms or numbers that
               are not in the quotes, or a negation mismatch. A human must judge it.
  conflicting  A quote that was found in the sources contradicts the claim.
  unsupported  No quote could be found in any source, or there is no evidence at all.

Limits, stated plainly: this is a coarse text check. It catches invented quotes, drifting
paraphrase, made-up numbers and flipped negation. It cannot judge meaning, so a human still
approves every claim.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .enums import ChangeType, Confidence, Stance
from .models import AuditEvent, Claim, Project, utcnow

MIN_SNIPPET_CHARS = 10
SUPPORT_THRESHOLD = 0.5

_STOP = set(
    """a an the and or but if then than so as of in on at to for from by with about into over
    is are was were be been being am do does did have has had will would can could may might
    shall should must it its this that these those there here he she they them their we our
    you your i me my who whom which what when where why how all any each some more most other
    such only also just very too team project decided decision agreed plan planned need
    needs currently now still""".split()
)
_NEG = {"not", "no", "never", "cannot", "without", "none", "nobody", "nothing"}


# ---------------------------------------------------------------- quote check


def _norm(text: str) -> str:
    text = (
        text.replace("’", "'").replace("‘", "'")
        .replace("“", '"').replace("”", '"')
        .replace("–", "-").replace("—", "-")
    )
    return " ".join(text.split())


def snippet_in_text(snippet: str, text: str) -> bool:
    """True if the snippet appears in the text word for word.

    Tolerated, because they change no words: line breaks and indentation, curly quotes,
    surrounding quote marks, and "..." where the quote skips text (parts must appear in order).
    Not tolerated: different wording, different case, or a quote too short to mean anything.
    """
    haystack = _norm(text)
    needle = _norm(snippet).strip(" \"'")
    if not needle:
        return False
    parts = [p.strip(" \"'") for p in re.split(r"\s*(?:\.\.\.|…)\s*", needle)]
    parts = [p for p in parts if p]
    if not parts:
        return False
    if sum(len(p) for p in parts) < MIN_SNIPPET_CHARS and " ".join(parts) != haystack:
        return False
    pos = 0
    for part in parts:
        i = haystack.find(part, pos)
        if i < 0:
            return False
        pos = i + len(part)
    return True


# ---------------------------------------------------------------- support check


def _stem(t: str) -> str:
    if any(c.isdigit() for c in t):
        return t
    for suffix in ("ing", "ed", "es", "s"):
        if len(t) > len(suffix) + 3 and t.endswith(suffix):
            t = t[: -len(suffix)]
            break
    if len(t) > 4 and t.endswith("e"):
        t = t[:-1]
    return t


def _tokens(text: str) -> set[str]:
    out = set()
    for t in re.findall(r"[a-z0-9]+", text.lower()):
        if t in _STOP:
            continue
        if len(t) < 3 and not any(c.isdigit() for c in t):
            continue
        out.add(_stem(t))
    return out


def _has_negation(text: str) -> bool:
    return any(w in _NEG or w.endswith("n't") for w in re.findall(r"[a-z']+", text.lower()))


def _is_mechanical(claim: Claim) -> bool:
    """Built by the rule-based extractor straight from a quote, and not edited since."""
    return (claim.extractor or "").startswith("rules") and not any(
        v.change_type == ChangeType.edit for v in claim.versions
    )


def verify_claim(claim: Claim) -> Confidence:
    """Check every quote, set the claim's label and explain it. Review status is untouched."""
    supporting, contradicting, failed = [], [], 0
    for ev in claim.evidence:
        ok = snippet_in_text(ev.snippet, ev.chunk.text)
        ev.snippet_verified = ok
        if not ok:
            failed += 1
        elif ev.stance == Stance.contradicts:
            contradicting.append(ev)
        else:
            supporting.append(ev)

    total = len(claim.evidence)
    score = None
    if contradicting:
        label = Confidence.conflicting
        note = f"{len(contradicting)} quote(s) found in the sources contradict this claim."
    elif not supporting:
        label = Confidence.unsupported
        note = (
            "No evidence is attached."
            if total == 0
            else f"None of the {total} quote(s) could be found word for word in the sources."
        )
    elif _is_mechanical(claim):
        label, score = Confidence.verified, 1.0
        note = (f"{len(supporting)} of {total} quote(s) found word for word. "
                "The claim is derived mechanically from the quote.")
    else:
        quoted = " ".join(ev.snippet for ev in supporting)
        claim_terms, quote_terms = _tokens(claim.statement), _tokens(quoted)
        score = len(claim_terms & quote_terms) / len(claim_terms) if claim_terms else 0.0
        missing_numbers = sorted(
            t for t in claim_terms - quote_terms if any(c.isdigit() for c in t)
        )
        problems = []
        if score < SUPPORT_THRESHOLD:
            problems.append(f"only {score:.0%} of the claim's key terms appear in the quotes")
        if missing_numbers:
            problems.append("these numbers or dates are not in the quotes: " + ", ".join(missing_numbers))
        if _has_negation(claim.statement) != _has_negation(quoted):
            problems.append("the claim and the quotes differ on negation")
        label = Confidence.inferred if problems else Confidence.verified
        note = f"{len(supporting)} of {total} quote(s) found word for word. " + (
            "; ".join(problems).capitalize() + "." if problems
            else f"{score:.0%} of the claim's key terms appear in the quotes."
        )

    if failed and label != Confidence.unsupported:
        note += f" {failed} other quote(s) could not be found."
    changed = claim.verified_at is None or claim.confidence != label or claim.verification_note != note
    claim.confidence = label
    claim.support_score = score
    claim.verification_note = note
    claim.verified_at = utcnow()
    if changed:     # an unchanged re-check adds no noise; every change is on the record
        claim.audit_events.append(AuditEvent(
            actor="verifier", action="verify",
            detail=json.dumps({"confidence": label.value, "note": note, "score": score,
                               "evidence": json.loads(claim.evidence_snapshot())})))
    return label


@dataclass
class VerificationReport:
    counts: dict[str, int] = field(default_factory=dict)
    snippets_checked: int = 0
    snippets_failed: int = 0


def verify_claims(claims: Iterable[Claim]) -> VerificationReport:
    report = VerificationReport()
    tally: Counter = Counter()
    for claim in claims:
        tally[verify_claim(claim).value] += 1
        report.snippets_checked += len(claim.evidence)
        report.snippets_failed += sum(1 for e in claim.evidence if e.snippet_verified is False)
    report.counts = dict(tally)
    return report


def verify_project(session: Session, project: Project) -> VerificationReport:
    claims = session.scalars(select(Claim).where(Claim.project_id == project.id)).all()
    report = verify_claims(claims)
    session.flush()
    return report
