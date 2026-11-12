<div align="center">

<img src="assets/handover-logo.svg" alt="Handover" width="56" />

# 08 — API & Route Reference

<sub>Handover · Product and engineering reference</sub>

</div>

> [Documentation index](README.md) · [Project home](../README.md)

---

Handover is primarily a server-rendered web application. The repository deliberately disables interactive FastAPI API docs in production. This reference therefore documents the implemented browser/health routes rather than exposing an automatically generated production API schema.

## Public/system routes

| Method | Route | Purpose |
|---|---|---|
| GET | `/` | Redirects to login, review or handover depending on session |
| GET | `/login` | Login page |
| POST | `/login` | Authenticate a user |
| POST | `/logout` | End session |
| GET | `/health` | Liveness; process is up |
| GET | `/ready` | Readiness; database reachable and migration current |

## Review routes

| Method | Route | Auth |
|---|---|---|
| GET | `/review` | admin/approver |
| GET | `/review/claims/{claim_id}` | admin/approver |
| POST | `/review/claims/{claim_id}/{action}` | admin/approver + CSRF |
| GET | `/review/chunks/{chunk_id}` | admin/approver |

Supported claim actions are `approve`, `reject`, `reopen` and `edit`.

## Handover routes

| Method | Route | Auth |
|---|---|---|
| GET | `/handover` | authenticated user |
| GET | `/handover/releases` | admin/approver |
| POST | `/handover/{action}` | authenticated user + CSRF |

Supported handover actions include `approve`, `withdraw` and `acknowledge`.

## Source administration routes

| Method | Route | Auth |
|---|---|---|
| GET | `/admin/sources` | admin |
| POST | `/admin/sources/upload` | admin + CSRF |
| POST | `/admin/sources/extract` | admin + CSRF |
| POST | `/admin/sources/semantic` | admin + CSRF |

## Conflict/question routes

| Method | Route | Auth |
|---|---|---|
| GET | `/conflicts` | admin/approver |
| POST | `/conflicts/detect` | admin/approver + CSRF |
| POST | `/conflicts/{conflict_id}/{action}` | admin/approver + CSRF |
| GET | `/questions` | admin/approver |
| POST | `/questions/refresh` | admin/approver + CSRF |
| POST | `/questions/{question_id}/{action}` | admin/approver + CSRF |

## Workspace routes

| Method | Route | Auth |
|---|---|---|
| GET | `/guide` | authenticated user (explains the product; steps differ by role) |
| GET | `/timeline` | authenticated user; approved claims the role may read (`type`, `drafts` filters; drafts for reviewers only) |
| GET | `/bus-factor` | admin/approver |
| GET | `/audit` | admin/approver; `kind` filter; entries above the role's clearance are left out |
| GET | `/projects` | authenticated user; lists only projects the user belongs to (admins see all) |
| POST | `/projects/switch` | member of the project + CSRF |
| POST | `/projects/new` | admin + CSRF |
| POST | `/projects/{project_id}/members/{add\|remove}` | admin + CSRF |

## `/health` vs `/ready`

`/health` is a **liveness** endpoint. It reports that the application process is running and does not assert database health.

`/ready` is a **readiness** endpoint. It checks whether the database is reachable and whether the migration state matches the current migration head. It returns HTTP 503 when not ready.

## Error behavior

The application renders user-facing error pages for HTTP errors and uses a generic 500 response for unexpected exceptions. Review access intentionally returns “not found” when a claim exists but is above the user's clearance, avoiding information disclosure about hidden records.


---

[← Documentation index](README.md) · [Project home](../README.md)
