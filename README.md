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

- Claim extraction into draft, evidence-linked claims, with two interchangeable extractors:
  a rule-based baseline that runs locally with no key (structured notes, tasks and GitHub
  only), and an LLM extractor for any OpenAI-compatible provider (also reads chat)

- Verification pass: every quoted snippet is checked against its source, and each claim gets
  a confidence label with a plain-language reason (see "Confidence labels" below)

- Login (salted PBKDF2, lockout after repeated failures, CSRF tokens, security headers) and a
  review screen: each claim beside its quoted evidence, the confidence label with its reason,
  approve / edit / reject / reopen, and a version history with word-level diffs

- Handover: an approver signs it off, then each person sees only the approved claims their
  role may see, grouped as first week, decisions, risks, dependencies and people. The
  incoming person acknowledges it. Admins can upload sources and run extraction in the browser.

- Also built: conflict detection across sources, a "Questions Before I Leave" checklist,
  field-level redaction with a "preview as another role" view, immutable numbered releases,
  Alembic migrations, and production settings (`APP_ENV=production`)

Not built yet: multiple projects per deployment, an audit-log page, acknowledgement history by
name, richer conflict visualisation, and rate limiting shared across servers. See "Known
limitations" below and `docs/PRODUCTION_READINESS.md`.

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
7. A remote (LLM) extractor never sees confidential chunks unless explicitly allowed. Local
   extractors may read them, because nothing leaves the server.
8. Extraction output is untrusted. Evidence must point at a chunk the extractor was given,
   claims without valid evidence are dropped, and source text is fenced inside the prompt as
   data, never instructions.
9. Draft claims start as `generated`. The pipeline never approves anything: a human does.
10. Confidence labels come from mechanical checks, never from a model's opinion. An invented
    or paraphrased quote is labelled `unsupported`, not quietly accepted.
11. The review queue and every claim action re-check role and clearance on the server. A claim
    above a reviewer's clearance returns "not found". Approving a claim that is not `verified`
    needs a written reason, and editing a claim re-runs the verification check.
12. Nobody except reviewers sees a handover before sign-off. After sign-off it is a live view
    of approved claims only, so rejecting, reopening or editing a claim removes it from every
    view at once. A person never learns how many claims their role hides.
13. Only admins can add sources. Uploads are size-limited, must be text, are masked for
    secrets, and the file name is reduced to a plain name.
14. A conflict is a prompt, never an edit: it does not change a claim's status or confidence,
    and a warning on the handover only names conflicting claims that reader may already see.
15. A leaver's answer appears in the handover only when every claim it concerns is visible
    to that reader, and is labelled as their own words, not a verified fact.
16. Inside visible claims, emails, phone numbers and (for the most restricted role) money
    amounts are hidden by role. Reviewers can preview each role's exact view.
17. Releases are immutable. A sign-off records which claims at which versions were approved,
    by whom and when. A claim edited, rejected or reopened afterwards drops out of the shared
    handover until the next release (fail closed). Acknowledgements belong to one release.
18. History is append-only. Claim versions (with the full state after each change),
    verification results, releases and quoted evidence cannot be updated or deleted; the
    database layer refuses it.
19. One handover per project, one copy of identical source content, one acknowledgement per
    person per release: all enforced by unique constraints, and creation, upload and
    acknowledgement handle simultaneous requests by keeping the winner.
20. Failed sign-ins are counted in the database, so lockout survives restarts and several
    server processes.
21. Model replies are validated for shape and type (a chunk id must be a real integer, text
    must be text, sizes are bounded, control characters stripped). The optional model
    "second opinion" can only add a warning that makes approval need a written reason. It
    never changes a label, and never sees confidential claims.
22. A claim cannot be `verified` while any quote it cites is missing from the sources: one
    valid quote beside one invented quote makes it `inferred`, with a note saying why.
23. If a signed-off claim is later edited, rejected or reopened, the release is stale:
    non-reviewers see nothing and cannot acknowledge until a reviewer signs off again as a new
    release. Approving extra claims does not invalidate a release.

## Confidence labels
| Label | Meaning |
|---|---|
| verified (shown as "quote-verified") | A supporting quote was found word for word in its source, and the claim's key terms (at least two, at least 60%), numbers and negation agree with it. It does **not** mean the claim is true, current or complete. A person decides that. |
| inferred | Quotes were found, but the claim says more than they do (extra terms, numbers or dates, or a flipped negation). A human must judge it. |
| conflicting | A quote found in the sources contradicts the claim. |
| unsupported | No quote could be found in any source, or there is no evidence. |

Every label carries a note explaining why, so a reviewer can see what the check found.

## Run it
```bash
pip install -r requirements-dev.txt
pytest                             # SQLite; set TEST_DATABASE_URL=postgresql://... to run on PostgreSQL
python -m app.demo                 # load the synthetic demo project and print a summary
python -m app.demo --extract rules # ...and extract draft claims with no API key
DEMO_PASSWORD=choose-one python -m app.demo --extract rules   # demo logins: meera (approver), riya (admin), kabir (viewer), rao (restricted)
uvicorn app.main:app --reload      # then open /login (set SECRET_KEY for stable sessions)
# Production: APP_ENV=production needs SECRET_KEY (32+ chars), PostgreSQL DATABASE_URL, secure cookies.
# Migrations run at startup. See docs/OPERATIONS.md for backups and recovery.
```

### Using an LLM for extraction
Any provider that speaks the OpenAI chat-completions format works. Set three variables:
```bash
export LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai   # example: Gemini
export LLM_API_KEY=...                                                        # your key
export LLM_MODEL=...                                                          # a model name
python -m app.demo --extract llm
```
Keys are read from the environment only and are never stored or logged.

## Known limitations
- **Verification is a text check, not understanding.** It catches invented quotes, drifting
  paraphrase, made-up numbers and flipped negation. It cannot judge meaning, so a human approves
  every claim and the label reads "quote-verified". A cited quote that is missing downgrades the
  whole claim.
- **Sign-off is conservative.** Any edit, rejection or reopening of a signed-off claim hides
  the handover from non-reviewers until a new release is signed. Safe, but it can interrupt
  readers over a small fix.
- **LLM paths were never run live.** The LLM extractor and the semantic second opinion are tested
  only against simulated provider replies. Run `python -m app.demo --extract llm` with a real
  key and review the output before trusting it.
- **Deployment is configured but unverified.** `render.yaml` and the production settings are
  tested locally (SQLite and PostgreSQL), not on Render itself.
- **Migrations exist (Alembic) but are minimal.** One initial migration; a database created
  without Alembic is refused rather than guessed at. Back up before upgrading.
- **Login lockout is persistent** (database backed, 5 failures in 5 minutes per username). It is
  per username, not per address.
- **GitHub:** public repositories only; up to 100 items per list across at most 5 pages; files,
  diffs and reviews for the newest 5 pull requests and commits; diffs cut near 1,100
  characters; subject to GitHub's unauthenticated rate limit.
- **Conflict detection is rule based:** a fixed list of technology categories plus any
  `topic`/`value` an LLM fills in. It misses others and can flag a mere mention of a related tool.
- **Checklist questions are simple text rules**; expect noise, reviewers can dismiss them.
- **Redaction and secret masking are pattern based** and lean towards hiding too much. Neither
  catches every format.
- **Chat dates** are read as day/month/year unless the file clearly uses month/day/year.
- **The rule-based extractor reads structure only.** Chat meaning, cross-source conflicts and
  recurring problems need the LLM extractor.
- **Confidential chunks** are not sent to a remote model by default, so LLM mode makes no
  claims from them.
- **One project per deployment.** The review queue loads in full (no pagination yet).

## Roadmap
1. Foundation: data model, access rules, demo data (done)
2. Source ingestion: notes, chat, task CSV, GitHub (done)
3. Claim extraction with exact evidence snippets (done)
4. Verification pass and confidence labels (done)
5. Login and review screen with version history (done)
6. Handover sign-off, filtered role views, acknowledgement, source upload (done)
7. Deployment, tests and architecture document

See `docs/DISCLOSURES.md` for AI assistance, libraries and data.
