<div align="center">

<img src="assets/handover-logo.svg" alt="Handover" width="48" />

# 11 — Deployment & Operations

<sub>Handover · Product and engineering documentation</sub>

</div>

---

## 1. Render architecture

`render.yaml` describes:

- one Python web service named `handover`;
- a PostgreSQL database named `handover-db`;
- Python 3.12.7;
- `pip install -r requirements.lock` as build command;
- `uvicorn app.main:app --host 0.0.0.0 --port $PORT` as start command;
- `/health` as Render health check.

## 2. Production configuration

The blueprint sets:

- `APP_ENV=production`
- `TRUST_PROXY=true`
- `COOKIE_SECURE=true`
- generated `SECRET_KEY`
- `DEMO_MODE=true`
- a dashboard-supplied `DEMO_PASSWORD`
- PostgreSQL `DATABASE_URL` from the managed database.

The application itself additionally validates production settings and refuses unsafe combinations.

## 3. Startup migration behavior

By default `MIGRATE_ON_STARTUP=true`. Startup calls the database migration routine and upgrades to Alembic head.

When disabled, startup does not modify the schema and instead requires the database to already be current.

## 4. Health vs readiness

- `/health`: process liveness only.
- `/ready`: database reachable and migration state current.

Render is configured to use `/health`, so an operational deployment may need separate readiness monitoring if schema/database readiness is important to the operator.

## 5. Backup

The repository includes a backup/restore test and documents backup operations in its existing operational material. The core operational rule is: **take a database backup before destructive migration/downgrade or legacy-schema adoption.**

For PostgreSQL, use the normal `pg_dump`/`pg_restore` toolchain appropriate to the deployed database and retain credentials outside source control.

## 6. Restore validation

A backup is useful only if it can be restored. The repository includes `tests/test_backup_restore.py` and `scripts/restore_check.py` for verification of the restore path.

A production operator should test restoration against an isolated database before relying on a backup as a recovery plan.

## 7. Logging

Unexpected application exceptions are logged server-side with request method/path while the browser receives a generic error message.

Do not log API keys, passwords or raw secret material.

## 8. Operational limitations

- Render configuration exists but the repository documentation explicitly states that the live Render deployment has not been verified.
- In-memory request rate limiting is process-local.
- GitHub ingestion is subject to unauthenticated GitHub API limits.
- Live LLM behavior is not part of the ordinary deterministic CI baseline.

## 9. Troubleshooting

### Application refuses to start in production

Check:

```text
APP_ENV
SECRET_KEY
DATABASE_URL
COOKIE_SECURE
DEMO_PASSWORD (when DEMO_MODE=true)
```

### Migration error

Check:

```bash
python -m app.db status
```

If the database predates Alembic, use `adopt --dry-run` first and back up before adoption.

### `/ready` returns 503

The database may be unreachable or migrations may be behind. Inspect the application logs and migration state.

### Login fails after restart in development

If `SECRET_KEY` is not set, the application intentionally generates a temporary key and existing sessions end after restart.
