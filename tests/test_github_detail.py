import json

import httpx
import pytest
from sqlalchemy import select

from app.enums import ClaimType
from app.extract.pipeline import run_extraction
from app.extract.rules import RuleExtractor
from app.ingest.github import fetch_public_repo
from app.ingest.parsers import MAX_CHUNK_CHARS, parse_github
from app.models import Claim
from tests.test_extract import view  # noqa: F401


def snap(**pull):
    base = {"number": 7, "title": "add webhook", "state": "open", "author": "riya",
            "created": "2026-10-01T10:00:00Z", "body": "wip"}
    base.update(pull)
    return json.dumps({"pulls": [base]})


def by_locator(res):
    return {c.locator: c for c in res.chunks}


def test_pull_request_files_diffs_reviews_and_comments_become_chunks():
    res = parse_github(snap(
        files=[{"filename": "a.py", "additions": 3, "deletions": 1, "patch": "@@ -1 +1 @@\n+x = 1"},
               {"filename": "b.py"}],
        reviews=[{"author": "meera", "state": "changes_requested", "body": "Fix the signature check.",
                  "submitted": "2026-10-02T09:00:00Z"},
                 {"author": "bot", "state": "COMMENTED", "body": ""}],                  # empty: skipped
        comments=[{"author": "meera", "path": "a.py", "body": "Trusts the payload.",
                   "created": "2026-10-02T09:01:00Z"}]), "o/r")
    got = by_locator(res)
    assert "changes 2 file(s): a.py (+3/-1), b.py" in got["pull request #7 › files"].text
    assert "+x = 1" in got["pull request #7 › diff a.py"].text
    rev = got["pull request #7 › review by meera"]
    assert "[CHANGES_REQUESTED]" in rev.text and rev.author == "meera"
    assert got["pull request #7 › comment on a.py"].text.endswith("Trusts the payload.")
    assert "pull request #7 › review by bot" not in got
    assert all(len(c.text) <= MAX_CHUNK_CHARS for c in res.chunks)
    dates = [c.occurred_at for c in res.chunks]
    assert dates == sorted(dates)


def test_commit_diffs_are_chunked_and_long_patches_cut():
    snapshot = {"commits": [{"sha": "abc1234", "author": "a", "date": "2026-10-01T10:00:00Z",
                             "message": "m", "files": [{"filename": "x.py", "additions": 1,
                                                        "deletions": 0, "patch": "+" + "z" * 5000}]}]}
    res = parse_github(json.dumps(snapshot), "o/r")
    diff = by_locator(res)["commit abc1234 › diff x.py"]
    assert "…[diff cut]" in diff.text and len(diff.text) <= MAX_CHUNK_CHARS


def test_bad_entries_are_skipped_with_warnings_not_fatal():
    res = parse_github(snap(files=[42, {"nofilename": 1}, "ok.py"], reviews=["x", {"body": 5}],
                            comments="nope"), "o/r")
    assert any("file entry was not understood" in w for w in res.warnings)
    assert any("review was not understood" in w for w in res.warnings)
    assert "pull request #7 › files" in by_locator(res)


def test_at_most_ten_diffs_per_item():
    files = [{"filename": f"f{i}.py", "patch": "+x"} for i in range(15)]
    res = parse_github(snap(files=files), "o/r")
    assert len([c for c in res.chunks if "› diff" in c.locator]) == 10


def test_secrets_inside_diffs_are_masked_on_ingest(session, project):
    from app.enums import SourceKind
    from app.ingest.service import ingest_source
    fake = "sk_live_" + "A1b2C3d4E5f6G7h8I9j0K1l2"
    content = snap(files=[{"filename": "cfg.py", "patch": f"+KEY = '{fake}'"}])
    src = ingest_source(session, project, kind=SourceKind.github, name="o/r", content=content).source
    assert all(fake not in c.text for c in src.chunks)
    assert any(c.redacted and c.sensitivity.value == "confidential" for c in src.chunks)


def test_changes_requested_review_becomes_a_risk_claim():
    from app.extract.base import ChunkView
    res = parse_github(snap(reviews=[{"author": "meera", "state": "CHANGES_REQUESTED",
                                      "body": "Fix the signature check first."}]), "o/r")
    rev = next(c for c in res.chunks if "review by" in c.locator)
    cv = view(text=rev.text, kind=__import__("app.enums", fromlist=["x"]).SourceKind.github)
    claims = RuleExtractor().extract([cv]).result.claims
    assert len(claims) == 1 and claims[0].type == ClaimType.risk
    assert claims[0].statement == "Pull request #7 has changes requested by meera: Fix the signature check first."
    approvals = RuleExtractor().extract([view(text=rev.text.replace("CHANGES_REQUESTED", "APPROVED"),
                                              kind=cv.source_kind)]).result.claims
    assert approvals == []


def test_demo_review_is_extracted_and_verified(session, demo_project):
    run_extraction(session, demo_project, RuleExtractor())
    claim = session.scalar(select(Claim).where(Claim.statement.contains("changes requested")))
    assert claim and claim.confidence.value == "verified" and "signature" in claim.statement


# ------------------------------------------------------------ live fetch with details


def handler(calls, fail_on=None):
    def h(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(path)
        if fail_on and fail_on in path:
            return httpx.Response(403, headers={"x-ratelimit-remaining": "0"})
        if path == "/repos/o/r":
            return httpx.Response(200, json={"private": False})
        if path == "/repos/o/r/commits":
            return httpx.Response(200, json=[{"sha": "abcdef1234", "commit": {
                "author": {"name": "A", "date": "2026-10-01T10:00:00Z"}, "message": "m"}}])
        if path == "/repos/o/r/commits/abcdef1234":
            return httpx.Response(200, json={"files": [
                {"filename": "x.py", "additions": 2, "deletions": 1, "patch": "+a"}]})
        if path == "/repos/o/r/issues":
            return httpx.Response(200, json=[])
        if path == "/repos/o/r/pulls":
            return httpx.Response(200, json=[{"number": 3, "title": "t", "state": "open",
                "user": {"login": "a"}, "created_at": "2026-10-02T10:00:00Z", "body": "b"}])
        if path == "/repos/o/r/pulls/3/files":
            return httpx.Response(200, json=[{"filename": "w.py", "additions": 5, "deletions": 0,
                                              "patch": "+def f(): pass"}])
        if path == "/repos/o/r/pulls/3/reviews":
            return httpx.Response(200, json=[{"user": {"login": "m"}, "state": "CHANGES_REQUESTED",
                                              "body": "no", "submitted_at": "2026-10-03T10:00:00Z"}])
        if path == "/repos/o/r/pulls/3/comments":
            return httpx.Response(200, json=[{"user": {"login": "m"}, "path": "w.py",
                                              "body": "why", "created_at": "2026-10-03T10:01:00Z"}])
        return httpx.Response(404)
    return h


def client(h):
    return httpx.Client(transport=httpx.MockTransport(h))


def test_live_fetch_includes_files_diffs_reviews_and_comments():
    calls = []
    s = fetch_public_repo("o", "r", client=client(handler(calls)))
    pr = s["pulls"][0]
    assert pr["files"][0]["patch"] == "+def f(): pass"
    assert pr["reviews"][0]["state"] == "CHANGES_REQUESTED" and pr["comments"][0]["path"] == "w.py"
    assert s["commits"][0]["files"][0]["filename"] == "x.py" and s["warnings"] == []
    chunks = parse_github(json.dumps(s), "o/r").chunks
    assert {"pull request #3 › diff w.py", "commit abcdef1 › diff x.py"} <= {c.locator for c in chunks}


def test_detail_limit_bounds_the_requests():
    calls = []
    fetch_public_repo("o", "r", client=client(handler(calls)), detail_limit=0)
    assert not any("/pulls/3" in c or "/commits/abc" in c for c in calls)


def test_rate_limit_during_details_keeps_the_basics_and_warns():
    calls = []
    s = fetch_public_repo("o", "r", client=client(handler(calls, fail_on="/files")))
    assert s["pulls"][0]["number"] == 3 and s["pulls"][0]["files"] == []
    assert any("partly fetched" in w and "rate limit" in w for w in s["warnings"])
    assert not any(c.endswith("/reviews") for c in calls)          # stopped at the first failure
    res = parse_github(json.dumps(s), "o/r")
    assert any("partly fetched" in w for w in res.warnings)


# ------------------------------------------------------------ pagination


def _pager(total, calls):
    def h(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        q = request.url.params
        calls.append((path, q.get("page"), q.get("per_page")))
        if path == "/repos/o/r":
            return httpx.Response(200, json={"private": False})
        if path == "/repos/o/r/commits":
            page, size = int(q["page"]), int(q["per_page"])
            lo = (page - 1) * size
            rows = [{"sha": f"{i:07x}", "commit": {"author": {"name": "A", "date": "2026-10-01T10:00:00Z"},
                     "message": f"m{i}"}} for i in range(lo, min(lo + size, total))]
            return httpx.Response(200, json=rows)
        return httpx.Response(200, json=[])
    return h


def test_reads_several_pages_up_to_max_items():
    calls = []
    s = fetch_public_repo("o", "r", client=client(_pager(500, calls)), max_items=250, detail_limit=0)
    pages = [c[1] for c in calls if c[0].endswith("/commits")]
    assert pages == ["1", "2", "3"]
    assert len(s["commits"]) == 250


def test_stops_on_a_short_page_and_never_exceeds_the_page_cap():
    calls = []
    fetch_public_repo("o", "r", client=client(_pager(30, calls)), max_items=100, detail_limit=0)
    assert [c[1] for c in calls if c[0].endswith("/commits")] == ["1"]
    calls = []
    fetch_public_repo("o", "r", client=client(_pager(10_000, calls)), max_items=10_000, detail_limit=0)
    assert len([c for c in calls if c[0].endswith("/commits")]) == 5


def test_pull_request_detail_collections_follow_bounded_pagination():
    calls = []
    base_handler = handler(calls)
    file_pages = []

    def paged_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/o/r/pulls/3/files":
            page = int(request.url.params.get("page", "1"))
            file_pages.append((page, int(request.url.params.get("per_page", "0"))))
            if page == 1:
                return httpx.Response(200, json=[
                    {"filename": f"module_{i}.py", "additions": 1, "deletions": 0}
                    for i in range(100)
                ])
            return httpx.Response(200, json=[
                {"filename": "module_last.py", "additions": 2, "deletions": 0}
            ])
        return base_handler(request)

    snapshot = fetch_public_repo("o", "r", client=client(paged_handler), detail_limit=1)
    assert len(snapshot["pulls"][0]["files"]) == 101
    assert file_pages == [(1, 100), (2, 100)]
