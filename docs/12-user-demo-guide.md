<div align="center">

<img src="assets/handover-logo.svg" alt="Handover" width="48" />

# 12 — User & Demo Guide

<sub>Handover · Product and engineering documentation</sub>

</div>

---

## 1. Start the demo

```bash
python -m app.demo
python -m app.demo --extract rules
uvicorn app.main:app --reload
```

Open `/login`.

## 2. Demo personas

| Username | Role | Purpose |
|---|---|---|
| `riya` | admin | Source management and administration |
| `meera` | approver | Review and sign off claims |
| `kabir` | viewer | Read the released handover |
| `rao` | restricted | Demonstrate reduced clearance/redaction |

Use the same demo password configured through `DEMO_PASSWORD` when password-backed demo login is enabled.

## 3. Admin flow

1. Log in as `riya`.
2. Open Sources.
3. Review the synthetic sources.
4. Load additional notes/chat/tasks/GitHub data if desired.
5. Run rule extraction.
6. Optionally configure an LLM provider and run LLM extraction.
7. Review generated conflicts/questions.

## 4. Approver flow

1. Log in as `meera`.
2. Open the review queue.
3. Start with conflicting/unsupported claims.
4. Open a claim and inspect its evidence.
5. Open the underlying source chunk when necessary.
6. Approve, edit, reject or reopen.
7. If a claim is not fully verified or has an advisory semantic doubt, provide the required review reason when approving.
8. Sign off the handover.

## 5. Viewer flow

1. Log in as `kabir`.
2. Open the handover.
3. Read role-appropriate sections.
4. Notice that rejected/edited/stale material is not presented as published truth.
5. Acknowledge the release when ready.

## 6. Restricted flow

1. Log in as `rao`.
2. Open the approved handover.
3. Compare visible claims with the viewer experience.
4. Observe reduced clearance and field-level redaction, including monetary amounts where applicable.

## 7. Confidence labels

- **quote-verified**: evidence was mechanically checked and supports the claim.
- **inferred**: evidence exists but the statement goes beyond what the text mechanically supports.
- **conflicting**: evidence contradicts the claim.
- **unsupported**: usable evidence was not found.

These are not truth scores. Human review remains the publication gate.

## 8. Conflicts

Conflict detection highlights potentially inconsistent claims. Resolving a conflict does not itself rewrite or approve the underlying claim. Reviewers must still edit/reject/approve the claims as appropriate.

## 9. Questions Before I Leave

Questions identify gaps such as missing ownership or unresolved context. Answers are displayed as the leaver's own words rather than automatically promoted to verified facts.

## 10. Timeline, bus factor, audit log and projects

- **How it works** (`/guide`): a short in-app explanation of the story, the steps, the labels and a role-based walkthrough. Start here if the demo data looks confusing.
- **Timeline** (`/timeline`): approved decisions, blockers, risks and open questions in date order. Each role sees only what it may read.
- **Bus factor** (`/bus-factor`, reviewers): claims whose evidence all comes from one person, so the loss of that person matters most.
- **Audit log** (`/audit`, reviewers): who changed, approved, released, acknowledged or resolved what, and when.
- **Projects** (`/projects`): switch between projects you belong to. Admins add members and create projects.
