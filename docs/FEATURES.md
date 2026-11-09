# Conflict detection, questions and redaction

Later hardening is listed in `PRODUCTION_READINESS.md`.

All three work on the demo project with no API key, and are covered by `tests/test_conflicts_questions.py`.

## 1. Cross-source conflict detection (`app/conflicts.py`, page `/conflicts`)
- Rule 1: claims with the same `topic` and different `value` conflict.
- Rule 2: a claim that says something is "the only" datastore, gateway, frontend or backend
  conflicts with live claims naming a different technology in that category.
- Demo result: "PostgreSQL is the only datastore" is flagged against the MongoDB prototype
  (commit and issue claims) and the Redis seat-lock claims.
- Conflicts never alter claims. A reviewer records how it was resolved; the resolution
  survives re-runs unless a new claim joins the dispute. Rejected claims are ignored.
- On the handover, a claim shows "Sources disagree" only for partners the reader can see.

## 2. Questions Before I Leave (`app/questions.py`, page `/questions`)
Rules ask: why a technical choice was made when no source says; who owns an unowned action;
who answers an open question; who watches a risk; whether a promised document exists; and
which side of an open conflict is right. Questions are idempotent, close themselves when the
gap is filled, and never overwrite an answer. Answers appear in the handover as the leaver's
own words, only when every claim they concern is visible to the reader.

## 3. Redaction and role views (`app/redaction.py`, `/handover?view_as=`)
| Role | Hidden inside readable claims |
|---|---|
| admin, approver | nothing |
| viewer | emails, phone numbers |
| restricted | emails, phone numbers, money amounts |
A reviewer can preview any role's exact view. Other roles cannot ask to see a different role.

## Testing
354 tests pass across the project (SQLite and PostgreSQL), including these features. Each rule was checked by deliberately breaking it in a scratch copy
(ignoring rejected claims, leaking hidden conflict partners, showing partial answers,
disabling redaction, weakening a role's policy, letting viewers preview, ignoring clearance on
questions, overwriting answers, asking about GitHub-only items). Two survived at first
and now have tests.
