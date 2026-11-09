# Handover

Keep critical knowledge from leaving with people.

Handover turns scattered project activity (meeting notes, team chat, a task board and a
GitHub repository) into a reviewed handover for the person taking over. Every claim carries
its evidence, a confidence level and a sensitivity label. A human approves the handover
before anyone sees it, and each viewer only sees what their role allows.

Built for the CodeFrontier hackathon (We Code Coders), by team STARTEND.

## What it does
1. **Ingest** meeting notes, chat exports, task CSVs and public GitHub repositories (commits,
   issues, pull requests, changed files, reviews). Secrets are masked before anything is stored.
2. **Extract** draft claims, each pointing at exact quotes. A rule-based extractor runs locally
   with no key; an optional LLM extractor (any OpenAI-compatible provider) also reads chat.
3. **Verify** every quote against its source. Each claim gets a confidence label with a reason.
4. **Review** each claim beside its evidence: approve, edit, reject or reopen, with version
   history and word-level diffs. Conflicts between sources and "Questions Before I Leave"
   (missing owners, reasons, open items) are raised for the reviewer.
5. **Sign off** as an immutable, numbered release. Each person then sees only the approved
   claims their role allows, with emails, phone numbers and amounts redacted by role.
   Reviewers can preview any role. The incoming person acknowledges the release.

Roles: `admin`, `approver`, `viewer`, `restricted`. The server decides access; the UI never does.

## Status
Feature-complete for the planned scope. Latest GitHub Actions run (9 Nov 2026, commit
`a6d9527`): 422 tests passed on SQLite and 422 on PostgreSQL 16, including a real-browser
walkthrough, and `pip-audit` found no known vulnerabilities. Run `pytest` for the current count.
Hosting is configured for Render (`render.yaml`) but has not been verified on Render itself, and
the LLM paths have never been run against a live model. Both are listed under "Known
limitations".

Not built: multiple projects per deployment, an audit-log page, acknowledgement history by
name, richer conflict visualisation, and rate limiting shared across servers.

## Documents
| File | Contents |
|---|---|
| `docs/ROUND2.md` | Round 2 build document: architecture, trust rules, testing, limitations |
| `docs/FEATURES.md` | Conflict detection, Questions Before I Leave, role redaction |
| `docs/PRODUCTION_READINESS.md` | External review items and their status |
| `docs/OPERATIONS.md` | Production settings, migrations, backups, recovery |
| `docs/DISCLOSURES.md` | Libraries, services and AI assistance used |

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
pip install -r requirements.lock -r requirements-dev.txt   # exact tested versions
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
- **Migrations exist (Alembic) but are minimal.** One initial migration. A database created by
  an older build is refused until you run `python -m app.db adopt` (it stamps a matching schema
  or creates missing tables; anything else is refused untouched). Back up first.
- **Login limits are persistent and shared** (database backed), within 5 minutes: 5 failures
  per account per address, 20 per account overall, 15 different accounts tried from one address,
  100 failures from one address. A few typos in a shared office do not lock anyone out. Behind a
  proxy set `TRUST_PROXY` so the address is read from the last `X-Forwarded-For` entry; without a
  proxy leave it off, or the header can be forged.
- **Request rate limiting is in memory, per server process:** 300 requests a minute and 30 login
  posts a minute per address (`RATE_LIMIT_PER_MIN`, `LOGIN_RATE_PER_MIN`; 0 turns it off). It is a
  first defence, not a substitute for a proxy or CDN in front, which the host must provide.
- **GitHub:** public repositories only; up to 100 items per list across at most 5 pages; files,
  diffs and reviews for the newest 5 pull requests and commits; diffs cut near 1,100
  characters; subject to GitHub's unauthenticated rate limit.
- **Conflict detection is rule based:** a fixed list of technology categories plus any
  `topic`/`value` an LLM fills in. It misses others and can flag a mere mention of a related tool.
- **Checklist questions are simple text rules**; expect noise, reviewers can dismiss them.
- **Redaction and secret masking are pattern based** and lean towards hiding too much. Masking
  covers common cloud, source-host, payment, chat and LLM keys, JWTs, bearer and basic auth
  headers, URLs with passwords, private key blocks, `password=`/`secret:`-style assignments, and
  unlabelled random-looking strings (24+ characters, high entropy). Git hashes, UUIDs, paths and
  ordinary identifiers are left alone, so a short or word-like secret can still slip through.
- **Chat dates** are read as day/month/year unless the file clearly uses month/day/year.
- **The rule-based extractor reads structure only.** Chat meaning, cross-source conflicts and
  recurring problems need the LLM extractor.
- **Confidential chunks** are not sent to a remote model by default, so LLM mode makes no
  claims from them.
- **One project per deployment.** The review queue filters, counts and pages in SQL; other
  pages load a project's claims in a fixed number of queries (tested not to grow with claim count).

## Roadmap
1. Foundation: data model, access rules, demo data (done)
2. Source ingestion: notes, chat, task CSV, GitHub (done)
3. Claim extraction with exact evidence snippets (done)
4. Verification pass and confidence labels (done)
5. Login and review screen with version history (done)
6. Handover sign-off, filtered role views, acknowledgement, source upload (done)
7. Deployment configuration, tests and architecture document (built: `render.yaml`, 400+ tests
   with CI on SQLite and PostgreSQL, `docs/`; **not yet verified:** a live Render deployment, a
   live LLM provider run, and a backup restore on the hosting platform)
8. Later: multiple projects per deployment, an audit-log page, acknowledgement history by person,
   better conflict visualisation, extraction reports, better evaluation of semantic checks

See `docs/DISCLOSURES.md` for AI assistance, libraries and data.
