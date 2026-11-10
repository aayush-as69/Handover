<div align="center">

<img src="assets/handover-logo.svg" alt="Handover" width="48" />

# 07 — Security Architecture & Review

<sub>Handover · Product and engineering documentation</sub>

</div>

---

## 1. Security posture

Handover uses layered controls rather than treating the UI or the model as a security boundary.

## 2. Authentication

- Passwords are hashed with PBKDF2-HMAC-SHA256 using a per-password random salt.
- Unknown usernames are checked using a dummy hash at the real hashing cost.
- Sessions use Starlette's signed session middleware.
- Production requires a 32+ character `SECRET_KEY`.
- Production requires secure cookies.

## 3. CSRF

State-changing HTML form requests include a server-generated CSRF token. `check_csrf()` uses constant-time comparison.

## 4. Authorization

Authorization is server-side.

| Role | Clearance | Review queue | Source admin |
|---|---|---|---|
| admin | confidential | yes | yes |
| approver | confidential | yes | no |
| viewer | restricted | no | no |
| restricted | team | no | no |

A claim's effective sensitivity is the maximum of its own sensitivity, its evidence chunk sensitivities and their source sensitivities.

Unknown/invalid sensitivity values in SQL ranking are treated above the known levels, which fails closed.

## 5. Login throttling

The database stores failed attempts so throttling survives process restarts. The documented limits include per-user/IP, per-user, username-spraying and per-IP failure limits.

The application also has in-memory request-rate limiting. This is per server process and therefore is not a distributed rate limiter.

## 6. Secret protection

Secrets are masked during ingestion before storage, display or model submission. Patterns cover common cloud/source-host/payment/chat/LLM keys, JWTs, bearer/basic credentials, credential URLs, private keys and credential-like assignments/high-entropy values.

This is **pattern-based protection**, not a guarantee that every secret will be detected.

## 7. LLM trust boundary

The LLM is treated as untrusted:

- source content is explicitly fenced as data;
- evidence references must correspond to chunks supplied to the extractor;
- response shape and types are validated;
- oversized/malformed replies are rejected;
- malformed claims are dropped;
- confidential chunks are withheld from remote extractors by default;
- model semantic opinions are advisory only.

## 8. HTTP security

The application sets:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: same-origin`
- restrictive `Content-Security-Policy`
- `Cache-Control: no-store` for normal responses
- HSTS when secure cookies are enabled.

Production disables the interactive FastAPI docs and OpenAPI endpoint.

## 9. Error handling

Unexpected exceptions are logged server-side and presented to the user as a generic message rather than an internal traceback.

## 10. Integrity controls

Append-only guards protect claim versions, audit events and handover releases. Evidence cannot be modified/deleted after storage. Database uniqueness constraints and savepoints handle selected concurrent creation races.

## 11. What Handover does not guarantee

- Pattern-based secret detection can miss unusual secrets or mask benign strings.
- Mechanical verification cannot understand semantic truth.
- Conflict detection is rule based and may miss disagreements or produce noise.
- Live LLM behavior has not been validated in the documented CI baseline.
- In-memory request limiting is not a distributed production defense.
- A configured Render deployment is not the same as a verified live deployment.
