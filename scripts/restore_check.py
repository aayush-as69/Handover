"""Back up a PostgreSQL database, restore it into a new one, and prove the copy is faithful.

    python scripts/restore_check.py postgresql://user:pass@host:5432/handover

Steps: pg_dump (custom format) -> create a scratch database -> pg_restore -> compare every
table's row count and a checksum of its contents -> check the restored schema is current ->
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


def main(source: str) -> int:
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
        if bad or state != "current":
            print("RESTORE CHECK FAILED", bad or state)
            return 1
        print("restore check passed: every table matches")
        return 0
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    raise SystemExit(main(sys.argv[1]))
