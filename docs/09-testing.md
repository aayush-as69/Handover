<div align="center">

<img src="assets/handover-logo.svg" alt="Handover" width="56" />

# 09 — Testing Guide

<sub>Handover · Product and engineering reference</sub>

</div>

> [Documentation index](README.md) · [Project home](../README.md)

---

## 1. Test strategy

The repository has tests spanning unit logic, database behavior, web/API behavior, security, ingestion, extraction, verification, concurrency, deployment configuration, migrations, backup/restore and browser E2E.

## 2. Test inventory

| Area | Relevant tests |
|---|---|
| Access/clearance | `test_access.py`, `test_sql_access.py` |
| Web/API | `test_web.py`, `test_api.py` |
| Backup/restore | `test_backup_restore.py` |
| Browser E2E | `test_browser_e2e.py` |
| Concurrency | `test_concurrency.py` |
| Configuration | `test_config.py` |
| Conflicts/questions | `test_conflicts_questions.py` |
| Demo fixtures | `test_demo_data.py` |
| Deployment | `test_deploy.py`, `test_readiness_and_deploy_ops.py` |
| Extraction | `test_extract.py`, `test_llm_validation.py`, `test_live_llm.py` |
| Failures | `test_failures.py` |
| GitHub ingestion | `test_github_detail.py` |
| Handover lifecycle | `test_handover.py` |
| Ingestion | `test_ingest.py` |
| Integrity | `test_integrity.py`, `test_models.py` |
| Migrations | `test_migrations.py` |
| Query scaling | `test_query_counts.py` |
| Redaction/secret defense | `test_redaction_adversarial.py`, `test_secret_patterns.py` |
| Semantic review | `test_semantic.py` |
| Throttling | `test_throttle_ip.py` |
| Verification | `test_verify.py` |

## 3. Local commands

Install exact locked dependencies:

```bash
pip install -r requirements.lock -r requirements-dev.txt
```

Run the default SQLite suite:

```bash
python -m pytest -q
```

Run a focused area:

```bash
python -m pytest -q tests/test_access.py
python -m pytest -q tests/test_verify.py
python -m pytest -q tests/test_ingest.py
python -m pytest -q tests/test_handover.py
```

## 4. PostgreSQL suite

Set `TEST_DATABASE_URL` to a PostgreSQL database, for example:

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/handover_test python -m pytest -q
```

The CI workflow provisions PostgreSQL 16 and runs the full suite against both SQLite and PostgreSQL.

## 5. Browser tests

The development dependencies include Playwright. CI installs Chromium with:

```bash
python -m playwright install --with-deps chromium
```

The browser suite is skipped when Chromium is unavailable in environments that do not provide it.

## 6. Live LLM test

`tests/test_live_llm.py` is opt-in. A live model/provider run should be treated separately from simulated-provider tests.

Do not report a live LLM evaluation as passed unless the current environment actually executed it against a real provider.

## 7. CI

`.github/workflows/ci.yml` runs on pushes and pull requests and currently performs:

1. Python 3.12 setup.
2. Locked dependency installation.
3. Playwright/Chromium installation.
4. SQLite tests.
5. PostgreSQL 16 tests.
6. `pip-audit` against `requirements.lock`.

## 8. Historical evidence rule

The repository README records a historical CI result of 481 SQLite tests and 482 PostgreSQL tests on 9 Nov 2026. That is historical evidence, not a substitute for executing the current suite after future changes.

## 9. Feature traceability

| Feature | Implementation | Verification |
|---|---|---|
| Authentication | `app/web.py`, `app/security.py` | `test_web.py`, `test_failures.py`, `test_throttle_ip.py` |
| Role clearance | `app/access.py` | `test_access.py`, `test_sql_access.py` |
| Source ingestion | `app/ingest/` | `test_ingest.py` |
| Secret masking | `app/ingest/redact.py` | `test_secret_patterns.py`, `test_redaction_adversarial.py` |
| Rule extraction | `app/extract/rules.py` | `test_extract.py` |
| LLM validation | `app/extract/llm.py`, `app/schemas.py` | `test_llm_validation.py`, `test_live_llm.py` |
| Evidence verification | `app/verify.py` | `test_verify.py` |
| Claim lifecycle | `app/models.py`, `app/web.py` | `test_models.py`, `test_handover.py` |
| Conflict/question workflows | `app/conflicts.py`, `app/questions.py` | `test_conflicts_questions.py` |
| Release/acknowledgement | `app/handover.py` | `test_handover.py` |
| Concurrency | ORM/domain logic | `test_concurrency.py`, integrity tests |
| Migrations | `app/db.py`, `migrations/` | `test_migrations.py` |
| Backup/restore | operational scripts | `test_backup_restore.py` |
| Deployment/readiness | `render.yaml`, `app/main.py` | `test_deploy.py`, `test_readiness_and_deploy_ops.py` |
| Browser flow | server-rendered UI | `test_browser_e2e.py` |


---

[← Documentation index](README.md) · [Project home](../README.md)

## Performance benchmark

`python scripts/benchmark.py --sizes 100 1000 10000` builds a synthetic project of each size in a temporary database, signs in through the real login form and times a GET of the pages that read the most data, with the number of SQL statements each ran. CI runs `--sizes 300 --budget 5` as a loose guard against gross regressions or a per-claim query. It is a timing aid, not a load test: one user, one process. Results and what they mean are in [13 — Limitations](13-limitations-roadmap.md). Use a disposable database if you point it at PostgreSQL.
