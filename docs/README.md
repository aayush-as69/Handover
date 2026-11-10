<div align="center">

<img src="assets/handover-logo.svg" alt="Handover" width="64" />

# Handover Documentation

**Product context · Engineering decisions · Operations**

A structured guide to understanding, building, testing and operating Handover.

</div>

---

## Start here

| Goal | Recommended reading |
|---|---|
| Understand the product | [Project overview](01-project-overview.md) → [PRD](02-prd.md) |
| Understand requirements | [SRS](03-srs.md) |
| Follow the data flow | [Architecture](04-architecture.md) → [Technical implementation](06-technical-implementation.md) |
| Understand persistence | [Database design](05-database-design.md) |
| Review trust boundaries | [Security architecture](07-security.md) |
| Explore routes | [API and route reference](08-api-reference.md) |
| Run and verify locally | [Development setup](10-development.md) → [Testing guide](09-testing.md) |
| Deploy and operate | [Deployment and operations](11-deployment-operations.md) |
| Walk through the demo | [User and demo guide](12-user-demo-guide.md) |
| Check limitations | [Limitations and roadmap](13-limitations-roadmap.md) |

## Documentation map

### Product and requirements

- [01 — Project overview](01-project-overview.md)
- [02 — Product requirements (PRD)](02-prd.md)
- [03 — Software requirements (SRS)](03-srs.md)
- [12 — User and demo guide](12-user-demo-guide.md)

### Architecture and implementation

- [04 — System architecture](04-architecture.md)
- [05 — Database design](05-database-design.md)
- [06 — Technical implementation](06-technical-implementation.md)
- [07 — Security architecture](07-security.md)
- [08 — API and route reference](08-api-reference.md)

### Development and operations

- [09 — Testing guide](09-testing.md)
- [10 — Development setup](10-development.md)
- [11 — Deployment and operations](11-deployment-operations.md)
- [OPERATIONS — Operational runbook](OPERATIONS.md)

### Project context and audit material

- [13 — Limitations and roadmap](13-limitations-roadmap.md)
- [14 — Documentation coverage](14-documentation-coverage.md)
- [FEATURES — Conflicts, questions and redaction](FEATURES.md)
- [PRODUCTION READINESS — Engineering review](PRODUCTION_READINESS.md)
- [DISCLOSURES — Tools, services and AI assistance](DISCLOSURES.md)
- [ROUND2 — Round 2 project notes](ROUND2.md)

## Architecture assets

- [Rendered architecture diagram](architecture.svg)
- [Architecture source (Mermaid)](architecture.mmd)
- [Architecture PNG](architecture.png)

## Documentation conventions

- **Implemented** means supported by repository code and/or tests reviewed.
- **Partial** means some behavior or operational evidence remains incomplete.
- **Not verified** means configuration or code exists, but a live execution was not established.
- **Proposed** means future work, not a delivered capability.

The implementation and tests are authoritative. Historical test totals and deployment observations are point-in-time evidence, not guarantees about a future checkout.
