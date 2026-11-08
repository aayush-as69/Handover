# Handover

Keep critical knowledge from leaving with people.

Handover turns scattered project activity (meeting notes, team chat, a task board and a
GitHub repository) into a reviewed handover for the person taking over. Every claim carries
its evidence, a confidence level and a sensitivity label. A human approves the handover
before anyone sees it, and each viewer only sees what their role allows.

Built for the CodeFrontier hackathon (We Code Coders), by team STARTEND.

## Status
Round 2, in development. Working so far:
- Claim data model with evidence, confidence, sensitivity, review status and version history
- Access rules enforced in the core (sensitivity is inherited from evidence; only approved
  claims reach a handover; rejected claims never appear)
- Synthetic demo project with deliberately planted traps (`data/demo/`)

Not built yet: source ingestion, AI extraction, verification, review screen, role views,
deployment. See the roadmap below.

## Trust rules the code enforces
1. A claim is `unsupported` until the verification pass proves otherwise.
2. A claim's sensitivity is the highest label among itself, its evidence chunks and their
   sources. Confidential evidence makes the whole claim confidential.
3. A handover contains only approved claims. Editing an approved claim sends it back for
   approval. Rejected claims never appear.
4. Only approvers and admins can open the review queue.

## Run it
```bash
pip install -r requirements-dev.txt
pytest
uvicorn app.main:app --reload
```

## Roadmap
1. Foundation: data model, access rules, demo data (done)
2. Source ingestion: notes, chat, task CSV, GitHub
3. Claim extraction with exact evidence snippets
4. Verification pass and confidence labels
5. Review screen with version history
6. Role login, filtered handover view, acknowledgement
7. Deployment, tests and architecture document

See `docs/DISCLOSURES.md` for AI assistance, libraries and data.
