import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.access import chunk_visible
from app.demo import load_demo_project
from app.enums import Role, Sensitivity, SourceKind
from app.ingest import IngestError
from app.ingest.github import fetch_public_repo
from app.ingest.parsers import (
    MAX_CHUNK_CHARS,
    parse_chat,
    parse_github,
    parse_notes,
    parse_tasks,
)
from app.ingest.redact import redact
from app.ingest.service import MAX_BYTES, decode_upload, ingest_github_repo, ingest_source
from app.models import Chunk, Source, User

DEMO = Path(__file__).resolve().parents[1] / "data" / "demo"


def read(rel: str) -> str:
    return (DEMO / rel).read_text(encoding="utf-8")


# Fake credentials are assembled at runtime so this file never contains a full token.
FAKE_SECRETS = {
    "aws_key": "AK" "IAIOSFODNN7EXAMPLE",
    "github_token": "gh" "p_" + "a" * 36,
    "stripe_key": "sk_" "live_" + "b" * 20,
    "slack_token": "xo" "xb-1234567890-abcdef",
}


# ------------------------------------------------------------ redaction


def test_assignment_style_secret_is_masked():
    r = redact("sandbox payment key for testing: api_key = demo_live_8f3a91c2d7e04b65a1f0 (do NOT commit this)")
    assert "demo_live_8f3a" not in r.text
    assert r.text == (
        "sandbox payment key for testing: api_key = [REDACTED:secret] (do NOT commit this)"
    )
    assert r.kinds == ["secret"]


@pytest.mark.parametrize("kind", list(FAKE_SECRETS))
def test_provider_tokens_are_masked(kind):
    r = redact(f"here you go {FAKE_SECRETS[kind]} thanks")
    assert FAKE_SECRETS[kind] not in r.text
    assert f"[REDACTED:{kind}]" in r.text
    assert r.kinds == [kind]


def test_private_key_block_is_masked():
    block = "-----BEGIN RSA " "PRIVATE KEY-----\nabc123\n-----END RSA " "PRIVATE KEY-----"
    r = redact(f"before\n{block}\nafter")
    assert "abc123" not in r.text
    assert r.kinds == ["private_key"]


def test_ordinary_text_is_left_alone():
    text = "We need passwords or access sorted before Monday. The token bucket limit is fine."
    r = redact(text)
    assert r.text == text
    assert not r.redacted


# ------------------------------------------------------------ notes


def test_notes_split_by_section_and_carry_the_meeting_date():
    res = parse_notes(read("notes/2026-09-05_kickoff.md"), "kickoff.md")
    headings = [c.locator.split(" › ")[1] for c in res.chunks]
    assert headings == [
        "CampusEvents: Kickoff meeting", "Goal", "Decisions", "Open questions", "Next actions",
    ]
    assert all(c.occurred_at == datetime(2026, 9, 5) for c in res.chunks)
    decisions = next(c for c in res.chunks if c.locator.endswith("Decisions"))
    assert "## Decisions" in decisions.text and "Backend in FastAPI" in decisions.text


def test_long_sections_are_split_without_losing_text():
    body = "## Big\n" + "word " * 1000
    res = parse_notes(body, "big.md")
    assert len(res.chunks) > 1
    assert all(len(c.text) <= MAX_CHUNK_CHARS for c in res.chunks)
    assert "(part 2)" in res.chunks[1].locator
    assert "".join("".join(c.text.split()) for c in res.chunks) == "".join(body.split())


def test_notes_without_a_date_have_no_timestamp_and_empty_notes_are_rejected():
    assert parse_notes("## A\nhello", "n.md").chunks[0].occurred_at is None
    with pytest.raises(IngestError):
        parse_notes("   \n\n", "n.md")


# ------------------------------------------------------------ chat


def test_chat_has_one_chunk_per_message_with_author_and_time():
    raw = read("team_chat.txt")
    res = parse_chat(raw, "team_chat.txt")
    assert len(res.chunks) == len([l for l in raw.splitlines() if l.strip()])
    first = res.chunks[0]
    assert first.author == "Meera Iyer"
    assert first.occurred_at == datetime(2026, 9, 6, 10, 2)
    assert first.locator == "team_chat.txt line 1"
    assert res.warnings == []


def test_chat_lines_without_a_timestamp_continue_the_previous_message():
    raw = "[06/09/2026, 10:02] A: first line\nsecond line\n[06/09/2026, 10:03] B: ok"
    res = parse_chat(raw, "c.txt")
    assert [c.text for c in res.chunks] == ["first line\nsecond line", "ok"]


def test_chat_month_first_dates_are_detected():
    raw = "[09/25/2026, 10:02] A: hi\n[09/26/2026, 10:03] B: yo"
    assert parse_chat(raw, "c.txt").chunks[0].occurred_at == datetime(2026, 9, 25, 10, 2)


def test_chat_junk_before_the_first_message_is_skipped_with_a_warning():
    res = parse_chat("Messages are end-to-end encrypted\n[06/09/2026, 10:02] A: hi", "c.txt")
    assert len(res.chunks) == 1
    assert "line 1" in res.warnings[0]


def test_text_that_is_not_a_chat_is_rejected():
    with pytest.raises(IngestError):
        parse_chat("hello world", "c.txt")


# ------------------------------------------------------------ tasks


def test_tasks_become_one_chunk_per_row_and_a_blank_owner_is_made_explicit():
    res = parse_tasks(read("tasks.csv"), "tasks.csv")
    assert len(res.chunks) == 11
    t7 = next(c for c in res.chunks if "(T7)" in c.locator)
    assert t7.text.startswith("T7: QR check-in at the venue | owner: UNASSIGNED")
    assert res.warnings == []


def test_task_file_errors_are_clear():
    with pytest.raises(IngestError, match="missing required column"):
        parse_tasks("name,owner\nx,y\n", "t.csv")
    with pytest.raises(IngestError, match="no task rows"):
        parse_tasks("id,title\n,\n", "t.csv")
    res = parse_tasks("id,title\nT1,a\nT1,b\n", "t.csv")
    assert "duplicate task id T1" in res.warnings[0]


# ------------------------------------------------------------ github


def test_snapshot_becomes_dated_chunks_in_time_order():
    res = parse_github(read("github_snapshot.json"), "snap")
    assert len(res.chunks) == 12 + 6 + 4
    dates = [c.occurred_at for c in res.chunks]
    assert dates == sorted(dates)
    mongo = next(c for c in res.chunks if c.locator == "commit 7c2e8d1")
    assert "add mongo event feed prototype" in mongo.text
    issue5 = next(c for c in res.chunks if c.locator == "issue #5")
    assert "Assignees: none." in issue5.text


def test_bad_github_files_are_rejected():
    with pytest.raises(IngestError, match="valid JSON"):
        parse_github("not json", "x")
    with pytest.raises(IngestError, match="at least one of"):
        parse_github('{"hello": 1}', "x")
    with pytest.raises(IngestError, match="no commits"):
        parse_github('{"commits": []}', "x")


def _github_handler(private=False):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/repos/o/r":
            return httpx.Response(200, json={"private": private})
        if path == "/repos/o/r/commits":
            return httpx.Response(200, json=[{
                "sha": "abcdef1234567",
                "commit": {"author": {"name": "A", "date": "2026-10-01T10:00:00Z"},
                           "message": "first line\n\nlong body"},
            }])
        if path == "/repos/o/r/issues":
            return httpx.Response(200, json=[
                {"number": 1, "title": "bug", "state": "open", "user": {"login": "a"},
                 "assignees": [], "created_at": "2026-10-02T10:00:00Z", "body": None},
                {"number": 2, "title": "a pr", "pull_request": {}, "user": {"login": "a"},
                 "created_at": "2026-10-02T11:00:00Z"},
            ])
        if path == "/repos/o/r/pulls":
            return httpx.Response(200, json=[
                {"number": 2, "title": "a pr", "state": "closed",
                 "merged_at": "2026-10-03T00:00:00Z", "user": {"login": "a"},
                 "created_at": "2026-10-02T11:00:00Z", "body": "x"},
            ])
        return httpx.Response(404)
    return handler


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_public_repo_fetch_normalises_to_the_snapshot_shape():
    snap = fetch_public_repo("o", "r", client=_client(_github_handler()))
    assert snap["commits"][0]["sha"] == "abcdef1"
    assert snap["commits"][0]["message"] == "first line"
    assert [i["number"] for i in snap["issues"]] == [1]      # the PR is not double counted
    assert snap["pulls"][0]["state"] == "merged"
    assert len(parse_github(json.dumps(snap), "o/r").chunks) == 3


def test_private_missing_limited_and_malformed_repos_are_refused():
    with pytest.raises(IngestError, match="public"):
        fetch_public_repo("o", "r", client=_client(_github_handler(private=True)))
    with pytest.raises(IngestError, match="not found"):
        fetch_public_repo("o", "missing", client=_client(_github_handler()))
    limited = _client(lambda req: httpx.Response(403, headers={"x-ratelimit-remaining": "0"}))
    with pytest.raises(IngestError, match="rate limit"):
        fetch_public_repo("o", "r", client=limited)
    with pytest.raises(IngestError, match="valid GitHub"):
        fetch_public_repo("../etc", "passwd")


def test_ingest_github_repo_stores_a_public_source(session, project):
    result = ingest_github_repo(session, project, "o", "r", client=_client(_github_handler()))
    assert result.source.sensitivity == Sensitivity.public
    assert result.source.origin == "https://github.com/o/r"
    assert result.chunk_count == 3


# ------------------------------------------------------------ service


def test_secret_is_masked_before_storage_and_marks_the_chunk_confidential(session, project):
    raw = "[11/10/2026, 16:20] Riya: key for testing: api_key = demo_live_8f3a91c2d7e04b65a1f0"
    result = ingest_source(session, project, kind=SourceKind.chat, name="c.txt", content=raw)
    session.commit()
    chunk = result.source.chunks[0]
    assert chunk.redacted and chunk.sensitivity == Sensitivity.confidential
    assert result.redacted_chunks == 1
    for text in session.scalars(select(Chunk.text)):
        assert "demo_live_8f3a" not in text      # never stored, anywhere


def test_same_content_is_not_ingested_twice(session, project):
    first = ingest_source(session, project, kind=SourceKind.notes, name="a.md", content="## A\nhi")
    again = ingest_source(session, project, kind=SourceKind.notes, name="renamed.md",
                          content="## A\nhi")
    assert again.duplicate and again.source.id == first.source.id
    assert len(session.scalars(select(Source)).all()) == 1


def test_bad_sources_leave_nothing_behind(session, project):
    with pytest.raises(IngestError):
        ingest_source(session, project, kind=SourceKind.tasks, name="t.csv", content="a,b\n1,2\n")
    with pytest.raises(IngestError, match="empty"):
        ingest_source(session, project, kind=SourceKind.notes, name="e.md", content="  \n")
    with pytest.raises(IngestError, match="larger"):
        ingest_source(session, project, kind=SourceKind.notes, name="big.md",
                      content="a" * (MAX_BYTES + 1))
    assert session.scalars(select(Source)).all() == []


def test_uploads_must_be_text():
    assert decode_upload("héllo".encode("utf-8")) == "héllo"
    assert decode_upload(b"\xef\xbb\xbfhi") == "hi"           # BOM from Windows editors
    with pytest.raises(IngestError, match="binary"):
        decode_upload(b"PK\x00\x03")
    with pytest.raises(IngestError, match="UTF-8"):
        decode_upload(b"\xff\xfe\xfa")
    with pytest.raises(IngestError, match="larger"):
        decode_upload(b"a" * (MAX_BYTES + 1))


# ------------------------------------------------------------ demo project


@pytest.fixture()
def demo(session):
    project = load_demo_project(session)
    session.commit()
    return project


def _all_text(session) -> str:
    return "\n".join(session.scalars(select(Chunk.text)))


def test_demo_project_loads_every_source_and_user(session, demo):
    assert len(demo.sources) == 8
    assert len(session.scalars(select(User)).all()) == 4
    assert {s.kind for s in demo.sources} == set(SourceKind)


def test_demo_load_is_idempotent(session, demo):
    again = load_demo_project(session)
    session.commit()
    assert again.id == demo.id
    assert len(again.sources) == 8
    assert len(session.scalars(select(User)).all()) == 4


def test_every_seeded_trap_is_reachable_in_the_stored_chunks(session, demo):
    traps = json.loads(read("expected.json"))["seeded_traps"]
    text = _all_text(session)
    assert traps["conflict"]["agreed"]["quote"] in text
    assert traps["conflict"]["contradicted_by"][0]["quote"] in text
    assert traps["conflict"]["contradicted_by"][1]["quote"] in text
    assert traps["no_reason"]["decision"] in text
    assert "T7: QR check-in at the venue | owner: UNASSIGNED" in text


def test_the_demo_secret_is_masked_everywhere_and_the_message_is_confidential(session, demo):
    marker = json.loads(read("expected.json"))["seeded_traps"]["confidential"][0]["marker"]
    assert marker not in _all_text(session)
    assert "demo_live_" not in _all_text(session)
    masked = session.scalars(select(Chunk).where(Chunk.redacted.is_(True))).all()
    assert len(masked) == 1
    assert "[REDACTED:secret]" in masked[0].text
    assert masked[0].sensitivity == Sensitivity.confidential


def test_sponsor_notes_are_confidential_and_hidden_from_lower_roles(session, demo):
    sponsor = next(s for s in demo.sources if "sponsor" in s.name)
    assert sponsor.chunks and all(c.sensitivity == Sensitivity.confidential for c in sponsor.chunks)
    for chunk in sponsor.chunks:
        assert chunk_visible(Role.approver, chunk)
        assert not chunk_visible(Role.viewer, chunk)
        assert not chunk_visible(Role.restricted, chunk)


def test_the_masked_chat_message_is_hidden_from_the_incoming_person(session, demo):
    masked = session.scalars(select(Chunk).where(Chunk.redacted.is_(True))).one()
    assert chunk_visible(Role.admin, masked)
    assert not chunk_visible(Role.viewer, masked)
    ordinary = session.scalars(select(Chunk).where(Chunk.redacted.is_(False))).first()
    assert chunk_visible(Role.restricted, ordinary) == (ordinary.sensitivity in
                                                       (Sensitivity.public, Sensitivity.team))
