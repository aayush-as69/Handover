<div align="center">

<img src="../../docs/assets/handover-logo.svg" alt="Handover" width="52" />

# Synthetic demo dataset

**CampusEvents · Safe sample data for local walkthroughs**

</div>

---

Everything in this directory is invented for demonstration. The project, people, sponsor, dates, commits, issues and the “API key” are fictional. No real credentials or confidential workplace material are included.

## Scenario

A four-person club team built **CampusEvents**, an app for discovering club events, booking seats and paying online.

- **Riya Sharma** — backend lead, leaving on 20 November 2026.
- **Kabir Mehta** — incoming backend owner.
- **Meera Iyer** — club lead and handover approver.
- **Mr. Rao** — mentor with restricted access.

## Dataset files

| File | Purpose |
|---|---|
| `manifest.json` | Dataset metadata and source inventory |
| `github_snapshot.json` | Synthetic public-repository activity |
| `tasks.csv` | Example project tasks and ownership |
| `team_chat.txt` | Example team conversation |
| `notes/` | Project notes, decisions and planning context |
| `expected.json` | Deliberately planted edge cases used by tests/evaluation |

The expected file describes the traps intentionally planted in the sample. Tests and later evaluation use it to check whether the application handles those cases correctly.

> Use this dataset to explore ingestion, extraction, verification, review, redaction and role-filtered handover behavior. Do not treat sample identities or credentials as real.

## Seeded review examples
`seeded_claims.json` holds four deliberately weak draft claims (two inferred, one conflicting, one
unsupported) so the demo shows every confidence label without an LLM key. They are marked
`demo-seed`, and their labels are computed by the normal verifier, not written by hand. Like every
claim they start unapproved and need a reviewer.
