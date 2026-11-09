# Operations

## Configuration
Set `APP_ENV=production`. The server then refuses to start unless `SECRET_KEY` is 32+ characters,
cookies are secure, and `DATABASE_URL` is PostgreSQL. API docs are disabled. With `DEMO_MODE=1`,
`DEMO_PASSWORD` must be 10+ characters and not a common password.

## Migrations
Alembic runs at startup. A database with tables but no `alembic_version` is refused. To adopt
such a database, back it up, then `alembic stamp 0001` if its schema matches the initial migration.

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
5. Practise this restore once before relying on it.

## Locked-out users
Lockout is 5 failed sign-ins in 5 minutes per username and clears itself. To clear it at once,
delete that username's rows from `login_attempts`.
