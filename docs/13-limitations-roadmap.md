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

### One project per deployment

The current review/handover architecture assumes a single project in a deployment.

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
