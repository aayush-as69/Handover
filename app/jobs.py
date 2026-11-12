"""Background jobs: slow extraction runs off the web request.

One worker thread per job inside the web process. That is enough for a single instance and
keeps the project free of a queue service, but it is not a distributed queue: a job does not
survive a restart (see `recover_interrupted`), and two instances do not share work.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

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


def run_job(factory: sessionmaker, job_id: int, extractor_factory=None) -> None:
    """Run one job to the end. Never raises: the outcome is written on the job row."""
    extractor_factory = extractor_factory or llm_from_env
    with factory() as session:
        job = session.get(Job, job_id)
        job.status, job.started_at = "running", _now()
        session.commit()
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
            job = session.get(Job, job_id)
            job.status, job.message = "failed", f"Unexpected error: {type(exc).__name__}"
        job.finished_at = _now()
        session.commit()


def start_thread(factory: sessionmaker, job_id: int) -> None:
    threading.Thread(target=run_job, args=(factory, job_id), daemon=True,
                     name=f"job-{job_id}").start()


def recover_interrupted(session: Session) -> int:
    """At startup: no worker survives a restart, so anything still active did not finish."""
    n = session.execute(update(Job).where(Job.status.in_(ACTIVE)).values(
        status="failed", finished_at=_now(),
        message="Interrupted by a server restart. Run it again.")).rowcount
    session.commit()
    return n or 0
