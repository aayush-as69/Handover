"""Fetch a PUBLIC GitHub repository's recent commits, issues and pull requests.

Only public repositories are read, with no credentials. The result has the same shape as the
offline snapshot in data/demo/github_snapshot.json, so both go through the same parser.
"""

from __future__ import annotations

import re

import httpx

from .errors import IngestError

API = "https://api.github.com"
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_BODY_LIMIT = 2000


def _check(resp: httpx.Response, what: str) -> None:
    if resp.status_code == 404:
        raise IngestError(f"{what} was not found, or it is not public")
    if resp.status_code == 429 or (
        resp.status_code == 403 and resp.headers.get("x-ratelimit-remaining") == "0"
    ):
        raise IngestError("GitHub rate limit reached; try again later")
    if resp.status_code == 403:
        raise IngestError(f"GitHub refused access to {what}")
    if resp.status_code >= 400:
        raise IngestError(f"GitHub returned an error ({resp.status_code}) for {what}")


def _get(client: httpx.Client, path: str, what: str, params: dict | None = None):
    try:
        resp = client.get(f"{API}{path}", params=params)
    except httpx.HTTPError:
        raise IngestError("could not reach GitHub")
    _check(resp, what)
    return resp.json()


def _list(payload, what: str) -> list:
    if not isinstance(payload, list):
        raise IngestError(f"unexpected response from GitHub for {what}")
    return payload


def _clip(text: str | None) -> str:
    return (text or "")[:_BODY_LIMIT]


def _clip_patch(text: str | None) -> str:
    return (text or "")[:1500]


def fetch_public_repo(
    owner: str, repo: str, *, client: httpx.Client | None = None, max_items: int = 100,
    detail_limit: int = 5,
) -> dict:
    """Recent commits, issues and pull requests; for the newest `detail_limit` pull requests
    and commits also the changed files (with diffs) and pull request reviews and comments.

    Details cost extra requests against GitHub's unauthenticated rate limit, so they stop at
    the first failure and the result carries a warning instead of failing the whole import.
    """
    if not (_NAME.match(owner) and _NAME.match(repo)):
        raise IngestError("that does not look like a valid GitHub owner/repository name")

    own_client = client is None
    client = client or httpx.Client(
        timeout=15,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "handover-hackathon-app"},
    )
    per_page = {"per_page": max(1, min(max_items, 100))}
    try:
        meta = _get(client, f"/repos/{owner}/{repo}", "the repository")
        if not isinstance(meta, dict) or meta.get("private"):
            raise IngestError("only public repositories can be connected")

        commits = _list(_get(client, f"/repos/{owner}/{repo}/commits", "commits", per_page), "commits")
        issues = _list(
            _get(client, f"/repos/{owner}/{repo}/issues", "issues", {**per_page, "state": "all"}),
            "issues",
        )
        pulls = _list(
            _get(client, f"/repos/{owner}/{repo}/pulls", "pull requests", {**per_page, "state": "all"}),
            "pull requests",
        )
        warnings: list[str] = []
        pull_details: dict[int, dict] = {}
        commit_files: dict[str, list] = {}
        try:
            for p in pulls[:detail_limit]:
                n = p.get("number")
                if not isinstance(n, int):
                    continue
                base = f"/repos/{owner}/{repo}/pulls/{n}"
                pull_details[n] = {
                    "files": _list(_get(client, f"{base}/files", f"pull request #{n} files",
                                        {"per_page": 30}), "files"),
                    "reviews": _list(_get(client, f"{base}/reviews", f"pull request #{n} reviews",
                                          {"per_page": 30}), "reviews"),
                    "comments": _list(_get(client, f"{base}/comments", f"pull request #{n} comments",
                                           {"per_page": 30}), "comments"),
                }
            for c in commits[:detail_limit]:
                sha = str(c.get("sha", ""))
                if sha:
                    one = _get(client, f"/repos/{owner}/{repo}/commits/{sha}", f"commit {sha[:7]}")
                    commit_files[sha[:7]] = (one.get("files") if isinstance(one, dict) else None) or []
        except IngestError as exc:
            warnings.append(f"Files, diffs and reviews were only partly fetched: {exc}.")
    finally:
        if own_client:
            client.close()

    def files_of(raw) -> list[dict]:
        return [{"filename": f.get("filename"), "additions": f.get("additions"),
                 "deletions": f.get("deletions"), "patch": _clip_patch(f.get("patch"))}
                for f in raw if isinstance(f, dict) and isinstance(f.get("filename"), str)]

    return {
        "warnings": warnings,
        "repo": f"{owner}/{repo}",
        "synthetic": False,
        "commits": [
            {
                "sha": str(c.get("sha", ""))[:7],
                "author": ((c.get("commit") or {}).get("author") or {}).get("name", "unknown"),
                "date": ((c.get("commit") or {}).get("author") or {}).get("date"),
                "message": ((c.get("commit") or {}).get("message") or "").split("\n", 1)[0],
                "files": files_of(commit_files.get(str(c.get("sha", ""))[:7], [])),
            }
            for c in commits
        ],
        "issues": [
            {
                "number": i.get("number"),
                "title": i.get("title", ""),
                "state": i.get("state", "?"),
                "author": (i.get("user") or {}).get("login", "unknown"),
                "assignees": [a.get("login") for a in i.get("assignees") or [] if a.get("login")],
                "created": i.get("created_at"),
                "body": _clip(i.get("body")),
            }
            for i in issues
            if "pull_request" not in i  # GitHub lists pull requests as issues too
        ],
        "pulls": [
            {
                "number": p.get("number"),
                "title": p.get("title", ""),
                "state": "merged" if p.get("merged_at") else p.get("state", "?"),
                "author": (p.get("user") or {}).get("login", "unknown"),
                "created": p.get("created_at"),
                "body": _clip(p.get("body")),
                "files": files_of(pull_details.get(p.get("number"), {}).get("files", [])),
                "reviews": [
                    {"author": (r.get("user") or {}).get("login", "unknown"),
                     "state": r.get("state", "COMMENTED"), "body": _clip(r.get("body")),
                     "submitted": r.get("submitted_at")}
                    for r in pull_details.get(p.get("number"), {}).get("reviews", [])
                    if isinstance(r, dict)],
                "comments": [
                    {"author": (c.get("user") or {}).get("login", "unknown"),
                     "path": c.get("path"), "body": _clip(c.get("body")),
                     "created": c.get("created_at")}
                    for c in pull_details.get(p.get("number"), {}).get("comments", [])
                    if isinstance(c, dict)],
            }
            for p in pulls
        ],
    }
