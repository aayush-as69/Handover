<div align="center">

<img src="assets/handover-logo.svg" alt="Handover" width="48" />

# Operations

<sub>Handover · Product and engineering documentation</sub>

</div>

---

## Configuration
Set `APP_ENV=production`. The server then refuses to start unless `SECRET_KEY` is 32+ characters,
cookies are secure, and `DATABASE_URL` is PostgreSQL. API docs are disabled. With `DEMO_MODE=1`,
`DEMO_PASSWORD` must be 10+ characters and not a common password.

## Migrations
Alembic runs at startup. A database with tables but no `alembic_version` (made by an older
build) is refused with instructions. To adopt it:
1. Back it up (see Backups).
2. `python -m app.db adopt --dry-run` shows what would happen and changes nothing.
3. `python -m app.db adopt` stamps a matching schema as migration 0001, or creates tables the
   older build lacked and then stamps. If a column, index or constraint differs it stops,
   lists the difference and changes nothing; restore into a new database instead.
4. Start the app normally.

## Two deployments: demo and production
`render.yaml` is the free **demo** blueprint: `DEMO_MODE=true`, synthetic accounts, one shared demo
password you type into the dashboard. `render.production.yaml` is the **real** one: demo mode off,
`JOB_MODE=queue` with a separate worker service (`python -m app.worker`), a paid Postgres with
backups, `/ready` as the health check, `autoDeploy` off and a generated `METRICS_TOKEN`. Keep them as
separate Render projects so synthetic data and credentials never reach a real environment.

With the demo off nobody exists yet. Create the first admin from the web service's shell, then add
the rest in the app (Projects) or the same way:

    python -m app.users create --username you --name "Your Name" --role admin
    python -m app.users set-password --username you      # also signs them out everywhere
    python -m app.users list

The password is asked for on the terminal (or read from `NEW_USER_PASSWORD`), never taken as an
argument. Minimum 10 characters, no common passwords.

The worker does not migrate (`MIGRATE_ON_STARTUP=false`): the web service owns the schema. On the very
first deploy the worker may restart a few times until the web service has finished migrating.

## Backups
- Render free Postgres has no automatic backups and expires; for anything real use a paid plan
  with backups.
- Manual: `pg_dump --format=custom "$DATABASE_URL" > handover-$(date +%F).dump`
- Take a dump before every deploy that includes a migration.

## Recovery
1. Create an empty database.
2. `pg_restore --no-owner --dbname "$NEW_DATABASE_URL" handover-YYYY-MM-DD.dump`
3. Point `DATABASE_URL` at it and restart. Startup checks the migration version.
4. Log in and open `/handover/releases` to confirm releases and acknowledgements are intact.
5. Practise this restore before relying on it. `python scripts/restore_check.py <DATABASE_URL>`
   does the whole exercise for you: dumps the database, restores it into a scratch database,
   compares the row count and a checksum of every table, confirms the schema is current, and
   deletes the scratch copy. It exits non-zero on any difference. Use `pg_dump`/`pg_restore` of the same major version as the
   database (set `PG_BIN` to their folder): a newer client writes settings an older server rejects.

### Recovery drill (run it, do not just read it)
1. Backup: `pg_dump --format=custom "$DATABASE_URL" > handover-$(date +%F).dump` (the paid database also keeps its own daily backups).
2. Restore into an isolated database, never over production.
3. Check the schema: `DATABASE_URL=<restored> python -m app.db status` should say current.
4. Check the application: start it against the restored copy and request `/ready`.
5. Smoke test: sign in, open `/handover/releases`, and compare the claim and release counts with production.

`python scripts/restore_check.py <DATABASE_URL> --smoke` performs steps 1 to 4 and compares every table.
`.github/workflows/backup-check.yml` runs it weekly against the database named by the repository secret
`BACKUP_CHECK_DATABASE_URL` (a no-op while the secret is unset). The database user needs permission to
create a scratch database; if the host does not allow that, run the drill from a machine that can reach
a separate PostgreSQL server instead.

Exercised on 9 Nov 2026 against a local PostgreSQL 16 holding the demo project: all 15 tables
matched (48 claims, 87 chunks, 48 claim versions, 48 audit events and the rest) and the restored
schema was current. It has **not** been run on Render's database; do that once after deploying.

## Locked-out users
Lockout limits (per 5 minutes): 5 failures per account and address, 20 per account, 15 different accounts from one address, 100 failures from one address. They clear themselves.
Set `TRUST_PROXY=true` only behind a proxy that appends the client address (Render does). To clear a username at once,
delete its rows (`key = 'u:<username>'`, `'ip:<address>'`, or keys starting `'ipu:<address>|'`) from `login_attempts`.

## Rate limiting
The app limits each address to `RATE_LIMIT_PER_MIN` requests (default 300) and `LOGIN_RATE_PER_MIN`
login posts (default 30) a minute, returning 429. The counters live in each server process, so with
several processes the effective limit is higher. For real protection put a rate limiter in front
(Cloudflare, or your host's edge rules) and keep `TRUST_PROXY=true` so addresses are read correctly.
The sign-in lockout is different: it is stored in the database and is shared by every instance.
Moving the request limiter itself into a shared store (Redis) is only worth doing if you run several
web instances and cannot limit at the edge; `app/throttle.py` is the one place to change.

## Dependencies
`requirements.txt` lists minimum versions; `requirements.lock` pins every package to the exact
versions the tests ran against, and Render builds from it. To refresh: in a clean virtualenv run
`pip install pip-tools`, then `pip-compile --strip-extras --no-header --annotation-style=line
requirements.txt -o requirements.lock`, run the tests, and commit both. CI runs `pip-audit`.
The lock was verified by installing it into an empty virtualenv and running the suite there.

## Migrations at deployment
By default the app upgrades the schema when it starts (`MIGRATE_ON_STARTUP=true`), which suits
Render's free plan. For a controlled rollout set `MIGRATE_ON_STARTUP=false`, run
`python -m app.db upgrade` first (for example as a pre-deploy command), and the app then refuses
to start on a schema that is behind. `python -m app.db status` shows the state and
`python -m app.db downgrade <revision> --yes` rolls back (data in dropped tables is lost, so take
a backup first). `/health` is liveness; `/ready` also checks the database and schema (503 if not).

## Live LLM check
No model has been called yet in development. With any OpenAI-compatible provider (Gemini, OpenAI,
Groq, a local Ollama) run:
`LIVE_LLM_TEST=1 LLM_BASE_URL=... LLM_API_KEY=... LLM_MODEL=... python -m pytest tests/test_live_llm.py -v -s`
It sends one invented note and checks every quote the model cites exists word for word. For
Gemini, the base URL is `https://generativelanguage.googleapis.com/v1beta/openai`. Then run
`python -m app.demo --extract llm` to see the full pipeline and read the report it prints.
