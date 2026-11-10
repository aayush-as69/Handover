

def test_seeded_examples_cover_every_confidence_label_and_are_idempotent(session):
    from collections import Counter
    from sqlalchemy import select
    from app.demo import load_demo_project, seed_review_examples
    from app.extract.pipeline import run_extraction
    from app.extract.rules import RuleExtractor
    from app.models import Claim
    project = load_demo_project(session)
    run_extraction(session, project, RuleExtractor())
    assert seed_review_examples(session, project) == 4
    assert seed_review_examples(session, project) == 0
    seeded = session.scalars(select(Claim).where(Claim.extractor == "demo-seed")).all()
    assert Counter(c.confidence.value for c in seeded) == {"inferred": 2, "conflicting": 1, "unsupported": 1}
    assert all(c.review_status.value == "generated" for c in seeded)
