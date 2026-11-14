"""Background jobs: slow extraction runs off the web request.

Two ways to run them, chosen by JOB_MODE:

* `thread` (default) - one worker thread per job inside the web process. Right for a demo or a
  single small instance and needs nothing extra. A job does not survive a restart (see
  `recover_interrupted`), and two instances do not share work.
* `queue` - the web process only writes a `queued` row. One or more separate worker processes
  (`python -m app.worker`) claim rows from the same database, run them and keep a heartbeat.
  A worker that dies leaves a stale heartbeat and `requeue_stale` puts its job back. The
  database is the queue, so no broker is needed; claiming is one atomic UPDATE, safe with
  several workers on SQLite or PostgreSQL.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from . import metrics
from .conflicts import detect_conflicts
from .extract.base import ExtractionError
from .extract.llm import llm_from_env
from .extract.pipeline import run_extraction
from .models import Job, Project
from .questions import generate_questions

ACTIVE = ("queued", "running")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def active_job(session: Session, project_id: int, kind: str) -> Job | None:
    return session.scalar(select(Job).where(Job.project_id == project_id, Job.kind == kind,
                                            Job.status.in_(ACTIVE)))


def create_job(session: Session, project: Project, kind: str, who: str) -> Job:
    job = Job(project_id=project.id, kind=kind, created_by=who)
    session.add(job)
    session.flush()
    return job


STALE_AFTER = timedelta(minutes=2)        # a running job with no heartbeat for this long is orphaned
HEARTBEAT_EVERY = 15                      # seconds


def claim(factory: sessionmaker, job_id: int, worker: str) -> bool:
    """Atomically move one job from queued to running. False if someone else got it first."""
    with factory() as session:
        n = session.execute(update(Job).where(Job.id == job_id, Job.status == "queued").values(
            status="running", started_at=_now(), heartbeat_at=_now(), claimed_by=worker)).rowcount
        session.commit()
        return bool(n)


def claim_next(factory: sessionmaker, worker: str) -> int | None:
    """Claim the oldest queued job, or None when the queue is empty."""
    for _ in range(5):                    # another worker may win the race; try the next one
        with factory() as session:
            job_id = session.scalar(select(Job.id).where(Job.status == "queued").order_by(Job.id).limit(1))
        if job_id is None:
            return None
        if claim(factory, job_id, worker):
            return job_id
    return None


def _beat(factory: sessionmaker, job_id: int, stop: threading.Event) -> None:
    while not stop.wait(HEARTBEAT_EVERY):
        with factory() as session:
            session.execute(update(Job).where(Job.id == job_id, Job.status == "running")
                            .values(heartbeat_at=_now()))
            session.commit()


def run_job(factory: sessionmaker, job_id: int, extractor_factory=None, worker: str = "web") -> None:
    """Claim a queued job and run it to the end. Never raises: the outcome is written on the row."""
    if claim(factory, job_id, worker):
        execute(factory, job_id, extractor_factory)


def execute(factory: sessionmaker, job_id: int, extractor_factory=None) -> None:
    """Run a job that is already claimed (status running). Never raises."""
    extractor_factory = extractor_factory or llm_from_env
    stop = threading.Event()
    threading.Thread(target=_beat, args=(factory, job_id, stop), daemon=True,
                     name=f"beat-{job_id}").start()
    try:
        _execute(factory, job_id, extractor_factory)
    finally:
        stop.set()


def _execute(factory: sessionmaker, job_id: int, extractor_factory) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        try:
            project = session.get(Project, job.project_id)
            with extractor_factory() as extractor:
                report = run_extraction(session, project, extractor)
            detect_conflicts(session, project)
            generate_questions(session, project)
            job.chunks_total = report.chunks_sent
            job.claims_created = report.claims_created
            job.message = (f"{report.claims_created} new draft claims, "
                           f"{report.duplicates_skipped} duplicates skipped.")
            job.status = "done"
        except ExtractionError as exc:
            session.rollback()
            job = session.get(Job, job_id)
            job.status, job.message = "failed", f"Extraction failed: {exc}"[:500]
        except Exception as exc:  # a worker thread must report, not die silently
            session.rollback()
            if isinstance(exc, SQLAlchemyError):
                metrics.inc("handover_db_errors_total", where="job")
            job = session.get(Job, job_id)
            job.status, job.message = "failed", f"Unexpected error: {type(exc).__name__}"
        job.finished_at = _now()
        session.commit()


def start_thread(factory: sessionmaker, job_id: int) -> None:
    threading.Thread(target=run_job, args=(factory, job_id), daemon=True,
                     name=f"job-{job_id}").start()


def dispatch(factory: sessionmaker, job_id: int, mode: str) -> str:
    """Hand a created job to whoever runs it. Returns a short phrase for the confirmation message."""
    if mode == "queue":
        return "queued for the background worker"
    start_thread(factory, job_id)
    return "started in the background"


def requeue_stale(session: Session, now: datetime | None = None) -> int:
    """Put running jobs whose worker stopped sending heartbeats back in the queue."""
    cutoff = (now or _now()) - STALE_AFTER
    n = session.execute(update(Job).where(
        Job.status == "running", (Job.heartbeat_at.is_(None)) | (Job.heartbeat_at < cutoff)).values(
        status="queued", claimed_by=None, heartbeat_at=None,
        message="Worker stopped; job was put back in the queue.")).rowcount
    session.commit()
    return n or 0


def recover_interrupted(session: Session) -> int:
    """At startup: no worker survives a restart, so anything still active did not finish."""
    n = session.execute(update(Job).where(Job.status.in_(ACTIVE)).values(
        status="failed", finished_at=_now(),
        message="Interrupted by a server restart. Run it again.")).rowcount
    session.commit()
    return n or 0
