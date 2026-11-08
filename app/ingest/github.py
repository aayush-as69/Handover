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


def fetch_public_repo(
    owner: str, repo: str, *, client: httpx.Client | None = None, max_items: int = 100
) -> dict:
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
    finally:
        if own_client:
            client.close()

    return {
        "repo": f"{owner}/{repo}",
        "synthetic": False,
        "commits": [
            {
                "sha": str(c.get("sha", ""))[:7],
                "author": ((c.get("commit") or {}).get("author") or {}).get("name", "unknown"),
                "date": ((c.get("commit") or {}).get("author") or {}).get("date"),
                "message": ((c.get("commit") or {}).get("message") or "").split("\n", 1)[0],
                "files": [],
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
            }
            for p in pulls
        ],
    }
