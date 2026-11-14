"""Back up a PostgreSQL database, restore it into a new one, and prove the copy is faithful.

    python scripts/restore_check.py postgresql://user:pass@host:5432/handover
    python scripts/restore_check.py postgresql://... --smoke     # also start the app on the restored copy

Steps: pg_dump (custom format) -> create a scratch database -> pg_restore -> compare every
table's row count and a checksum of its contents -> check the restored schema is current ->
(with --smoke) boot the app against the copy and request /ready and /login ->
drop the scratch database. Exits non-zero on any difference. Needs pg_dump and pg_restore.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import _normalise_db_url  # noqa: E402
from app.db import migration_state  # noqa: E402


def fingerprint(engine) -> dict[str, tuple[int, str]]:
    out = {}
    with engine.connect() as conn:
        for table in sorted(inspect(conn).get_table_names()):
            rows = conn.execute(text(f'SELECT * FROM "{table}"')).fetchall()
            digest = hashlib.sha256(repr(sorted(map(repr, rows))).encode()).hexdigest()
            out[table] = (len(rows), digest)
    return out


def pg_args(url) -> list[str]:
    args = ["-h", url.host or "localhost", "-p", str(url.port or 5432), "-U", url.username or "postgres"]
    return args


def run(cmd, url) -> None:
    # Use client tools of the same major version as the server (set PG_BIN to their directory):
    # a newer pg_dump writes settings an older server rejects when restoring.
    bindir = os.environ.get("PG_BIN")
    if bindir:
        cmd = [str(Path(bindir) / cmd[0]), *cmd[1:]]
    env = {"PGPASSWORD": url.password or "", "PATH": "/usr/bin:/usr/local/bin:/bin"}
    subprocess.run(cmd, check=True, env=env)


SMOKE = """
import sys
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
with TestClient(create_app(secret_key="restore-check-not-a-real-key-0123456789", config=Settings())) as c:
    ready, login = c.get("/ready"), c.get("/login")
    print("  /ready", ready.status_code, "  /login", login.status_code)
    sys.exit(0 if ready.status_code == 200 and login.status_code == 200 else 1)
"""


def smoke(target) -> bool:
    """Start the application against the restored copy, the way a real recovery would."""
    env = {**os.environ, "DATABASE_URL": target.render_as_string(False), "APP_ENV": "development",
           "MIGRATE_ON_STARTUP": "false", "DEMO_MODE": "false"}
    root = Path(__file__).resolve().parent.parent
    return subprocess.run([sys.executable, "-c", SMOKE], env=env, cwd=root).returncode == 0


def main(source: str, check_schema: bool = True, run_smoke: bool = False) -> int:
    url = make_url(source.replace("postgres://", "postgresql://", 1))
    scratch = f"restore_check_{uuid.uuid4().hex[:8]}"
    target = url.set(database=scratch)
    admin = create_engine(_normalise_db_url(url.set(database="postgres").render_as_string(False)),
                          isolation_level="AUTOCOMMIT")
    dump = Path(tempfile.mkdtemp()) / "backup.dump"
    try:
        run(["pg_dump", "--format=custom", "--no-owner", *pg_args(url), "-d", url.database, "-f", str(dump)], url)
        print(f"backup written: {dump.stat().st_size} bytes")
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{scratch}"'))
        run(["pg_restore", "--no-owner", *pg_args(url), "-d", scratch, str(dump)], url)
        src_engine = create_engine(_normalise_db_url(url.render_as_string(False)))
        dst_engine = create_engine(_normalise_db_url(target.render_as_string(False)))
        a, b = fingerprint(src_engine), fingerprint(dst_engine)
        bad = [t for t in a if a[t] != b.get(t)] + [t for t in b if t not in a]
        for t in sorted(a):
            print(f"  {t:24} rows {a[t][0]:>5}  {'same' if t not in bad else 'DIFFERENT'}")
        state = migration_state(dst_engine)
        print(f"restored schema: {state}")
        if bad or (check_schema and state != "current"):
            print("RESTORE CHECK FAILED", bad or state)
            return 1
        if run_smoke and not smoke(target):
            print("RESTORE CHECK FAILED: the application did not start on the restored copy")
            return 1
        print("restore check passed: every table matches" + (" and the app starts on the copy" if run_smoke else ""))
        return 0
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        raise SystemExit(__doc__)
    # --no-schema-check: for test databases built without migrations
    raise SystemExit(main(args[0], check_schema="--no-schema-check" not in sys.argv,
                          run_smoke="--smoke" in sys.argv))
