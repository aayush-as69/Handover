"""Structured observability: a few counters, one latency histogram and JSON access logs.

Kept in memory per process and exposed at `/metrics` in Prometheus text format (or JSON with
`?format=json`). Nothing here stores a person's data: only counts, route templates (never raw
URLs with ids) and durations. With several worker processes, scrape each one or aggregate in
the monitoring system. Job counts come from the database, so they are the same everywhere.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict

BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 120.0)

_lock = threading.Lock()
_counters: dict[tuple[str, tuple], float] = defaultdict(float)
_hist: dict[tuple[str, tuple], list[float]] = {}          # name,labels -> [bucket counts..., sum, count]

access_log = logging.getLogger("handover.access")

HELP = {
    "handover_requests_total": "HTTP requests by method, route template and status class.",
    "handover_request_seconds": "HTTP request latency.",
    "handover_login_failures_total": "Failed sign-in attempts.",
    "handover_rate_limited_total": "Requests answered 429, by limiter.",
    "handover_extractions_total": "Extraction runs by engine and outcome.",
    "handover_extraction_seconds": "Extraction duration by engine.",
    "handover_llm_failures_total": "Extraction runs that failed because the model call failed.",
    "handover_db_errors_total": "Database errors raised while serving a request or job.",
    "handover_jobs": "Background jobs by status (from the database).",
}


def _key(labels: dict) -> tuple:
    return tuple(sorted(labels.items()))


def inc(name: str, amount: float = 1, **labels) -> None:
    with _lock:
        _counters[(name, _key(labels))] += amount


def observe(name: str, value: float, **labels) -> None:
    with _lock:
        row = _hist.setdefault((name, _key(labels)), [0.0] * (len(BUCKETS) + 2))
        for i, b in enumerate(BUCKETS):
            if value <= b:
                row[i] += 1
        row[-2] += value
        row[-1] += 1


def reset() -> None:
    with _lock:
        _counters.clear()
        _hist.clear()


def counter(name: str, **labels) -> float:
    """Sum of a counter over every series whose labels include the ones given."""
    want = set(labels.items())
    with _lock:
        return sum(v for (n, k), v in _counters.items() if n == name and want <= set(k))


def log_request(method: str, route: str, status: int, seconds: float, request_id: str) -> None:
    access_log.info(json.dumps({"event": "request", "method": method, "route": route,
                                "status": status, "ms": round(seconds * 1000, 1),
                                "request_id": request_id}, separators=(",", ":")))


def job_counts(session) -> dict[str, int]:
    from sqlalchemy import func, select
    from .models import Job
    rows = session.execute(select(Job.status, func.count()).group_by(Job.status)).all()
    out = {s: 0 for s in ("queued", "running", "done", "failed")}
    out.update({s: n for s, n in rows})
    return out


def _fmt(labels: tuple, extra: dict | None = None) -> str:
    items = list(labels) + list((extra or {}).items())
    if not items:
        return ""
    return "{" + ",".join(f'{k}="{str(v).replace(chr(34), "")}"' for k, v in items) + "}"


def render_text(jobs: dict[str, int]) -> str:
    lines: list[str] = []
    with _lock:
        counters, hists = dict(_counters), {k: list(v) for k, v in _hist.items()}
    for name in sorted({n for n, _ in counters}):
        lines += [f"# HELP {name} {HELP.get(name, name)}", f"# TYPE {name} counter"]
        lines += [f"{name}{_fmt(k)} {v:g}" for (n, k), v in sorted(counters.items()) if n == name]
    for name in sorted({n for n, _ in hists}):
        lines += [f"# HELP {name} {HELP.get(name, name)}", f"# TYPE {name} histogram"]
        for (n, k), row in sorted(hists.items()):
            if n != name:
                continue
            for b, c in zip(BUCKETS, row):
                lines.append(f"{name}_bucket{_fmt(k, {'le': b})} {c:g}")
            lines.append(f"{name}_bucket{_fmt(k, {'le': '+Inf'})} {row[-1]:g}")
            lines += [f"{name}_sum{_fmt(k)} {row[-2]:.6f}", f"{name}_count{_fmt(k)} {row[-1]:g}"]
    lines += ["# HELP handover_jobs " + HELP["handover_jobs"], "# TYPE handover_jobs gauge"]
    lines += [f'handover_jobs{{status="{s}"}} {n}' for s, n in sorted(jobs.items())]
    return "\n".join(lines) + "\n"


def render_json(jobs: dict[str, int]) -> dict:
    with _lock:
        counters = [{"name": n, "labels": dict(k), "value": v} for (n, k), v in sorted(_counters.items())]
        hists = [{"name": n, "labels": dict(k), "count": r[-1], "sum": round(r[-2], 6)}
                 for (n, k), r in sorted(_hist.items())]
    return {"counters": counters, "histograms": hists, "jobs": jobs}
