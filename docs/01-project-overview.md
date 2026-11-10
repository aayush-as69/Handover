# 01 — Project Overview

## 1. Purpose

Handover is a knowledge-transfer application for projects where important context can be lost when a team member leaves.

It ingests structured project evidence, extracts candidate claims, mechanically checks those claims against their evidence, sends them through human review, and publishes only approved information to role-appropriate readers.

## 2. Problem

Project knowledge is distributed across sources such as meeting notes, team chat, task exports and repository activity. A replacement team member often needs the **reason behind a decision**, current ownership, unfinished work, risks and sensitive context—not simply the source files themselves.

The central design decision is therefore to make a **claim with evidence** the unit of handover knowledge.

## 3. Target users

| Role | Purpose |
|---|---|
| `admin` | Manage sources and project-level operations; full clearance |
| `approver` | Review, approve and sign off handover content |
| `viewer` | Incoming person who reads an approved handover |
| `restricted` | Limited-context reader |

The role model and clearance mapping are defined in `app/enums.py` and enforced through `app/access.py`.

## 4. Core workflow

1. An admin loads project sources.
2. Parsers convert sources into addressable chunks.
3. Secret masking runs before chunks are persisted.
4. The extractor produces candidate claims with evidence references.
5. The verification pass assigns a mechanical confidence label.
6. Reviewers inspect claims beside their evidence.
7. Reviewers approve, edit, reject or reopen claims.
8. Approved claims can be signed off into a numbered release.
9. Readers receive only claims allowed by their role and effective sensitivity.
10. Readers may acknowledge a specific release.

## 5. What makes the product different

Handover is not simply a document-sharing system. Its central controls are:

- evidence-linked claims;
- mechanical evidence verification;
- human approval as a separate trust boundary;
- sensitivity propagation from evidence to claims;
- server-side role/clearance enforcement;
- field-level redaction;
- immutable claim history and releases;
- stale-release behavior after later edits/rejections/reopenings.

## 6. Functional boundaries

### Included

- Four source families: notes, chat, tasks and public GitHub.
- Rule-based extraction.
- Optional OpenAI-compatible extraction.
- Evidence verification.
- Human review.
- Conflict detection.
- Questions Before I Leave.
- Role-filtered handover generation.
- Acknowledgements.
- SQLite/PostgreSQL persistence.
- Render configuration.

### Explicitly not built

The repository documents these as future work rather than delivered features:

- multiple projects per deployment;
- a dedicated audit-log UI;
- named acknowledgement history UI;
- richer conflict visualization;
- extraction quality reporting;
- stronger semantic evaluation.

## 7. Non-functional characteristics

The implementation explicitly addresses:

- fail-closed access control;
- CSRF protection;
- persistent login-failure tracking;
- request throttling;
- secret masking;
- secure production configuration validation;
- append-only history for critical records;
- optimistic locking for claim edits;
- duplicate/race-safe creation of selected records;
- health and readiness endpoints;
- CI on SQLite and PostgreSQL.
