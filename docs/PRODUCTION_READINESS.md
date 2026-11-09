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
| 11 | Cross-source conflict detection | Done (see `FEATURES.md`). |
| 12 | Questions Before I Leave | Done. |
| 13 | Field-level redaction | Done. |
| 14 | Better semantic evidence evaluation | Partly. An optional model second opinion exists, advisory only. It has not been run against a live model, so its quality is unknown. |

## Second review: tests, performance, correctness
| Area | Status |
|---|---|
| Approval invalidation after claim edits | Done and tested (stale releases hide the handover from non-reviewers). |
| One valid plus one invalid quote | Done: the claim cannot be `verified`. |
| Concurrent uploads, claim edits, sign-offs | Done: parallel-thread tests on SQLite and PostgreSQL (optimistic locking on claims). |
| Session expiry and cookie flags | Done: HttpOnly, SameSite=Lax, Secure in production, 8h expiry. |
| Multi-page GitHub ingestion | Done: bounded to 5 pages per list. |
| PostgreSQL tests | Done: the whole suite passes on PostgreSQL 16 (`TEST_DATABASE_URL`); CI runs both. |
| Browser end-to-end | Done: Playwright walks review, sign-off, viewer read, acknowledge, and stale release. |
| Migrations | Alembic, one initial migration, run at startup. |
| Dev vs production settings | `APP_ENV=production` refuses weak or missing secrets, insecure cookies, SQLite; hides API docs. |
| LLM client lifecycle | Clients are closed after each use. |
| Review queue | One query with eager loading, paginated 50 per page. Filtering by clearance still happens in Python. |
| CI | `.github/workflows/ci.yml` runs tests on SQLite and PostgreSQL plus `pip-audit`. Not yet run on GitHub. |

## Still needed before real data
- Run the LLM extractor and semantic check against a real provider and measure them.
- A real secrets store and HTTPS-only hosting (the Render blueprint sets secure cookies).
- Rate limiting per client address beyond the per-username lockout, shared across instances.
- Sensitivity filtering in SQL rather than Python, for large projects.
- Not built: multiple projects per deployment, audit-log page, acknowledgement history by name,
  richer conflict visualisation, extraction reporting. See `OPERATIONS.md` for backups.
