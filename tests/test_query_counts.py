"""Pages must not issue a query per claim (N+1). Counts are measured on the demo project."""
import re

import pytest
from sqlalchemy import event

from tests.test_web import PW, env, login  # noqa: F401


class Counter:
    def __init__(self, engine):
        self.n = 0
        event.listen(engine, "before_cursor_execute", self._hit)
        self.engine = engine

    def _hit(self, *a):
        self.n += 1

    def reset(self):
        self.n = 0


@pytest.fixture()
def counted(env):
    app, Session = env
    engine = Session.kw["bind"]
    c = Counter(engine)
    yield app, Session, c
    event.remove(engine, "before_cursor_execute", c._hit)


def measure(counter, client, path):
    counter.reset()
    r = client.get(path)
    assert r.status_code == 200, (path, r.status_code)
    return counter.n


def sign_off(client):
    html = client.get("/handover").text
    tok = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    # approve every verified claim first through the model layer is overkill; sign off as-is
    client.post("/handover/approve", data={"csrf": tok})


PAGES = ["/review?status=all", "/conflicts", "/questions", "/handover", "/handover/releases"]


@pytest.mark.parametrize("path", PAGES)
def test_page_query_count_is_small_and_flat(counted, path):
    app, Session, counter = counted
    c = login(app, "meera")
    sign_off(c)
    small = measure(counter, c, path)
    assert small <= 25, f"{path} used {small} queries"


def add_many(Session, n):
    """n more approved claims, half of them in disagreement with each other, some answerable."""
    from app.conflicts import detect_conflicts
    from app.enums import ReviewStatus
    from app.models import Project
    from app.questions import generate_questions
    from tests.test_conflicts_questions import add_claim
    from sqlalchemy import select
    with Session() as s:
        project = s.scalar(select(Project))
        for i in range(n):
            tech = "MongoDB" if i % 2 else "PostgreSQL"
            add_claim(s, project, f"Service {i} uses {tech} as the datastore.", topic=f"store-{i // 2}",
                      value=tech, status=ReviewStatus.approved)
        detect_conflicts(s, project)
        generate_questions(s, project)
        s.commit()


@pytest.mark.parametrize("path", PAGES)
def test_query_count_does_not_grow_with_the_number_of_claims(counted, path):
    app, Session, counter = counted
    c = login(app, "meera")
    add_many(Session, 20)                      # reach the steady state first (conflicts exist, etc.)
    sign_off(c)
    before = measure(counter, c, path)
    add_many(Session, 60)
    sign_off(c)
    after = measure(counter, c, path)
    assert after <= before + 2, f"{path}: {before} queries -> {after} after adding 60 claims"
