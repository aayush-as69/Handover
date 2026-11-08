# Production readiness review

An external review listed what to fix before production. Status of each item:

| # | Item | Status |
|---|---|---|
| 0 | Meaningless `or True` assertion in `tests/test_handover.py` | Fixed. It now asserts the rendered page shows the claims, then that they vanish after reject/edit. |
| 1 | Unique `project_id` for Handover | Done (unique constraint, tested). |
| 2 | Race-safe handover creation | Done (savepoint plus refetch; a lost race is tested). |
| 3 | Race-safe source dedupe | Done (unique `project_id, content_hash`, savepoint; lost race tested). |
| 4 | Immutable, complete audit history | Done. Claim versions record status, confidence, sensitivity and evidence; verification and model opinions are audit events; versions, events, releases and stored evidence cannot be updated or deleted. |
| 5 | Persistent login throttling | Done (database table; survives restart). |
| 6 | Acknowledgement race | Done (unique per release and user; lost race tested). |
| 7 | Versioned handovers | Done (immutable numbered releases; history page; changed claims drop out until re-released). |
| 8 | Stronger meaning of `verified` | Done. Shown as "quote-verified", needs 2+ distinctive terms and 60% coverage, the UI states what it does not mean, and disputed claims show their conflicts. |
| 9 | Validate LLM response types | Done (envelope, content parts, strict ids, sizes, control characters, caps, truncation). 46 tests. |
| 10 | GitHub files, diffs, PR reviews | Done (parser, live fetch with a request budget, rule for "changes requested", secrets in diffs masked). |
| 11 | Cross-source conflict detection | Done in Round 3 (see `ROUND3.md`). |
| 12 | Questions Before I Leave | Done in Round 3. |
| 13 | Field-level redaction | Done in Round 3. |
| 14 | Better semantic evidence evaluation | Partly. An optional model second opinion exists, advisory only. It has not been run against a live model, so its quality is unknown. |

## Still needed before real data
- Database migrations (Alembic).
- Run the LLM extractor and semantic check against a real provider and measure them.
- A real secrets store and HTTPS-only hosting (the Render blueprint sets secure cookies).
- Per-client rate limiting beyond the per-username lockout.
