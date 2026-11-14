"""Four plain answers for every claim a reviewer opens.

  What is the problem?          what kind of thing this claim is, in one sentence
  Why should I care?            the reasons it matters, from facts the system recorded
  What evidence proves it?      how many quotes, from how many sources, and the best one
  What action should I take?    the next step, chosen by fixed rules from the label and status

Everything here is chosen by fixed rules from recorded facts (type, label, conflicts, quote
counts, evidence age, status). Nothing is generated or guessed, so two reviewers looking at the
same claim are told the same thing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .connections import Breakdown
from .freshness import Freshness
from .models import Claim

PROBLEM = {
    "decision": "A decision was made that the next owner needs to know about.",
    "risk": "Something could go wrong.",
    "dependency": "Something else has to keep working for this to work.",
    "owner": "Someone owns this, or nobody does.",
    "open_question": "Nobody has answered this yet.",
    "next_action": "Work is waiting to be done.",
    "blocker": "Work is stuck until this is resolved.",
    "recurring_problem": "This keeps happening.",
    "contact": "Someone has to be asked about this.",
}

MATTERS = {
    "decision": "Without the decision and its reason, the next person may undo it.",
    "risk": "It is cheaper to prevent than to fix after it happens.",
    "dependency": "If the other thing changes, this stops working without warning.",
    "owner": "Without a named owner, questions about it go nowhere.",
    "open_question": "Work that depends on the answer cannot be finished.",
    "next_action": "If nobody picks it up, it does not get done.",
    "blocker": "The work it blocks cannot move until it is cleared.",
    "recurring_problem": "It will keep costing time until someone fixes the cause.",
    "contact": "The next person needs to know who to ask.",
}


@dataclass
class Action:
    headline: str
    detail: str
    key: str                    # approve | edit | reject | conflicts | none
    link: str = ""


@dataclass
class ClaimBrief:
    problem: str
    reasons: list[str]
    evidence: str
    best_quote: tuple | None    # (quote, where, chunk id)
    action: Action
    checks: list[str] = field(default_factory=list)


def next_step(status: str, confidence: str, open_disputes: int, stale: bool) -> Action:
    """The one next step for a claim. Shared by the claim page and the review queue."""
    if status == "approved":
        return Action("Nothing to do", "Approved. Reopen it if its evidence changes.", "none")
    if status == "rejected":
        return Action("Nothing to do", "Rejected. Reopen it if the rejection was a mistake.", "none")
    if open_disputes:
        return Action("Settle the conflict first",
                      "Sources disagree. Decide which one is right, then come back to this claim.",
                      "conflicts", "/conflicts")
    if confidence == "conflicting":
        return Action("Read the contradicting quote",
                      "A source says the opposite. Reject the claim or edit it to match the source.", "reject")
    if confidence == "unsupported":
        return Action("Find where this came from",
                      "No quote was found in any source. If you cannot find it, reject it.", "reject")
    if confidence == "inferred":
        return Action("Compare the wording with the quote",
                      "The claim says more than its quotes do. Edit it to match, or approve with a note.", "edit")
    if stale:
        return Action("Confirm it is still true",
                      "The quotes are old. Check with whoever knows, then approve with a note.", "approve")
    return Action("Check it matters, then approve",
                  "Every quote was found in the sources and nothing disputes it.", "approve")


def claim_brief(claim: Claim, *, breakdown: Breakdown, freshness: Freshness, disputes: list,
                sensitivity: str) -> ClaimBrief:
    t = claim.type.value
    reasons = [MATTERS.get(t, "")]
    open_disputes = [cf for cf, _ in disputes if cf.status.value == "open"]
    if open_disputes:
        n = len(open_disputes)
        reasons.append(f"Sources disagree about it ({n} open conflict{'s' if n != 1 else ''}).")
    if sensitivity in ("restricted", "confidential"):
        reasons.append(f"It is marked {sensitivity}, so only roles with that clearance will see it.")
    if freshness.state == "stale":
        reasons.append(f"Its newest quote is {freshness.age_days} days old.")
    elif freshness.state == "ageing":
        reasons.append(f"Its newest quote is {freshness.age_days} days old and may be out of date.")
    if breakdown.sources == 1:
        reasons.append("Only one source backs it.")
    reasons = [r for r in reasons if r]

    if breakdown.quotes:
        evidence = (f"{breakdown.found} of {breakdown.quotes} supporting quote"
                    f"{'s' if breakdown.quotes != 1 else ''} found word for word, from "
                    f"{breakdown.sources} source{'s' if breakdown.sources != 1 else ''}.")
        if breakdown.contradicting:
            evidence += f" {breakdown.contradicting} quote{'s' if breakdown.contradicting != 1 else ''} contradict it."
    else:
        evidence = "No supporting quote you are allowed to read is attached."
    best = None
    for _name, _kind, items in breakdown.tree:
        if items:
            loc, quote, cid = items[0]
            best = (quote, f"{_name} › {loc}" if not loc.startswith(_name) else loc, cid)
            break

    action = next_step(claim.review_status.value, claim.confidence.value, len(open_disputes),
                       freshness.state == "stale")
    return ClaimBrief(PROBLEM.get(t, "A claim to check."), reasons, evidence, best, action)
