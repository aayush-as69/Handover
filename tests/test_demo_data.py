"""The demo project is the ground truth for every later step. Keep it honest and consistent."""

import csv
import json
import re
from pathlib import Path

DEMO = Path(__file__).resolve().parents[1] / "data" / "demo"


def _json(name):
    return json.loads((DEMO / name).read_text(encoding="utf-8"))


def _text(rel):
    return (DEMO / rel).read_text(encoding="utf-8")


def test_manifest_lists_only_files_that_exist():
    manifest = _json("manifest.json")
    assert manifest["project"]["synthetic"] is True
    for src in manifest["sources"]:
        assert (DEMO / src["path"]).is_file(), src["path"]
    # and every file on disk is declared
    declared = {s["path"] for s in manifest["sources"]}
    on_disk = {p.relative_to(DEMO).as_posix() for p in DEMO.rglob("*") if p.is_file()}
    assert on_disk - declared == {"README.md", "manifest.json", "expected.json", "seeded_claims.json"}


def test_manifest_covers_every_role_and_source_kind():
    manifest = _json("manifest.json")
    assert {u["role"] for u in manifest["users"]} == {"admin", "approver", "viewer", "restricted"}
    assert {s["kind"] for s in manifest["sources"]} == {"notes", "chat", "tasks", "github"}


def test_exactly_one_task_has_no_owner():
    rows = list(csv.DictReader((DEMO / "tasks.csv").open(encoding="utf-8")))
    unowned = [r for r in rows if not r["owner"].strip()]
    assert [r["id"] for r in unowned] == ["T7"]
    assert unowned[0]["title"] == _json("expected.json")["seeded_traps"]["no_owner"]["title"]


def test_the_datastore_conflict_is_really_in_the_sources():
    trap = _json("expected.json")["seeded_traps"]["conflict"]
    assert trap["agreed"]["quote"] in _text(trap["agreed"]["source"])
    snapshot = _json("github_snapshot.json")
    commit = next(c for c in snapshot["commits"] if c["sha"] == trap["contradicted_by"][0]["sha"])
    assert trap["contradicted_by"][0]["quote"] in commit["message"]
    assert trap["contradicted_by"][1]["quote"] in _text("team_chat.txt")


def test_the_redis_decision_has_no_recorded_reason_anywhere():
    trap = _json("expected.json")["seeded_traps"]["no_reason"]
    notes = _text(trap["source"])
    assert trap["decision"] in notes
    decision_line = next(l for l in notes.splitlines() if trap["decision"] in l)
    assert "Reason" not in decision_line and "because" not in decision_line.lower()
    # No source gives a rationale for choosing Redis: it is only ever mentioned, never justified.
    everything = " ".join(
        [_text("team_chat.txt"), json.dumps(_json("github_snapshot.json"))]
        + [_text(p) for p in ("notes/2026-10-03_sprint_review.md",
                              "notes/2026-10-31_handover_planning.md")]
    )
    assert re.search(r"redis", everything, re.I)
    assert not re.search(r"redis.{0,60}(because|since|reason|so that)", everything, re.I)


def test_confidential_marker_exists_and_is_a_fake_credential():
    marker = _json("expected.json")["seeded_traps"]["confidential"][0]["marker"]
    assert marker in _text("team_chat.txt")
    assert "demo_" in marker  # clearly fake


def test_sponsor_note_is_labelled_confidential_in_the_manifest():
    manifest = _json("manifest.json")
    sponsor = next(s for s in manifest["sources"] if "sponsor" in s["path"])
    assert sponsor["sensitivity"] == "confidential"


def test_snapshot_shapes_are_consistent():
    snap = _json("github_snapshot.json")
    shas = [c["sha"] for c in snap["commits"]]
    assert len(shas) == len(set(shas))
    numbers = [i["number"] for i in snap["issues"]] + [p["number"] for p in snap["pulls"]]
    assert len(numbers) == len(set(numbers))  # issues and PRs share one numbering in GitHub


def test_no_real_looking_provider_secrets_in_demo_data():
    patterns = [r"AKIA[0-9A-Z]{16}", r"ghp_[A-Za-z0-9]{36}", r"sk_live_", r"sk_test_",
                r"xox[baprs]-", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"]
    for path in DEMO.rglob("*"):
        if path.is_file():
            body = path.read_text(encoding="utf-8")
            for pat in patterns:
                assert not re.search(pat, body), (path.name, pat)
