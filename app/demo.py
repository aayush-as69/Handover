"""Load the synthetic CampusEvents demo project.

    python -m app.demo

Safe to run twice: the project, users and sources are only created once.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import SessionLocal, init_db
from .enums import Role, Sensitivity, SourceKind
from .extract import ExtractionError
from .extract.llm import llm_from_env
from .extract.pipeline import run_extraction
from .extract.rules import RuleExtractor
from .ingest.service import ingest_source
from .models import Project, User
from .security import set_user_password

DEMO_DIR = Path(__file__).resolve().parents[1] / "data" / "demo"


def load_demo_project(session: Session, demo_dir: Path = DEMO_DIR,
                      password: str | None = None) -> Project:
    """Create the demo project. With a password, demo users can log in (otherwise they cannot)."""
    manifest = json.loads((demo_dir / "manifest.json").read_text(encoding="utf-8"))
    info = manifest["project"]

    project = session.scalar(select(Project).where(Project.name == info["name"]))
    if project is None:
        project = Project(
            name=info["name"],
            description=info["description"],
            outgoing_member=info["outgoing_member"],
        )
        session.add(project)
        session.flush()

    for u in manifest["users"]:
        user = session.scalar(select(User).where(User.username == u["username"]))
        if user is None:
            user = User(username=u["username"], display_name=u["display_name"],
                        role=Role(u["role"]))
            session.add(user)
        if password:
            set_user_password(user, password)

    for s in manifest["sources"]:
        ingest_source(
            session,
            project,
            kind=SourceKind(s["kind"]),
            name=Path(s["path"]).name,
            content=(demo_dir / s["path"]).read_text(encoding="utf-8"),
            sensitivity=Sensitivity(s["sensitivity"]),
            origin="demo",
        )
    session.flush()
    return project


def seed_review_examples(session: Session, project: Project, demo_dir: Path = DEMO_DIR) -> int:
    """Add a few deliberately weak draft claims so the demo shows every confidence label.

    They are marked as demo-seed claims and go through the same verifier as any other claim;
    their labels are computed, not written. Safe to call repeatedly.
    """
    from .enums import ClaimType, Stance
    from .extract.pipeline import _higher
    from .models import Chunk, Claim, Evidence, Source
    from .verify import verify_claims

    path = demo_dir / "seeded_claims.json"
    if not path.exists():
        return 0
    have = set(session.scalars(select(Claim.statement).where(
        Claim.project_id == project.id, Claim.extractor == "demo-seed")))
    created = []
    for item in json.loads(path.read_text(encoding="utf-8")):
        if item["statement"] in have:
            continue
        chunk = session.scalars(select(Chunk).join(Source).where(
            Source.project_id == project.id, Source.name == Path(item["source"]).name,
            Chunk.text.contains(item["anchor"]))).first()
        if chunk is None:
            continue
        claim = Claim.create(
            project_id=project.id, statement=item["statement"], type=ClaimType(item["type"]),
            created_by="demo-seed", topic=item.get("topic"), sensitivity=_higher(
                Sensitivity.team, chunk.sensitivity), extractor="demo-seed")
        claim.evidence.append(Evidence(chunk_id=chunk.id, snippet=item["quote"],
                                       stance=Stance(item["stance"])))
        session.add(claim)
        created.append(claim)
    session.flush()
    verify_claims(created)
    return len(created)


def bootstrap_demo(session: Session, password: str) -> None:
    """For a hosted demo: load the project, draft claims and an empty handover once.

    Nothing is approved here. A reviewer still has to do that.
    """
    from .conflicts import detect_conflicts
    from .handover import get_or_create_handover
    from .questions import generate_questions
    from .models import Claim

    project = load_demo_project(session, password=password)
    # The hosted demo password is deployment configuration. Keep only these synthetic users
    # aligned with it; changing the environment variable rotates their sessions too.
    manifest = json.loads((DEMO_DIR / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["users"]:
        user = session.scalar(select(User).where(User.username == item["username"]))
        if user is not None:
            set_user_password(user, password)
    if session.scalar(select(Claim.id).where(Claim.project_id == project.id)) is None:
        run_extraction(session, project, RuleExtractor())
    seed_review_examples(session, project)
    detect_conflicts(session, project)
    generate_questions(session, project)
    get_or_create_handover(session, project)
    session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Load the synthetic demo project")
    parser.add_argument(
        "--extract", choices=["rules", "llm"],
        help="also extract draft claims (llm needs LLM_BASE_URL, LLM_API_KEY, LLM_MODEL)",
    )
    args = parser.parse_args()

    init_db()
    with SessionLocal() as session:
        project = load_demo_project(session, password=os.environ.get("DEMO_PASSWORD"))
        session.commit()
        print(f"Project: {project.name} (id {project.id})\n")
        print(f"{'source':44} {'kind':8} {'sensitivity':13} {'chunks':>6} {'masked':>6}")
        for src in project.sources:
            masked = sum(c.redacted for c in src.chunks)
            print(f"{src.name:44} {src.kind.value:8} {src.sensitivity.value:13} "
                  f"{len(src.chunks):>6} {masked:>6}")

        if args.extract:
            try:
                if args.extract == "rules":
                    report = run_extraction(session, project, RuleExtractor())
                else:
                    with llm_from_env() as extractor:
                        report = run_extraction(session, project, extractor)
            except ExtractionError as exc:
                raise SystemExit(f"Extraction failed: {exc}") from None
            if args.extract == "rules":
                seed_review_examples(session, project)
            session.commit()
            print(f"\nExtraction with {report.extractor}: {report.claims_created} claims created, "
                  f"{report.duplicates_skipped} duplicates skipped, "
                  f"{report.dropped_no_evidence} dropped (no valid evidence)")
            print("  confidence: " + ", ".join(
                f"{n} {label}" for label, n in sorted(report.confidence_counts.items())))
            for w in report.warnings:
                print(f"  note: {w}")


if __name__ == "__main__":
    main()
