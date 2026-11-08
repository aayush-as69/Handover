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
- Source ingestion: meeting notes, chat exports, task CSVs and GitHub data become dated,
  addressable chunks. Secrets are masked before anything is stored. Public GitHub
  repositories can be read live (no credentials); a bundled snapshot works offline.

Not built yet: AI extraction, verification, review screen, role views, deployment. See the
roadmap below.

## Trust rules the code enforces
1. A claim is `unsupported` until the verification pass proves otherwise.
2. A claim's sensitivity is the highest label among itself, its evidence chunks and their
   sources. Confidential evidence makes the whole claim confidential.
3. A handover contains only approved claims. Editing an approved claim sends it back for
   approval. Rejected claims never appear.
4. Only approvers and admins can open the review queue.
5. Secrets are masked at ingestion, so a raw credential is never stored, shown or sent to a
   model. A message that contained one is treated as confidential.
6. A source is parsed completely before anything is saved, so a bad file leaves nothing
   half-ingested. Identical content is never ingested twice.

## Run it
```bash
pip install -r requirements-dev.txt
pytest
python -m app.demo                 # load the synthetic demo project and print a summary
uvicorn app.main:app --reload
```

## Known limitations (so far)
- Secret masking is pattern based and leans towards masking too much. It will not catch every
  possible credential format.
- Chat dates are read as day/month/year unless the file clearly uses month/day/year.
- Live GitHub reading covers public repositories only, up to 100 commits, issues and pull
  requests, and is limited by GitHub's unauthenticated rate limit.
- There is no login or upload screen yet, so nothing is exposed over HTTP except `/health`.

## Roadmap
1. Foundation: data model, access rules, demo data (done)
2. Source ingestion: notes, chat, task CSV, GitHub (done)
3. Claim extraction with exact evidence snippets
4. Verification pass and confidence labels
5. Review screen with version history
6. Role login, filtered handover view, acknowledgement
7. Deployment, tests and architecture document

See `docs/DISCLOSURES.md` for AI assistance, libraries and data.
