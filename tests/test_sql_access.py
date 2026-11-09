"""The SQL version of the access rule must agree with the Python rule on every combination."""
import itertools

from sqlalchemy import select

from app.access import effective_rank_sql, effective_sensitivity, sensitivity_from_rank
from app.enums import ClaimType, Sensitivity, SourceKind
from app.models import Chunk, Claim, Evidence, Source


def test_sql_rank_matches_python_for_every_combination(session, project):
    claims = []
    for own, chunk, source in itertools.product(list(Sensitivity), repeat=3):
        src = Source(project_id=project.id, kind=SourceKind.notes, name="n.md", sensitivity=source)
        ch = Chunk(source=src, idx=0, text="t", locator="l", sensitivity=chunk)
        c = Claim.create(project_id=project.id, statement=f"{own}/{chunk}/{source}",
                         type=ClaimType.decision, sensitivity=own)
        c.evidence.append(Evidence(chunk=ch, snippet="t"))
        session.add_all([src, ch, c])
        claims.append(c)
    # a claim with no evidence, and one with two pieces of evidence at different levels
    bare = Claim.create(project_id=project.id, statement="bare", type=ClaimType.decision,
                        sensitivity=Sensitivity.restricted)
    two = Claim.create(project_id=project.id, statement="two", type=ClaimType.decision,
                       sensitivity=Sensitivity.public)
    for lvl in (Sensitivity.team, Sensitivity.confidential):
        src = Source(project_id=project.id, kind=SourceKind.notes, name="m.md", sensitivity=Sensitivity.public)
        ch = Chunk(source=src, idx=0, text="t", locator="l", sensitivity=lvl)
        two.evidence.append(Evidence(chunk=ch, snippet="t"))
        session.add_all([src, ch])
    session.add_all([bare, two])
    session.commit()
    session.expire_all()

    rows = {c.id: r for c, r in session.execute(select(Claim, effective_rank_sql()))}
    assert len(rows) == 64 + 2
    for c in session.scalars(select(Claim)):
        assert sensitivity_from_rank(rows[c.id]) == effective_sensitivity(c), c.statement
