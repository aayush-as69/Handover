<div align="center">

<img src="assets/handover-logo.svg" alt="Handover" width="48" />

# 13 — Limitations & Roadmap

<sub>Handover · Product and engineering documentation</sub>

</div>

---

## Verified limitations

### Verification is mechanical

The verification engine checks textual evidence, terms, numbers/dates and negation. It cannot determine semantic truth, currentness or completeness.

### LLM paths are optional and not fully live-validated

The deterministic tests simulate provider behavior. A real provider run requires credentials and separate evaluation.

### Deployment is configured but not live-verified

`render.yaml` is present and production configuration is tested locally, but the repository documentation does not claim that the live Render service has been independently verified.

### Secret masking is pattern based

The implementation intentionally leans toward masking too much, but unusual/short/word-like secrets may evade detection.

### GitHub ingestion is bounded

Only public repositories are supported. Collection is bounded by pagination/detail limits and the unauthenticated GitHub API rate limit.

### Conflict detection is rule based

It uses fixed technology categories and available topic/value information. It can miss disagreements and can flag related but non-conflicting mentions.

### Questions are rule based

The checklist can generate noise and requires reviewer judgment.

### Projects share users and roles

A deployment can hold several projects with membership-based access (see `15-round-improvements.md`), and a person can hold a different role in each project (approver, viewer or restricted, set by an admin on the membership; with none set, their default role applies). The admin role stays instance-wide and is never granted per project. There are still no organisations, teams or separate tenants.

### Distributed rate limiting is not implemented

General request throttling (`app/throttle.py`) is in memory per process. The database-backed login lockout is persistent and shared, but request throttling itself is not distributed.

## Roadmap proposals

These are proposals, not commitments:

1. Multiple projects per deployment.
2. Richer conflict visualization.
3. Dedicated audit-log UI.
4. Named acknowledgement history.
5. Extraction-quality reporting.
6. Stronger semantic evaluation.
7. Additional source integrations.
8. Distributed rate limiting.
9. Operational improvements around live deployment verification.

## Explicit non-goals

The project should not silently replace human approval with model confidence, expose confidential evidence to remote models by default, or turn verification into a claim of semantic truth.

- Background jobs run on a thread inside the web process by default (`JOB_MODE=thread`): they do not survive a restart. `JOB_MODE=queue` with `python -m app.worker` moves them to separate workers that share the database as the queue; there is no broker, automatic retry or scheduling. Jobs give a status, not a percentage. See [17](17-jobs-and-observability.md).
- Metrics are in memory per process and reset on restart; job counts come from the database.
- `handover_releases.claims_json` is kept next to the new `handover_release_claims` table because releases are immutable and the old column cannot be cleared. Readers use the table and fall back to the JSON for releases that have no rows.
- Slack and Jira are read from exported files, not a live connection. There is no scheduled sync.

## Environments

| Environment | Database |
|---|---|
| Development | SQLite or PostgreSQL |
| CI | SQLite and PostgreSQL 16 |
| Production | PostgreSQL required; SQLite is refused at startup |

## Scale and operations: what is known

- **Page timings** (`python scripts/benchmark.py`, SQLite, one user, one process, synthetic project with quotes and conflicts; seconds, median of 2–3 requests):

  | Claims | `/review` | `/conflicts` | `/search` | `/inbox` | `/handover` | `/handover/brief` |
  |---|---|---|---|---|---|---|
  | 100 | 0.03 | 0.01 | 0.01 | 0.02 | 0.03 | 0.01 |
  | 1,000 | 0.04 | 0.06 | 0.04 | 0.06 | 0.16 | 0.07 |
  | 5,000 | 0.13 | 0.35 | 0.02 | 0.40 | 1.2 | 0.48 |
  | 10,000 | 0.19 | 0.61 | 0.02 | 0.62 | 3.7 | 0.99 |

  Query counts stay flat (about 10 to 25 per page; more only where lookups are split into batches), so there is no per-claim query. Time grows roughly linearly. `/handover` is the outlier because it renders every approved claim into one page (about 35 MB of HTML at 6,000 claims) and the page searches client-side, so it cannot simply be paged. A real handover is tens to a few hundred claims; if one grows past about 2,000, split the project. PostgreSQL, concurrent users and 100,000 claims have not been measured.
- Metrics are per process and the request limiter is per process. With several web instances, scrape each instance or aggregate in your monitoring system, and limit at the edge.
- The backup drill (`scripts/restore_check.py --smoke`) has been run on local PostgreSQL 16 only, not on a hosted database.
- `render.production.yaml` has not been deployed by the author; the first real deploy is its test.
- The stylesheet is one file (about 1,300 lines). It is organised by comment sections, and splitting it is worthwhile once the interface stops changing.

