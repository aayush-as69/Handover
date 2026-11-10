# Handover Documentation

This documentation set reorganizes the existing Handover knowledge into a maintainable engineering reference. It follows the **documentation principles** observed in the JBSnap reference repository—clear separation of overview, requirements, architecture, implementation, testing, deployment and project context—without copying JBSnap's product architecture or implementation.

## Reading order

### 1. Understand the product
- [01 — Project Overview](01-project-overview.md)
- [02 — Product Requirements (PRD)](02-prd.md)
- [03 — Software Requirements (SRS)](03-srs.md)
- [12 — User & Demo Guide](12-user-demo-guide.md)

### 2. Understand the system
- [04 — System Architecture](04-architecture.md)
- [05 — Database Design](05-database-design.md)
- [06 — Technical Implementation](06-technical-implementation.md)
- [07 — Security Architecture](07-security.md)
- [08 — API Reference](08-api-reference.md)

### 3. Build, test and operate it
- [09 — Testing Guide](09-testing.md)
- [10 — Development Setup](10-development.md)
- [11 — Deployment & Operations](11-deployment-operations.md)

### 4. Understand boundaries and documentation quality
- [13 — Limitations & Roadmap](13-limitations-roadmap.md)
- [14 — Documentation Coverage](14-documentation-coverage.md)
- [Architecture Mermaid source](architecture.mmd)

## Source of truth

The implementation remains authoritative. Documentation describes behavior found in the current repository and intentionally avoids claiming features that could not be supported by code or tests.

When documentation and implementation disagree, update the documentation only after checking the relevant source and tests.

## Current repository snapshot audited

- FastAPI application under `app/`
- SQLAlchemy models and Alembic migrations
- SQLite and PostgreSQL support
- Server-rendered Jinja pages
- Ingestion and extraction pipelines
- Security/access/redaction controls
- CI workflow under `.github/workflows/ci.yml`
- Render blueprint under `render.yaml`
- Existing tests under `tests/`

## Documentation status vocabulary

| Status | Meaning |
|---|---|
| Complete | Documented and supported by implementation/tests reviewed |
| Partial | Some behavior or evidence remains incomplete |
| Not implemented | Explicitly absent from the current codebase |
| Not verified | Configuration/code exists but current live behavior was not verified |
