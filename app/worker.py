"""Run background jobs outside the web process.

    JOB_MODE=queue on the web service, then, as a separate process or service:
    python -m app.worker                 # run until stopped
    python -m app.worker --once          # drain the queue and exit (cron, tests)

Uses the same DATABASE_URL and the same LLM_* settings as the web service. Start as many
workers as needed; each job is claimed by exactly one.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import threading

from sqlalchemy.orm import sessionmaker

from . import jobs

log = logging.getLogger("handover.worker")


def work(factory: sessionmaker, worker: str, *, once: bool = False, poll: float = 2.0,
         stop: threading.Event | None = None, extractor_factory=None) -> int:
    """Claim and run jobs until the queue is empty (once) or `stop` is set. Returns jobs run."""
    stop = stop or threading.Event()
    ran = 0
    while not stop.is_set():
        with factory() as session:
            jobs.requeue_stale(session)
        job_id = jobs.claim_next(factory, worker)
        if job_id is None:
            if once:
                break
            stop.wait(poll)
            continue
        log.info("job %s claimed by %s", job_id, worker)
        jobs.execute(factory, job_id, extractor_factory)
        ran += 1
    return ran


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Handover background worker")
    ap.add_argument("--once", action="store_true", help="drain the queue, then exit")
    ap.add_argument("--poll", type=float, default=2.0, help="seconds between queue checks")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    from .db import SessionLocal, init_db
    from .config import settings
    init_db(settings.migrate_on_startup)
    name = f"{socket.gethostname()}-{os.getpid()}"
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    log.info("worker %s started", name)
    work(SessionLocal, name, once=args.once, poll=args.poll, stop=stop)
    log.info("worker %s stopped", name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
