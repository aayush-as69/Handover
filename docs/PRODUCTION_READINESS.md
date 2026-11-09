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
| Review queue | Clearance, status, confidence, counts, ordering and paging all run in SQL (50 per page). A test checks the SQL access rule against the Python rule for every sensitivity combination. |
| Query counts | Claim evidence, chunks and sources load eagerly; handover, conflicts, questions and release pages no longer query per claim. `tests/test_query_counts.py` fails if a page's query count grows with the number of claims. |
| Login throttling | Four database-backed limits per 5 minutes: 5 per account and address, 20 per account, 15 accounts per address, 100 failures per address. Offices behind one address are not locked out by a few typos. Forged `X-Forwarded-For` prefixes are ignored. |
| Request rate limiting | 300 requests and 30 login posts a minute per address, answered with 429 and `Retry-After`; `/health` and static files exempt. In memory per process. |
| Legacy databases | `python -m app.db adopt [--dry-run]` adopts a pre-migration database safely; tested on SQLite and PostgreSQL. |
| Secret masking | Added JWTs, bearer/basic auth, credential URLs, LLM/Google/SendGrid/npm/Slack-webhook keys, fine-grained GitHub tokens, PGP blocks and prefixed assignment names (`DB_PASSWORD`) and unlabelled high-entropy strings (hashes, UUIDs, paths and identifiers are exempt). Tested against both secrets and harmless look-alikes. |
| CI | `.github/workflows/ci.yml` runs tests on SQLite and PostgreSQL plus `pip-audit`. Latest run (9 Nov 2026, commit `a6d9527`): 422 tests passed on SQLite and 422 on PostgreSQL 16 (each includes the browser test), and `pip-audit` found no known vulnerabilities. |

## Third review: reliability and verification
| Item | Status |
|---|---|
| Health vs readiness | `/health` is liveness; `/ready` checks the database and that migrations are current, returns 503 with a fixed reason (no internals). Tested with an unreachable and a behind-schema database. |
| Locked dependencies | `requirements.lock` pins every package; Render and CI build from it. Verified by installing it in an empty virtualenv and running the suite there (429 passed, browser test skipped without Playwright). |
| Adversarial redaction | 36 tests of awkward forms (YAML, curl `-u`, quoted phrases, spoken passwords, zero-width and full-width disguises, short passwords) plus ordinary sentences that must survive. Gaps found and fixed. One documented gap remains: a secret spelled out across a sentence. |
| Human approval stays mandatory | Tests assert extraction and verification never approve a claim, `verify.py` never writes `review_status`, a viewer cannot approve, and unapproved claims never reach a handover. |
| Controlled migrations | `MIGRATE_ON_STARTUP=false` makes the app refuse a stale schema; `python -m app.db upgrade / status / downgrade --yes`. Tested: upgrade, rollback, upgrade again. Default stays on for Render's free plan. |
| Test-client warning | Resolved by adding `httpx2` to the dev requirements. |
| Shared throttling across workers | Tested with two app instances on one database: failures through one block the other. The request-rate counters are per process (documented). |
| Forged forwarding headers | Tested: forged leading entries and ignored headers without `TRUST_PROXY`. |
| Unexpected errors | Tests for a database failure (plain page, no SQL or traceback) and for seven provider failure modes (unreachable, 401, 429, 5xx, non-JSON, empty, truncated JSON): a message, nothing stored. |
| Backup and restore | `scripts/restore_check.py` exercised on PostgreSQL 16 with the demo data (all tables match). Not yet done on Render. |
| Live provider test | `tests/test_live_llm.py` is ready and skipped until you set `LIVE_LLM_TEST=1` and the `LLM_*` variables. Not run, because no key is available here. |

## Still needed before real data
- Run the live provider test and the full LLM pipeline (`tests/test_live_llm.py`, `python -m app.demo --extract llm`) and review the output.
- Deploy on Render, then run `scripts/restore_check.py` against its database once.
- A real secrets store and HTTPS-only hosting (the Render blueprint sets secure cookies).
- A proxy or CDN rate limiter in front of the app. The host provides it; the in-app limiter is per process and cannot replace it.
- Not built: multiple projects per deployment, audit-log page, acknowledgement history by name,
  richer conflict visualisation, extraction reporting. See `OPERATIONS.md` for backups.
