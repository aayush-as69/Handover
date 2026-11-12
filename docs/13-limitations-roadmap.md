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

General request throttling is in memory per process. The database-backed login failure tracking is persistent, but request throttling itself is not distributed.

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

- Background jobs run on a thread inside the web process. They are not a distributed queue, do not survive a restart, and give a status, not a percentage.
- Slack and Jira are read from exported files, not a live connection. There is no scheduled sync.

## Environments

| Environment | Database |
|---|---|
| Development | SQLite or PostgreSQL |
| CI | SQLite and PostgreSQL 16 |
| Production | PostgreSQL required; SQLite is refused at startup |
