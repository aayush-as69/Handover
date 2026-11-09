# Operations

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
Lockout is 5 failed sign-ins in 5 minutes per username, and 20 per client address; both clear themselves.
Set `TRUST_PROXY=true` only behind a proxy that appends the client address (Render does). To clear a username at once,
delete its rows (`key = 'u:<username>'`, or `'ip:<address>'`) from `login_attempts`.
