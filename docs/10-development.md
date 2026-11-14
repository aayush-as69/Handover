<div align="center">

<img src="assets/handover-logo.svg" alt="Handover" width="48" />

# 10 — Development Setup

<sub>Handover · Product and engineering documentation</sub>

</div>

---

## 1. Prerequisites

- Python 3.12 recommended (the CI/deployment target).
- Git.
- Optional PostgreSQL 16 for production-like local testing.
- Optional Chromium/Playwright for browser E2E.

## 2. Windows PowerShell

```powershell
git clone https://github.com/aayush-as69/Handover.git
cd Handover
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.lock -r requirements-dev.txt
```

Run:

```powershell
pytest
python -m app.demo
python -m app.demo --extract rules
uvicorn app.main:app --reload
```

## 3. Linux/macOS

```bash
git clone https://github.com/aayush-as69/Handover.git
cd Handover
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.lock -r requirements-dev.txt
```

## 4. Dependency files

| File | Meaning |
|---|---|
| `requirements.txt` | Direct runtime dependencies with minimum versions |
| `requirements.lock` | Exact resolved runtime versions used for reproducible installation/deployment |
| `requirements-dev.txt` | Runtime requirements plus testing/development tools |

For reproducible development, install the lock file together with development requirements.

## 5. Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `APP_ENV` | no | `development` by default; `production` enables strict validation |
| `DATABASE_URL` | no | Database URL; SQLite is the local default, PostgreSQL required in production |
| `SECRET_KEY` | production | Session signing secret; production requires 32+ characters |
| `COOKIE_SECURE` | production behavior | Controls secure session cookie behavior; production cannot disable it |
| `TRUST_PROXY` | deployment-dependent | Trust final `X-Forwarded-For` entry behind a trusted proxy |
| `DEMO_MODE` | no | Enables hosted demo bootstrap |
| `DEMO_PASSWORD` | with demo mode | Password for demo users |
| `MIGRATE_ON_STARTUP` | no | Defaults to true; when false startup requires current migrations |
| `RATE_LIMIT_PER_MIN` | no | In-memory general request limit; `0` disables it |
| `LOGIN_RATE_PER_MIN` | no | In-memory login POST limit; `0` disables it |
| `LLM_BASE_URL` | optional | OpenAI-compatible provider base URL |
| `LLM_API_KEY` | optional | Provider key; never commit it |
| `LLM_MODEL` | optional | Provider model identifier |

## 6. Database commands

```bash
python -m app.db status
python -m app.db upgrade
```

The application can migrate on startup when `MIGRATE_ON_STARTUP=true`.

## 7. Demo

The demo is synthetic. `app.demo` loads the project and users from `data/demo/`. If `DEMO_PASSWORD` is supplied, demo users receive password hashes.

The documented demo usernames are:

- `meera` — approver
- `riya` — admin
- `kabir` — viewer
- `rao` — restricted

Choose the demo password yourself; do not publish a real production password.

## 8. Coding/documentation rules

- Keep business logic out of templates.
- Keep access rules centralized in `app/access.py`.
- Treat model output as untrusted input.
- Add tests for security/integrity-sensitive behavior.
- Do not weaken fail-closed behavior for convenience.
- Update documentation when behavior changes.

## 9. Tech stack

| Layer | Technology |
|---|---|
| Runtime | Python 3.12 |
| Web | FastAPI, Uvicorn, Jinja2 |
| Data | SQLAlchemy 2, SQLite, PostgreSQL |
| Validation | Pydantic |
| Migrations | Alembic |
| Extraction | Rule-based pipeline, optional OpenAI-compatible provider |
| Repository ingestion | GitHub REST API |
| Testing | Pytest, HTTPX, Playwright |
| Deployment | Render blueprint (`render.yaml`) |
| CI | GitHub Actions: SQLite, PostgreSQL 16, browser tests, `pip-audit` |

## 10. Repository map

```text
Handover/
├── app/
│   ├── extract/          # Rule and optional LLM extraction, verification input
│   ├── ingest/           # Parsers (notes, chat, Slack, Jira, tasks), GitHub collection, secret redaction
│   ├── templates/        # Server-rendered HTML
│   ├── static/           # Stylesheet and small scripts (no inline scripts: CSP)
│   ├── throttle.py       # Request rate limiter and login lockout (the one throttling module)
│   ├── metrics.py        # Counters, latency histogram, JSON access log
│   ├── jobs.py, worker.py  # Background jobs: thread mode or queue + worker
│   └── *.py              # Routes, domain logic, models, access rules
├── data/demo/            # Synthetic demonstration project
├── data/eval/            # Labelled set for extraction quality
├── docs/                 # Product and engineering documentation, evaluation reports
├── migrations/           # Alembic history
├── scripts/              # Operational helpers
├── tests/                # Unit, integration, security, browser tests
│   └── evals/            # Evaluation fixtures and runner
├── .github/workflows/    # CI
└── render.yaml           # Render blueprint
```

## 11. Optional LLM extraction

The built-in extractor needs no key but reads only structured sources (notes, task files). To read chat, set an
OpenAI-compatible provider:

```bash
export LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
export LLM_API_KEY=<your-key>
export LLM_MODEL=<model-name>
python -m app.demo --extract llm
```

Keep keys in environment variables or a secrets manager; never commit them. Confidential chunks are withheld from
remote extraction by default, and anything a model writes back is passed through secret masking before it is saved.
Measure a provider with `python -m tests.evals.runner --engine llm` (see [18 — Evaluation](18-evaluation.md)).

## 12. Running the tests

```bash
python -m pytest -q                                   # everything except browser tests when Chromium is absent
python -m playwright install chromium
python -m pytest -q tests/test_browser_e2e.py         # browser walkthrough
TEST_DATABASE_URL=postgresql://... python -m pytest -q   # against a disposable PostgreSQL database
```
