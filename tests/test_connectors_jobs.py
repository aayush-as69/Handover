"""Slack export and Jira CSV readers, and background extraction jobs."""

import json
from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import jobs
from app.enums import ClaimType
from app.extract.base import ExtractionError, ExtractorOutput
from app.schemas import EvidenceIn, ExtractedClaim, ExtractionResult
from app.ingest.errors import IngestError
from app.ingest.parsers import parse_chat, parse_tasks
from app.models import Chunk, Claim, Job, Project
from tests.test_web import client, env, login, token  # noqa: F401

import pytest


SLACK = json.dumps([
    {"ts": "1762246860.000100", "user": "U1", "user_profile": {"real_name": "Rahul"},
     "text": "Seat locks moved to Redis"},
    {"ts": "1762247000", "user": "U2", "subtype": "channel_join", "text": "joined"},
    {"ts": "not-a-number", "user_name": "neha", "text": "Webhook owner is still unclear"},
])


def test_slack_export_keeps_channel_author_and_time():
    r = parse_chat(SLACK, "backend.json")
    assert [c.author for c in r.chunks] == ["Rahul", "neha"]
    assert r.chunks[0].locator.startswith("Slack #backend message 1 (04 Nov")
    assert r.chunks[0].occurred_at is not None
    assert r.chunks[1].occurred_at is None and r.warnings   # bad timestamp: kept, but flagged


def test_slack_export_without_messages_is_refused_and_plain_chat_still_works():
    with pytest.raises(IngestError):
        parse_chat(json.dumps([{"ts": "1", "text": "", "subtype": "channel_join"}]), "x.json")
    assert parse_chat("[04/11/2026, 09:01] Riya: hello", "chat.txt").chunks[0].author == "Riya"


def test_jira_export_columns_are_mapped_and_dated():
    csv_text = ("Issue key,Summary,Assignee,Status,Due date,Updated\n"
                "PAY-1,Fix webhook,Neha,In Progress,15/Nov/26,04/Nov/26 2:21 PM\n")
    c = parse_tasks(csv_text, "jira.csv").chunks[0]
    assert c.text.startswith("PAY-1: Fix webhook | owner: Neha | status: In Progress")
    assert c.occurred_at.year == 2026 and c.occurred_at.hour == 14
    with pytest.raises(IngestError):
        parse_tasks("Foo,Bar\n1,2\n", "x.csv")


class Good:
    name, remote = "scripted", False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract(self, chunks):
        ch = chunks[0]
        claim = ExtractedClaim(statement="A claim from the model", type=ClaimType.decision,
                               evidence=[EvidenceIn(chunk_id=ch.id, snippet=ch.text[:20])])
        return ExtractorOutput(ExtractionResult(claims=[claim]), [])


class Broken(Good):
    def extract(self, chunks):
        raise ExtractionError("model unreachable")


class Crashing(Good):
    def extract(self, chunks):
        raise RuntimeError("secret detail that must not be shown")


def _job(Session):
    with Session() as s:
        project = s.scalar(select(Project))
        job = jobs.create_job(s, project, "extract_llm", "meera")
        s.commit()
        return job.id


def test_job_runs_to_done_and_records_the_result(env):
    app, Session = env
    jid = _job(Session)
    with Session() as s:
        before = len(list(s.scalars(select(Claim))))
    jobs.run_job(Session, jid, lambda: Good())
    with Session() as s:
        job = s.get(Job, jid)
        assert job.status == "done" and job.claims_created == 1 and job.finished_at
        assert len(list(s.scalars(select(Claim)))) == before + 1


def test_failed_job_is_reported_without_leaking_internals(env):
    app, Session = env
    jid = _job(Session)
    jobs.run_job(Session, jid, lambda: Broken())
    jid2 = _job(Session)
    jobs.run_job(Session, jid2, lambda: Crashing())
    with Session() as s:
        assert s.get(Job, jid).status == "failed" and "unreachable" in s.get(Job, jid).message
        j2 = s.get(Job, jid2)
        assert j2.status == "failed" and "secret detail" not in j2.message


def test_jobs_left_active_by_a_restart_are_marked_failed(env):
    app, Session = env
    jid = _job(Session)
    with Session() as s:
        assert jobs.recover_interrupted(s) == 1
        assert s.get(Job, jid).status == "failed"
        assert jobs.recover_interrupted(s) == 0


def test_llm_extract_route_starts_one_job_and_refuses_a_second(env, monkeypatch):
    app, Session = env
    started = []
    monkeypatch.setattr(jobs, "start_thread", lambda factory, job_id: started.append(job_id))
    import app.handover_web as hw
    monkeypatch.setattr(hw, "llm_from_env", lambda: Good())
    c = login(app, "riya")
    t = token(c, "/admin/sources")
    r = c.post("/admin/sources/extract", data={"csrf": t, "engine": "llm"}, follow_redirects=True)
    assert r.status_code == 200 and "started in the background" in r.text
    assert len(started) == 1
    r = c.post("/admin/sources/extract", data={"csrf": t, "engine": "llm"}, follow_redirects=True)
    assert "already running" in r.text and len(started) == 1
    assert "Background runs" in c.get("/admin/sources").text
