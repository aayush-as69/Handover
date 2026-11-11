from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from .config import settings

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)

ROOT = Path(__file__).resolve().parents[1]


class MigrationError(RuntimeError):
    pass


def alembic_config(connection) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.attributes["connection"] = connection
    return cfg


def migrate(eng=None) -> None:
    """Bring the database to the latest schema. Safe to run on every start.

    A database that has tables but no migration history was made by an older build that
    created tables directly. It cannot be upgraded safely, so we stop with instructions
    instead of guessing.
    """
    eng = eng or engine
    with eng.begin() as conn:
        tables = set(inspect(conn).get_table_names())
        if tables and "alembic_version" not in tables:
            raise MigrationError(
                "This database was created before migrations existed. Back it up, then run "
                "`python -m app.db adopt` (see docs/OPERATIONS.md). Nothing was changed.")
        command.upgrade(alembic_config(conn), "head")


def _schema_differences(conn) -> list:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from .models import Base
    ctx = MigrationContext.configure(conn, opts={"compare_type": True})
    return compare_metadata(ctx, Base.metadata)


def adopt_legacy(eng=None, *, dry_run: bool = False) -> list[str]:
    """Bring a database made before migrations existed under Alembic's control.

    Only two situations are handled, both without touching existing data:
      * the schema already matches the models: it is stamped as the first migration;
      * whole tables are missing (an older build lacked them): they are created, then stamped.
    Any other difference (a missing or different column, index or constraint) is refused and
    listed, because guessing at those could lose data. Back up first.
    Returns a plain-language list of what was (or, with dry_run, would be) done.
    """
    from .models import Base

    eng = eng or engine
    with eng.begin() as conn:
        tables = set(inspect(conn).get_table_names())
        if not tables:
            raise MigrationError("The database is empty: nothing to adopt. Just start the app.")
        if "alembic_version" in tables:
            raise MigrationError("The database already has migration history: nothing to adopt.")
        diff = _schema_differences(conn)
        missing = [d[1].name for d in diff if d[0] == "add_table"]
        # Indexes of a missing table are created with it, so they are not separate differences.
        # A pre-migration database predates migration 0002. This known column is
        # intentionally absent until the database is stamped at 0001 and upgraded.
        post_0001_additions = {
            ("users", "session_version"),
        }
        other = [d for d in diff if d[0] != "add_table"
                 and not (d[0] == "add_index" and d[1].table.name in missing)
                 and not (d[0] == "add_column" and
                          (d[2], d[3].name) in post_0001_additions)]
        if other:
            raise MigrationError(
                "The schema differs from this version in ways that cannot be fixed safely "
                "(" + "; ".join(str(d)[:120] for d in other[:5]) + "). Restore from backup into a "
                "new database or migrate the data by hand. Nothing was changed.")
        done = [f"create missing table {name}" for name in missing] + [
            "mark the database as migration 0001"]
        if dry_run:
            return done
        if missing:
            Base.metadata.create_all(conn, tables=[Base.metadata.tables[n] for n in missing])
        command.stamp(alembic_config(conn), "0001")
        return done


def main(argv: list[str] | None = None) -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="python -m app.db")
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("adopt", help="put a pre-migration database under Alembic control")
    a.add_argument("--dry-run", action="store_true", help="show what would happen, change nothing")
    sub.add_parser("upgrade", help="apply migrations")
    d = sub.add_parser("downgrade", help="roll the schema back (data in dropped tables is lost)")
    d.add_argument("revision", help="target revision, e.g. base")
    d.add_argument("--yes", action="store_true", help="confirm you have a backup")
    sub.add_parser("status", help="show whether migrations are current")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "adopt":
            for line in adopt_legacy(dry_run=args.dry_run):
                print(("would: " if args.dry_run else "done: ") + line)
        elif args.cmd == "downgrade":
            if not args.yes:
                raise MigrationError("Refusing without --yes. Take a backup first.")
            downgrade(args.revision)
            print(f"rolled back to {args.revision}")
        elif args.cmd == "status":
            print(migration_state())
        else:
            migrate()
            print("database is up to date")
    except MigrationError as exc:
        raise SystemExit(f"error: {exc}") from None


def migration_state(eng=None) -> str:
    """'current', 'behind' (migrations pending) or 'unmigrated' (no history at all)."""
    from alembic.script import ScriptDirectory
    eng = eng or engine
    with eng.connect() as conn:
        if "alembic_version" not in set(inspect(conn).get_table_names()):
            return "unmigrated"
        from alembic.migration import MigrationContext
        have = MigrationContext.configure(conn).get_current_revision()
    head = ScriptDirectory(str(ROOT / "migrations")).get_current_head()
    return "current" if have == head else "behind"


def check_ready(eng=None) -> tuple[bool, str]:
    """For the readiness endpoint: can we reach the database, and is the schema up to date?
    The reason is a short fixed word, never an error message (which could expose internals)."""
    try:
        state = migration_state(eng)
    except Exception:  # noqa: BLE001 - any failure means "not ready"
        return False, "database unreachable"
    return (state == "current"), ("ready" if state == "current" else f"migrations {state}")


def downgrade(revision: str, eng=None) -> None:
    """Roll the schema back (see docs/OPERATIONS.md: take a backup first; data in dropped
    columns and tables is lost)."""
    eng = eng or engine
    with eng.begin() as conn:
        command.downgrade(alembic_config(conn), revision)


def init_db(upgrade: bool = True) -> None:
    """Start-up. With upgrade=False (MIGRATE_ON_STARTUP=false) the app never changes the schema:
    it refuses to start unless migrations were already applied by `python -m app.db upgrade`."""
    if upgrade:
        migrate()
        return
    state = migration_state()
    if state != "current":
        raise MigrationError(f"The database schema is {state}. Run `python -m app.db upgrade` "
                             "before starting, or set MIGRATE_ON_STARTUP=true.")


def get_session():
    """FastAPI dependency."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


if __name__ == "__main__":
    main()
