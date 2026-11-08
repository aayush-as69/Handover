import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.enums import ClaimType, Sensitivity, SourceKind
from app.models import Base, Chunk, Claim, Evidence, Project, Source


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(engine, expire_on_commit=False)()
    yield s
    s.close()


@pytest.fixture()
def project(session):
    p = Project(name="CampusEvents", outgoing_member="Riya Sharma")
    session.add(p)
    session.commit()
    return p


@pytest.fixture()
def demo_project(session):
    from app.demo import load_demo_project

    p = load_demo_project(session)
    session.commit()
    return p


def make_claim(session, project, *, claim_sens=Sensitivity.team, chunk_sens=Sensitivity.team,
               source_sens=Sensitivity.team, statement="Seat locks use Redis"):
    """A claim backed by one chunk, with independent sensitivity labels at each level."""
    source = Source(project_id=project.id, kind=SourceKind.notes, name="n.md",
                    sensitivity=source_sens)
    chunk = Chunk(source=source, idx=0, text="Seat locks will go in Redis.",
                  locator="line 1", sensitivity=chunk_sens)
    claim = Claim.create(project_id=project.id, statement=statement,
                         type=ClaimType.decision, sensitivity=claim_sens)
    claim.evidence.append(Evidence(chunk=chunk, snippet="Seat locks will go in Redis"))
    session.add_all([source, chunk, claim])
    session.commit()
    return claim
