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
Lockout limits (per 5 minutes): 5 failures per account and address, 20 per account, 15 different accounts from one address, 100 failures from one address. They clear themselves.
Set `TRUST_PROXY=true` only behind a proxy that appends the client address (Render does). To clear a username at once,
delete its rows (`key = 'u:<username>'`, `'ip:<address>'`, or keys starting `'ipu:<address>|'`) from `login_attempts`.

## Rate limiting
The app limits each address to `RATE_LIMIT_PER_MIN` requests (default 300) and `LOGIN_RATE_PER_MIN`
login posts (default 30) a minute, returning 429. The counters live in each server process, so with
several processes the effective limit is higher. For real protection put a rate limiter in front
(Cloudflare, or your host's edge rules) and keep `TRUST_PROXY=true` so addresses are read correctly.
