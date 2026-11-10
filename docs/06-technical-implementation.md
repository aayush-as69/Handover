# 06 — Technical Implementation

## 1. Stack

| Technology | Role |
|---|---|
| Python 3.12 | Runtime/CI target |
| FastAPI | Web framework |
| Uvicorn | ASGI server |
| SQLAlchemy | ORM/database access |
| Pydantic | Extraction/input validation |
| Jinja2 | Server-rendered UI |
| PostgreSQL | Production database |
| SQLite | Local/test database |
| Alembic | Database migrations |
| HTTPX | HTTP client/testing |
| Playwright | Browser E2E |
| Pytest | Test framework |
| ItsDangerous | Signed session mechanism through Starlette SessionMiddleware |
| Psycopg | PostgreSQL driver |
| Optional OpenAI-compatible LLM | Claim extraction / advisory semantic review |
| GitHub REST API | Public repository ingestion |
| Render | Deployment configuration |

## 2. Core application modules

### `app/main.py`

Creates the FastAPI application, installs middleware, mounts static assets, registers routers, configures exception handling and exposes `/health` and `/ready`.

### `app/config.py`

Reads environment variables and validates production configuration. Production rejects missing/weak session configuration, insecure cookies, SQLite and weak demo credentials.

### `app/db.py`

Creates the SQLAlchemy engine/session factory and controls Alembic migration behavior.

### `app/models.py`

Defines persistence entities, relationships, versioning and append-only guards.

### `app/schemas.py`

Defines strict Pydantic models for extracted claims and evidence. Model output is bounded and cleaned before persistence.

### `app/enums.py`

Centralizes roles, sensitivity levels, confidence labels, claim types and state vocabularies.

### `app/security.py`

Implements PBKDF2 password hashing/verification, CSRF tokens, login throttling and address-aware persistent failure limits.

### `app/access.py`

Centralizes effective-sensitivity calculation and role clearance. It also provides SQL expressions so review-queue filtering can happen in the database.

### `app/web.py`

Implements login/logout, review queue, claim detail and claim actions.

### `app/handover_web.py`

Implements handover views/actions and admin source ingestion/extraction routes.

### `app/insights_web.py`

Implements conflict and question workflows.

### `app/handover.py`

Implements release creation, stale-release logic, role-filtered sections and acknowledgement behavior.

### `app/questions.py`

Generates and manages “Questions Before I Leave” gaps.

### `app/conflicts.py`

Detects source/claim disagreements and lets reviewers resolve/reopen them.

### `app/verify.py`

Performs mechanical quote/evidence verification.

### `app/redaction.py`

Applies field-level email/phone/amount masking after access control has determined that the containing claim is visible.

### `app/semantic.py`

Provides an optional advisory model-based second opinion. It cannot directly change the mechanical confidence label.

## 3. Ingestion engine

### Supported sources

- notes;
- chat exports;
- task CSVs;
- public GitHub snapshots.

### Processing order

The service parses the complete source before creating database records. It computes a SHA-256 content hash and checks for duplicates. Parsed chunks then pass through secret masking and sensitivity assignment before persistence.

### GitHub limits

The implementation fetches public repositories only. List pagination has a hard ceiling of five pages, and detailed file/diff/review collection is bounded to recent items to protect the unauthenticated API rate limit.

## 4. Extraction engine

### Rule extractor

`RuleExtractor` interprets structured notes, tasks and GitHub material. Chat is intentionally not semantically interpreted by the rule engine.

### LLM extractor

`OpenAICompatibleExtractor`:

1. batches chunks by character budget;
2. constructs a system/user message pair;
3. asks for structured JSON;
4. validates the response against Pydantic models;
5. retries malformed JSON once;
6. drops malformed claims rather than persisting them.

The prompt explicitly treats source content as untrusted data and instructs the model not to follow instructions embedded in source chunks.

## 5. Verification engine

Confidence labels are assigned by `app/verify.py`, not by the model.

| Label | Meaning |
|---|---|
| `verified` | Supporting evidence was found and the claim passes mechanical support checks |
| `inferred` | Evidence exists but the claim adds unsupported terms/numbers/dates or has a negation mismatch |
| `conflicting` | Attached evidence contradicts the claim |
| `unsupported` | No usable evidence was found |

Even `verified` means **quote-verified**, not proven true or current.

## 6. Human review

Reviewers see the claim, evidence, verification reason, conflicts and version history. Approving a non-verified/doubted claim requires a written reason. Editing a claim increments its version, clears the previous semantic opinion, re-runs verification and returns it to the review process.

## 7. Handover engine

A release records the exact `(claim_id, version)` pairs approved at sign-off. The claim text is not copied into the release because claim versions are append-only.

A later edit/reject/reopen makes the previous release stale for non-reviewers. This is intentionally conservative and fail-closed.
