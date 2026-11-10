<div align="center">

<div align="right">
<img src="assets/handover-logo.svg" alt="Handover" width="38" />
</div>

> [Documentation index](README.md) · [Project home](../README.md)

<img src="assets/handover-logo.svg" alt="Handover" width="48" />

# 02 — Product Requirements Document

<sub>Handover · Product and engineering documentation</sub>

</div>

---

## 1. Product vision

Make project handover evidence-backed, reviewable and permission-aware so that the incoming person receives useful context without treating generated text as unquestioned truth.

## 2. User problems

- Context is scattered across multiple tools.
- Important decisions lack rationale in one place.
- Ownership and unfinished work are easy to miss.
- Sensitive information should not be exposed to every reader.
- AI-generated summaries can invent or distort facts.
- A handover may change after it was approved.

## 3. Product principles

1. **Evidence before assertion.** Claims should point to source evidence.
2. **Verification is not approval.** Mechanical checks do not make a claim true.
3. **Human approval is mandatory.** Only reviewers promote claims into handover content.
4. **Least privilege.** A reader receives only information permitted by clearance.
5. **Fail closed.** Unknown or inaccessible content is not exposed.
6. **History matters.** Important changes remain traceable.
7. **Privacy starts at ingestion.** Secrets are masked before storage.

## 4. Functional requirements

| ID | Requirement | Acceptance evidence |
|---|---|---|
| FR-01 | Ingest supported project sources | `app/ingest/*`, `tests/test_ingest.py` |
| FR-02 | Mask secrets before storage | `app/ingest/redact.py`, secret/redaction tests |
| FR-03 | Deduplicate identical source content | `Source.content_hash` + ingestion tests |
| FR-04 | Extract claims with evidence | `app/extract/*`, extraction tests |
| FR-05 | Validate model output | `app/schemas.py`, LLM validation tests |
| FR-06 | Verify evidence mechanically | `app/verify.py`, verification tests |
| FR-07 | Review claims | `app/web.py`, web tests |
| FR-08 | Preserve claim history | `ClaimVersion`, model/integrity tests |
| FR-09 | Detect conflicts | `app/conflicts.py`, conflict tests |
| FR-10 | Generate questions | `app/questions.py`, conflict/question tests |
| FR-11 | Sign off releases | `app/handover.py`, handover tests |
| FR-12 | Filter by role and sensitivity | `app/access.py`, access/SQL tests |
| FR-13 | Redact fields inside visible claims | `app/redaction.py`, redaction tests |
| FR-14 | Record acknowledgements | `Acknowledgement`, handover tests |
| FR-15 | Support database migration lifecycle | `app/db.py`, migration tests |

## 5. Non-functional requirements

- Production configuration must reject unsafe settings.
- Passwords must not be stored in plaintext.
- Session cookies must support secure production operation.
- CSRF must be checked for state-changing form requests.
- Security headers must be applied by middleware.
- Unexpected errors must not expose internal details to users.
- Critical historical records must be append-only.
- Concurrent updates must not silently overwrite newer claim versions.

## 6. Out of scope

The current product does not claim multi-project hosting, a dedicated audit-log page, richer conflict visualization, or live-LLM quality guarantees.


---

[← Documentation index](README.md) · [Project home](../README.md)
