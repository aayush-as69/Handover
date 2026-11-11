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

## 8. Shared rate limiting at the edge

The application limiter is deliberately retained as a lightweight per-process fallback. It cannot enforce a shared quota across Render instances. For a public deployment, route a custom domain through a CDN or reverse proxy that supports shared rate limiting, such as Cloudflare.

Configure edge rules for:
- `POST /login`: strict per-client-IP rate limiting with a short mitigation window;
- other dynamic application routes: a broader per-IP limit;
- `/health` and static assets: exempt or use a separate, higher limit.

Do not rely on the direct `*.onrender.com` address as the public URL when enforcing a Cloudflare rule; traffic should enter through the proxied custom domain. Confirm the origin sees the correct client address. Keep `TRUST_PROXY=true` only when the app is reachable exclusively through the trusted Render proxy chain; the app uses the last appended forwarded address and ignores the untrusted prefix. Never use a client-controlled forwarding value as a trust signal.

The repository cannot install Cloudflare rules in the Render account. Treat edge throttling as a deployment checklist item and verify it against the public custom domain before production use.

## 9. Audit and credential guarantees

Claim versions, verification audit events, handover releases, and stored evidence are protected by database triggers as well as ORM guards. Verification may update only the derived `evidence.snippet_verified` flag. A database owner can still disable triggers or rewrite the database, so use least-privilege credentials and retain independent backups.

Authenticated cookies carry the user's `session_version`. Password rotation increments it, invalidating cookies with the previous version. Future credential-reset paths must use `set_user_password()` rather than assigning `password_hash` directly. Hosted demo startup synchronizes `DEMO_PASSWORD` to synthetic demo accounts; changing it rotates those sessions.

## 10. Data volume and ingestion bounds

The review queue already performs filtering, counting and pagination in SQL, returning 50 claims per page. GitHub commits, issues, pull requests and pull-request detail collections are fetched in bounded pages; detailed collections stop at 200 entries and deep details are limited to the newest configured pull requests/commits. The GitHub API remains unauthenticated by default and subject to its rate limits.

Conflict, question and release-history pages still load project-level working sets. Add database-backed pagination to those views before onboarding projects with very large histories.

## 11. Accessibility and responsive QA

Browser coverage checks the login flow on a 390px viewport, verifies accessible names on the sign-in controls and asserts that the page does not overflow horizontally. These automated checks are not a substitute for manual assistive-technology testing. Before release, complete keyboard-only navigation and a screen-reader walkthrough with NVDA on Windows or VoiceOver on macOS/iOS. Check focus order, visible focus, error announcements, form labels, table navigation and reduced-motion behavior.

The global stylesheet remains in place to avoid an unreviewed visual regression during the security work. Keep new component rules grouped by page/component and split the file only alongside visual regression coverage for both light and dark themes.

## 12. Operational limitations

- Render configuration exists but the live Render deployment has not been verified from this repository.
- Shared edge throttling requires CDN/proxy configuration by the deployment operator; the in-memory limiter alone is not distributed.
- Conflict, question and release-history views still need database pagination for very large projects.
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
