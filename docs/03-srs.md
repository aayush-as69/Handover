<div align="center">

<img src="assets/handover-logo.svg" alt="Handover" width="56" />

# 03 — Software Requirements Specification

<sub>Handover · Product requirements and engineering reference</sub>

</div>

> [Documentation index](README.md) · [Project home](../README.md)

---

## 1. System purpose

Handover is a server-rendered FastAPI application backed by SQLAlchemy that transforms project source material into reviewed, permission-aware handover releases.

## 2. System actors

- Administrator
- Approver
- Viewer / incoming person
- Restricted reader
- Optional external LLM provider
- GitHub public API

## 3. Functional requirements

### Authentication

- User credentials are checked against stored password hashes.
- Unknown usernames are verified against a dummy hash to reduce username-timing leakage.
- Login failures are persisted in the database.
- Session state is established only after successful authentication.
- Logout clears the session.

### Authorization

- Review routes require `admin` or `approver`.
- Source administration requires `admin`.
- Handover readers can see only approved content at or below their clearance.
- Reviewers can preview roles but ordinary readers cannot impersonate another role through the UI.
- The same clearance rule is implemented in Python and SQL for review-queue filtering.

### Ingestion

- Supported source kinds: notes, chat, tasks, GitHub.
- Uploaded text is size-limited and must be UTF-8 text.
- A source is parsed before persistence.
- Content is hashed for duplicate detection.
- Secret masking occurs before chunks are stored.

### Extraction

- Rule extraction is local and requires no API key.
- Optional LLM extraction uses an OpenAI-compatible chat-completions interface.
- Extracted claims must satisfy strict Pydantic schemas.
- Claims without valid evidence are discarded.
- Remote extractors do not receive confidential chunks by default.

### Verification

The verification engine checks:

- whether cited snippets occur in source text;
- key-term overlap;
- numbers/dates;
- negation;
- contradictory evidence.

The result is one of `verified`, `inferred`, `conflicting`, or `unsupported`.

### Review

A reviewer can:

- approve;
- edit;
- reject;
- reopen.

Editing re-verifies the claim and requires approval again.

### Publication

A reviewer signs off the current approved claims into a numbered release. Release rows contain claim/version pairs rather than a mutable copy of claim text.

### Acknowledgement

A reader can acknowledge one specific release. The database prevents duplicate acknowledgements for the same release/user pair.

## 4. Data integrity requirements

- One handover per project.
- One release number per handover.
- One acknowledgement per user per release.
- One source content hash per project.
- One chunk index per source.
- One claim version number per claim.
- Append-only guards for claim versions, audit events and releases.
- Evidence content cannot be altered or deleted after storage.

## 5. External interfaces

### GitHub

Only public repositories are fetched. The integration uses the GitHub REST API without application credentials.

### LLM provider

The optional extractor expects an OpenAI-compatible `/chat/completions` endpoint and requires `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL`.

## 6. Operational requirements

- `/health` is a liveness check.
- `/ready` is a database/schema readiness check.
- Production disables interactive FastAPI API docs.
- Render configuration runs the application with Uvicorn.


---

[← Documentation index](README.md) · [Project home](../README.md)
