# Handover

> **Keep critical project knowledge from leaving with people.**

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/aayush-as69/Handover)

Built for the CodeFrontier hackathon (We Code Coders) by team STARTEND.

Handover turns scattered project activity—notes, chat, task exports and public GitHub activity—into an evidence-linked knowledge handover that is reviewed by a human before it is published.

Every extracted claim keeps its supporting evidence, verification result, sensitivity level and review history. Access is enforced server-side, sensitive material is redacted, and published handovers are represented by immutable numbered releases.

## Why Handover exists

When a developer, team lead or other project owner leaves, the code may remain while the context disappears: why a decision was made, who owns an unfinished task, which risks are known, or which information is confidential.

Handover addresses that knowledge-loss problem by turning project sources into **reviewable claims rather than an opaque AI-generated summary**.

## Core workflow

```text
Project sources
    │
    ├── meeting / notes
    ├── chat export
    ├── task CSV
    └── public GitHub repository
            │
            ▼
      Parse + normalize
            │
            ▼
      Secret redaction
            │
            ▼
        Chunk storage
            │
            ▼
  Rule extraction / optional LLM
            │
            ▼
      Evidence-linked claims
            │
            ▼
   Mechanical verification
            │
            ▼
 Human review: approve / edit / reject
            │
            ▼
    Immutable numbered release
            │
            ▼
 Role-based filtering + redaction
            │
            ▼
      Incoming team member
```

## What is implemented

- Notes, chat, task CSV and public GitHub ingestion.
- Secret detection and masking before persistence.
- Content hashing and duplicate-source protection.
- Rule-based extraction that works without an API key.
- Optional OpenAI-compatible LLM extraction.
- Evidence references tied to source chunks.
- Mechanical quote verification and confidence labels.
- Human review with approve, edit, reject and reopen actions.
- Claim version history and word-level change display.
- Conflict detection and “Questions Before I Leave”.
- Role-based clearance and server-side access enforcement.
- Field-level redaction for email, phone and restricted-role monetary data.
- Handover sign-off and immutable numbered releases.
- Release acknowledgement.
- SQLite development/testing and PostgreSQL support.
- Alembic migrations.
- Render deployment configuration.
- Browser E2E, security/adversarial, concurrency, migration, backup/restore and database tests.

## Confidence labels
| Label | Meaning |
|---|---|
| verified (shown as "quote-verified") | A supporting quote was found word for word in its source, and the claim's key terms (at least two, at least 60%), numbers and negation agree with it. It does **not** mean the claim is true, current or complete. A person decides that. |
| inferred | Quotes were found, but the claim says more than they do (extra terms, numbers or dates, or a flipped negation). A human must judge it. |
| conflicting | A quote found in the sources contradicts the claim. |
| unsupported | No quote could be found in any source, or there is no evidence. |

Every label carries a note explaining why, so a reviewer can see what the check found.

## Trust model

Handover deliberately separates **extraction, verification and approval**:

1. Source material is treated as untrusted input.
2. Secrets are masked during ingestion.
3. Extracted claims are untrusted drafts.
4. Evidence must reference chunks supplied to the extractor.
5. Mechanical verification checks quotes, terms, numbers and negation.
6. Verification does not establish semantic truth.
7. A human reviewer must approve a claim before it becomes handover content.
8. Server-side authorization determines whether a user can see a claim or source.
9. Published releases contain approved claim/version pairs and are append-only.

## The interface
Server-rendered pages with one stylesheet and no external fonts or scripts, so the strict
`default-src 'self'` policy holds. The look is a bento grid of frosted-glass tiles over a soft
gradient (blur, thin light borders), in light and dark to match the device setting.
- **Review queue:** count tiles for needs review, approved and rejected (each opens that list),
  a filter tile, and the claim list with a coloured bar per confidence level. Riskiest first.
- **Claim page:** the statement, the reason for its label, one tile per piece of evidence
  (quote, verified or not, source, link to the source text), the decision form, version history.
- **Conflicts, questions, handover, sources:** the same tile layout.
- **Small screens:** the grid folds to one column and the claim table becomes stacked cards.
- **Accessibility:** visible focus rings, keyboard-reachable controls, reduced-motion respected.
  A formal accessibility audit has not been done.

## Quick start

Python 3.12 is the CI/deployment target.

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.lock -r requirements-dev.txt
pytest
python -m app.demo
python -m app.demo --extract rules
uvicorn app.main:app --reload
```

Linux/macOS:

```bash
source .venv/bin/activate
pip install -r requirements.lock -r requirements-dev.txt
pytest
python -m app.demo
python -m app.demo --extract rules
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/login` after starting the server. Demo users only get a password
if one is supplied: set `DEMO_PASSWORD` before `python -m app.demo`. The users are
`meera` (approver), `riya` (admin) and `kabir` (viewer) and `rao` (restricted).

For a stable development session key, set `SECRET_KEY`. Production requires a 32+ character secret, PostgreSQL, secure cookies and other validated production settings.

## Optional LLM extraction

The application accepts providers that expose the OpenAI chat-completions format.

```bash
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
LLM_API_KEY=<your-key>
LLM_MODEL=<model-name>
python -m app.demo --extract llm
```

Never commit the API key. Remote extraction excludes confidential chunks unless explicitly allowed by the caller.

## Documentation

| Document | Purpose |
|---|---|
| [Documentation index](docs/README.md) | Complete documentation map |
| [Project overview](docs/01-project-overview.md) | Problem, scope, users and workflows |
| [PRD](docs/02-prd.md) | Product requirements and acceptance criteria |
| [SRS](docs/03-srs.md) | Software requirements and traceability |
| [Architecture](docs/04-architecture.md) | System architecture and data flow |
| [Database design](docs/05-database-design.md) | Entities, relationships and invariants |
| [Technical implementation](docs/06-technical-implementation.md) | Modules, ingestion and extraction |
| [Security architecture](docs/07-security.md) | Security controls and trust boundaries |
| [API reference](docs/08-api-reference.md) | Browser and health/readiness routes |
| [Testing guide](docs/09-testing.md) | Test strategy, commands and traceability |
| [Development setup](docs/10-development.md) | Local development and migrations |
| [Deployment & operations](docs/11-deployment-operations.md) | Render, configuration, backup and recovery |
| [User & demo guide](docs/12-user-demo-guide.md) | Using the synthetic demo |
| [Limitations & roadmap](docs/13-limitations-roadmap.md) | Verified limitations and future work |
| [Documentation coverage](docs/14-documentation-coverage.md) | Audit checklist and evidence map |
| [Architecture source](docs/architecture.mmd) | Editable Mermaid architecture diagram |

## Repository structure

```text
app/
├── main.py                 # FastAPI application, middleware, health/readiness
├── config.py               # Environment-driven configuration
├── db.py                   # SQLAlchemy engine and Alembic lifecycle
├── models.py               # Persistent entities and append-only guards
├── schemas.py              # Pydantic extraction contracts
├── enums.py                # Roles, sensitivity, claim/confidence states
├── security.py             # Passwords, CSRF and throttling
├── access.py               # Server-side clearance and visibility rules
├── web.py                  # Login and review routes
├── handover_web.py         # Handover and source routes
├── insights_web.py         # Conflicts and questions routes
├── handover.py             # Release/sign-off domain logic
├── questions.py            # Questions Before I Leave
├── conflicts.py            # Conflict detection and resolution
├── semantic.py             # Optional advisory semantic review
├── redaction.py            # Role-specific field redaction
├── verify.py               # Mechanical evidence verification
├── ingest/                 # Source parsing, GitHub collection and redaction
└── extract/                # Rule and optional LLM extraction pipeline

data/demo/                 # Synthetic demonstration project
migrations/                 # Alembic migration history
tests/                     # Unit, integration, security, E2E and operational tests
scripts/                   # Operational helpers
.github/workflows/         # CI on SQLite and PostgreSQL
render.yaml                # Render deployment blueprint
docs/                      # Project documentation
```

## Status and verification

Latest GitHub Actions run recorded here (9 Nov 2026, commit `03a770b`): 481 tests passed on SQLite and
482 on PostgreSQL 16, and `pip-audit` found no known vulnerabilities. That is a point-in-time result;
run `pytest` for the current state.

Not yet verified: the Render deployment has configuration but has not been confirmed as a live
deployment, and the LLM extraction paths have not been run against a live model (an opt-in test,
`LIVE_LLM_TEST=1 pytest tests/test_live_llm.py`, exists for that).

## Known limitations

- Verification is mechanical text/evidence checking, not semantic proof.
- Sign-off becomes stale after an approved claim is edited, rejected or reopened.
- Live LLM quality has not been validated against a real provider in the documented test baseline.
- Render deployment is configured but not live-verified.
- GitHub ingestion is limited to public repositories and bounded recent/detail data.
- Secret detection and field redaction are pattern based and can produce false positives or miss unusual secrets.
- Conflict detection and checklist questions are rule based.
- One deployment currently supports one project.

See [Limitations & Roadmap](docs/13-limitations-roadmap.md) for the complete documented boundary.

## License

See [LICENSE](LICENSE).
