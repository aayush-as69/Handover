"""Time the pages that read the most data, at several project sizes.

    python scripts/benchmark.py                          # 100 / 1,000 claims on a temporary SQLite file
    python scripts/benchmark.py --sizes 100 1000 10000
    python scripts/benchmark.py --sizes 1000 --budget 3  # exit 1 if any page takes longer than 3 s
    DATABASE_URL=postgresql://... python scripts/benchmark.py --sizes 1000   # a disposable database only

It builds a synthetic project (claims with quotes, conflicts, an approved release), signs in as an
approver through the real login form, and times a GET of each page plus how many SQL statements it ran.
The numbers show where time goes as a project grows; they are not a load test (one user, one process).
Use a disposable database: this script writes thousands of rows.
"""
from __future__ import annotations

import argparse
import os
import re
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PAGES = ["/review?status=all", "/review/bulk", "/conflicts", "/questions", "/search?q=cache", "/inbox",
         "/freshness", "/bus-factor", "/handover", "/handover/brief", "/handover/releases", "/audit"]
PASSWORD = "benchmark-" + "pass-123"


def seed(session, n_claims: int):
    from app.conflicts import detect_conflicts
    from app.enums import ClaimType, Confidence, Sensitivity, SourceKind, Stance
    from app.handover import get_or_create_handover
    from app.models import Chunk, Claim, Evidence, Project, ProjectMember, Source, User
    from app.security import set_user_password

    user = User(username="bench", display_name="Bench Approver", role="approver")
    set_user_password(user, PASSWORD)
    project = Project(name="Benchmark project", outgoing_member="Dev Patel")
    session.add_all([user, project])
    session.flush()
    session.add(ProjectMember(project_id=project.id, user_id=user.id, added_by="benchmark"))
    types = [t for t in ClaimType]
    sens = [Sensitivity.public, Sensitivity.team, Sensitivity.team, Sensitivity.restricted]
    sources, chunks = [], []
    for i in range(max(1, n_claims // 25)):
        src = Source(project_id=project.id, kind=SourceKind.notes, name=f"notes-{i}.md", sensitivity=Sensitivity.team)
        sources.append(src)
        for j in range(5):
            chunks.append(Chunk(source=src, idx=j, text=f"Section {i}.{j}: the cache is Redis and runs on box {i}. "
                                f"Decision {i}.{j} was agreed with owner {i % 40}.", sensitivity=Sensitivity.team))
    session.add_all(sources + chunks)
    session.flush()
    claims = []
    for k in range(n_claims):
        chunk = chunks[k % len(chunks)]
        claim = Claim.create(project_id=project.id, statement=f"Decision {k}: the cache is Redis on box {k % 97}.",
                             type=types[k % len(types)], created_by="benchmark", sensitivity=sens[k % 4],
                             topic=f"cache-{k % 60}", value=f"box {k % 97}", owner=f"owner {k % 40}",
                             confidence=Confidence.verified, extractor="rules")
        claim.evidence.append(Evidence(chunk=chunk, snippet="the cache is Redis", stance=Stance.supports,
                                       snippet_verified=True))
        claims.append(claim)
    session.add_all(claims)
    session.flush()
    for claim in claims[::2]:
        claim.approve("bench", "benchmark")
    session.commit()
    detect_conflicts(session, project)
    get_or_create_handover(session, project)
    session.commit()
    return project


def timings(client, path: str, repeat: int, counter) -> tuple[float, int, int]:
    best, queries, status = [], 0, 0
    for _ in range(repeat):
        counter[0] = 0
        t = time.perf_counter()
        r = client.get(path)
        best.append(time.perf_counter() - t)
        queries, status = counter[0], r.status_code
    return statistics.median(best), queries, status


def run(n_claims: int, repeat: int) -> list[tuple[str, float, int, int]]:
    from fastapi.testclient import TestClient
    from sqlalchemy import event
    from app.config import Settings
    from app.db import SessionLocal, engine, init_db
    from app.main import create_app

    init_db(True)
    with SessionLocal() as session:
        seed(session, n_claims)
    counter = [0]
    event.listen(engine, "before_cursor_execute", lambda *a: counter.__setitem__(0, counter[0] + 1))
    app = create_app(secret_key="benchmark-key-not-for-production-0123456789", config=Settings())
    with TestClient(app, follow_redirects=False) as c:
        tok = re.search(r'name="csrf" value="([^"]+)"', c.get("/login").text).group(1)
        r = c.post("/login", data={"username": "bench", "password": PASSWORD, "csrf": tok})
        assert r.status_code == 303, "benchmark login failed"
        return [(p, *timings(c, p, repeat, counter)) for p in PAGES]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sizes", type=int, nargs="+", default=[100, 1000])
    ap.add_argument("--repeat", type=int, default=3, help="requests per page; the median is reported")
    ap.add_argument("--budget", type=float, help="fail if any page takes longer than this many seconds")
    args = ap.parse_args()
    worst = 0.0
    for n in args.sizes:
        # each size gets a clean database so numbers are comparable
        with tempfile.TemporaryDirectory() as tmp:
            if not os.environ.get("DATABASE_URL"):
                os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/bench.db"
                local = True
            else:
                local = False
            import importlib
            for mod in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
                del sys.modules[mod]
            importlib.invalidate_caches()
            t0 = time.perf_counter()
            rows = run(n, args.repeat)
            print(f"\n{n:,} claims (seeded and measured in {time.perf_counter() - t0:.1f} s)")
            print(f"{'page':<24}{'median s':>10}{'queries':>9}  status")
            for page, sec, q, status in rows:
                worst = max(worst, sec)
                flag = "  <-- over budget" if args.budget and sec > args.budget else ""
                print(f"{page:<24}{sec:>10.3f}{q:>9}  {status}{flag}")
            if local:
                os.environ.pop("DATABASE_URL")
    if args.budget and worst > args.budget:
        print(f"\nFAILED: slowest page {worst:.2f} s is over the {args.budget} s budget")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
