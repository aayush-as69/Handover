<div align="center">

<img src="assets/handover-logo.svg" alt="Handover" width="48" />

# 17 — Background Jobs & Observability

<sub>Handover · Product and engineering documentation</sub>

</div>

---

## Background jobs

Slow work (LLM extraction) runs as a **job**, a row in the `jobs` table, so the web request returns at once. Two ways to run jobs, chosen by `JOB_MODE`:

| | `thread` (default) | `queue` |
|---|---|---|
| Who runs it | A thread inside the web process | One or more separate worker processes |
| Extra services | None | A worker process (same code, same database) |
| Survives a restart | No: active jobs are marked failed at startup | Yes: the job stays queued, or is put back if its worker died |
| Several web instances | Each runs its own jobs | Share one queue |
| Use it for | Demo, single small instance | A team, or anything where extraction must outlive a deploy |

### Queue mode

```bash
JOB_MODE=queue uvicorn app.main:app          # web: writes a queued row, returns at once
python -m app.worker                         # worker: claims rows and runs them; start as many as you like
python -m app.worker --once                  # drain the queue and exit (cron, tests)
```

- The database is the queue. A worker claims a job with one atomic `UPDATE ... WHERE status='queued'`, so exactly one worker gets each job on SQLite or PostgreSQL. No broker to run.
- While a job runs its worker writes a heartbeat every 15 seconds. A running job with no heartbeat for 2 minutes is put back in the queue (`requeue_stale`), by any worker or at web startup.
- Workers need the same `DATABASE_URL` and `LLM_*` settings as the web service. The Sources page shows queued, running, done and failed jobs either way.
- A job that fails is not retried automatically: it records the reason and a person runs it again.

Why not Celery or Redis? At this size they add a second thing to deploy and monitor for no benefit. If throughput or scheduling grows, `jobs.dispatch` is the single place to hand jobs to a real broker.

## Observability

`/metrics` returns Prometheus text (or JSON with `?format=json`). It needs either `Authorization: Bearer <METRICS_TOKEN>` or an admin session; anyone else gets 404. It is exempt from the request rate limiter so a scraper is not throttled.

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `handover_requests_total` | counter | method, route, status | Requests by route *template* (`/review/claims/{claim_id}`), never raw URLs |
| `handover_request_seconds` | histogram | route | Request latency |
| `handover_login_failures_total` | counter | | Wrong username or password |
| `handover_rate_limited_total` | counter | limiter (`general`, `login`, `login_lockout`) | Requests answered 429 or sign-ins refused by lockout |
| `handover_extractions_total` | counter | engine, outcome | Extraction runs |
| `handover_extraction_seconds` | histogram | engine | Extraction duration |
| `handover_llm_failures_total` | counter | | Extraction failed because the model call failed |
| `handover_db_errors_total` | counter | where (`request`, `job`) | Database errors |
| `handover_jobs` | gauge | status | Jobs queued, running, done, failed (read from the database, so identical for every process) |

Each request also writes one JSON line to the `handover.access` logger: `event`, `method`, `route`, `status`, `ms`, `request_id`. The `X-Request-ID` header is passed through or generated and returned, so a log line can be matched to a user report. No usernames, query strings or bodies are logged.

Counters and histograms live in memory per process and reset on restart; with several web processes, scrape each. Job gauges are shared because they come from the database.

## Throttling

`app/throttle.py` is the only place that throttles:

- `RateLimiter`: sliding window per address, in memory per process (`RATE_LIMIT_PER_MIN`, `LOGIN_RATE_PER_MIN`).
- Login lockout: stored in the database so it survives restarts and is shared. Limits per account and address, per account, per address (accounts tried), and per address (volume).

A proxy or CDN limiter in front is still advised for production; see [11 — Deployment](11-deployment-operations.md).
