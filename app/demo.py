"""Load the synthetic CampusEvents demo project.

    python -m app.demo

Safe to run twice: the project, users and sources are only created once.
"""

from __future__ import annotations

import argparse
import json
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

DEMO_DIR = Path(__file__).resolve().parents[1] / "data" / "demo"


def load_demo_project(session: Session, demo_dir: Path = DEMO_DIR) -> Project:
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
        if session.scalar(select(User).where(User.username == u["username"])) is None:
            session.add(User(username=u["username"], display_name=u["display_name"],
                             role=Role(u["role"])))

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Load the synthetic demo project")
    parser.add_argument(
        "--extract", choices=["rules", "llm"],
        help="also extract draft claims (llm needs LLM_BASE_URL, LLM_API_KEY, LLM_MODEL)",
    )
    args = parser.parse_args()

    init_db()
    with SessionLocal() as session:
        project = load_demo_project(session)
        session.commit()
        print(f"Project: {project.name} (id {project.id})\n")
        print(f"{'source':44} {'kind':8} {'sensitivity':13} {'chunks':>6} {'masked':>6}")
        for src in project.sources:
            masked = sum(c.redacted for c in src.chunks)
            print(f"{src.name:44} {src.kind.value:8} {src.sensitivity.value:13} "
                  f"{len(src.chunks):>6} {masked:>6}")

        if args.extract:
            try:
                extractor = RuleExtractor() if args.extract == "rules" else llm_from_env()
                report = run_extraction(session, project, extractor)
            except ExtractionError as exc:
                raise SystemExit(f"Extraction failed: {exc}")
            session.commit()
            print(f"\nExtraction with {report.extractor}: {report.claims_created} claims created, "
                  f"{report.duplicates_skipped} duplicates skipped, "
                  f"{report.dropped_no_evidence} dropped (no valid evidence)")
            for w in report.warnings:
                print(f"  note: {w}")


if __name__ == "__main__":
    main()
