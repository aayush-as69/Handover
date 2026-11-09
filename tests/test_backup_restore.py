"""Backup and restore round trip (PostgreSQL only; skipped on SQLite or without pg_dump)."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.dbutil import PG_URL, on_postgres

pytestmark = pytest.mark.skipif(
    not (on_postgres() and shutil.which("pg_dump") and shutil.which("pg_restore")),
    reason="needs TEST_DATABASE_URL (PostgreSQL) and pg_dump/pg_restore")


def test_dump_and_restore_reproduces_every_table(session, project):
    session.commit()
    script = Path(__file__).parent.parent / "scripts" / "restore_check.py"
    r = subprocess.run([sys.executable, str(script), PG_URL], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "restore check passed" in r.stdout
