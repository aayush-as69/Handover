"""Real parallel requests against a real database (a SQLite file, or PostgreSQL when
TEST_DATABASE_URL is set). Threads wait at a barrier so they genuinely collide."""

import threading

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from app.config import _normalise_db_url
from app.enums import ClaimType, ReviewStatus, Role, SourceKind
from app.handover import (HandoverError, acknowledge, approve_handover, get_or_create_handover)
from app.ingest.service import ingest_source
from app.models import (Acknowledgement, Base, Claim, Handover, HandoverRelease, LoginAttempt,
                        Project, Source, User)
from app.security import login_blocked, record_login_failure
from tests.dbutil import PG_URL, on_postgres
from tests.test_round3 import add_claim

N = 8


@pytest.fixture()
def Session(tmp_path):
    if on_postgres():
        eng = create_engine(_normalise_db_url(PG_URL), pool_size=N + 2)
        Base.metadata.drop_all(eng)
        Base.metadata.create_all(eng)
    else:
        eng = create_engine(f"sqlite:///{tmp_path / 'c.db'}", connect_args={"timeout": 30})
        Base.metadata.create_all(eng)
    maker = sessionmaker(eng, expire_on_commit=False)
    with maker() as s:
        s.add(Project(name="P", outgoing_member="Riya"))
        s.commit()
    yield maker
    eng.dispose()


def race(Session, work, n=N):
    """Run work(session, i) in n threads at once. Returns (results, errors)."""
    barrier = threading.Barrier(n)
    results, errors = [None] * n, [None] * n

    def run(i):
        s = Session()
        try:
            results[i] = work(s, i, barrier)
        except Exception as exc:                  # collected, asserted on by each test
            errors[i] = exc
            s.rollback()
        finally:
            s.close()

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    [t.start() for t in threads]
    [t.join(60) for t in threads]
    return results, errors


def count(Session, model):
    with Session() as s:
        return s.scalar(select(func.count()).select_from(model))


def test_identical_uploads_at_the_same_moment_store_one_source(Session):
    content = "## Decisions\n- We will keep one datastore for everything here."

    def work(s, i, barrier):
        project = s.scalar(select(Project))
        barrier.wait()
        r = ingest_source(s, project, kind=SourceKind.notes, name=f"n{i}.md", content=content)
        s.commit()
        return r.duplicate

    results, errors = race(Session, work)
    assert errors == [None] * N
    assert count(Session, Source) == 1
    assert results.count(False) == 1 and results.count(True) == N - 1


def test_simultaneous_handover_creation_makes_one(Session):
    def work(s, i, barrier):
        project = s.scalar(select(Project))
        barrier.wait()
        h = get_or_create_handover(s, project)
        s.commit()
        return h.id

    results, errors = race(Session, work)
    assert errors == [None] * N and len(set(results)) == 1
    assert count(Session, Handover) == 1


def test_simultaneous_decisions_on_one_claim_cannot_both_win(Session):
    with Session() as s:
        cid = add_claim(s, s.scalar(select(Project)), "Use Redis for locks.").id
        s.commit()

    def work(s, i, barrier):
        claim = s.get(Claim, cid)
        barrier.wait()
        try:
            (claim.approve if i % 2 else claim.reject)(f"R{i}")
            s.commit()
            return True
        except (StaleDataError, IntegrityError):
            s.rollback()
            return False

    results, errors = race(Session, work)
    assert errors == [None] * N
    assert results.count(True) == 1                      # exactly one reviewer's decision landed
    with Session() as s:
        claim = s.get(Claim, cid)
        assert [v.version for v in claim.versions] == [1, 2]
        assert claim.version == 2 and claim.review_status in (ReviewStatus.approved, ReviewStatus.rejected)


def test_simultaneous_acknowledgements_record_once(Session):
    with Session() as s:
        project = s.scalar(select(Project))
        add_claim(s, project, "Use Redis for locks.", status=ReviewStatus.approved)
        boss = User(username="boss", display_name="Boss", role=Role.approver)
        reader = User(username="rd", display_name="Reader", role=Role.viewer)
        s.add_all([boss, reader])
        s.flush()
        approve_handover(s, get_or_create_handover(s, project), boss)
        s.commit()
        rid = reader.id

    def work(s, i, barrier):
        project = s.scalar(select(Project))
        h = get_or_create_handover(s, project)
        reader = s.get(User, rid)
        barrier.wait()
        got = acknowledge(s, h, reader)
        s.commit()
        return got

    results, errors = race(Session, work)
    assert errors == [None] * N
    assert count(Session, Acknowledgement) == 1 and results.count(True) <= 1


def test_simultaneous_sign_offs_get_distinct_release_numbers(Session):
    with Session() as s:
        project = s.scalar(select(Project))
        add_claim(s, project, "Use Redis for locks.", status=ReviewStatus.approved)
        s.add(User(username="boss", display_name="Boss", role=Role.approver))
        get_or_create_handover(s, project)               # created before the race, like in real use
        s.commit()

    def work(s, i, barrier):
        project = s.scalar(select(Project))
        h = get_or_create_handover(s, project)
        boss = s.scalar(select(User))
        barrier.wait()
        try:
            n = approve_handover(s, h, boss).number
            s.commit()
            return n
        except (HandoverError, IntegrityError):
            s.rollback()
            return None

    results, errors = race(Session, work, n=5)
    assert errors == [None] * 5
    numbers = [r for r in results if r]
    assert numbers and len(numbers) == len(set(numbers))
    with Session() as s:
        stored = sorted(r.number for r in s.scalars(select(HandoverRelease)))
    assert stored == sorted(numbers) and stored == list(range(1, len(stored) + 1))


def test_parallel_failed_logins_are_all_counted_and_lock_the_account(Session):
    def work(s, i, barrier):
        barrier.wait()
        record_login_failure(s, "meera")

    _, errors = race(Session, work, n=6)
    assert errors == [None] * 6
    with Session() as s:
        assert s.scalar(select(func.count()).select_from(LoginAttempt)) == 6
        assert login_blocked(s, "meera") and not login_blocked(s, "someone-else")
