<div align="center">

<img src="assets/handover-logo.svg" alt="Handover" width="48" />

# 15 — Improvements: quality report, timeline, projects

<sub>Handover · Product and engineering documentation</sub>

</div>

---

## 1. Extraction quality report

`python -m app.quality --engine rules|llm` runs an extractor over a small invented project
(`data/eval/`: a chat export, planning notes and a task sheet) and scores it against a list
of claims a careful reader should find (`data/eval/gold.json`). A claim counts as found when it
has the right type, contains the key words, and is backed by the right kind of source.

Reported: recall and precision per source kind, how many decision reasons were kept, the
confidence labels given, quotes that could not be found in their source, and claims labelled
quote-verified that match nothing expected (verification proves a quote exists, not that the
claim matters, so this shows what a human still filters).

**Measured baseline (rule-based extractor)** is in `docs/quality/rules-baseline.md`: it finds
all notes and task claims and none of the 9 chat claims, because it does not read free text.
That gap is what the LLM extractor is for.

**Live model numbers have not been measured yet.** To produce them, set `LLM_BASE_URL`,
`LLM_API_KEY` and `LLM_MODEL` and run:

```
python -m app.quality --engine llm --out docs/quality/llm-report.md --json docs/quality/llm-report.json
```

Only then should the README claim any live accuracy. The scorer itself is tested with scripted
models, including one that invents a quote (verification catches it) and one that adds noise
(precision drops), in `tests/test_quality.py`.

## 2. Decision timeline and bus-factor view

- `/timeline` lists dated decisions, blockers, risks, open questions and next actions in order,
  each with its confidence label and sources. Readers see approved claims their role may read,
  and only once a current sign-off exists (the same gate as the handover). Reviewers may add
  drafts with `?drafts=1`; drafts are marked "not approved yet". Rejected claims never appear.
  The date is the earliest dated passage behind the claim; undated claims are listed last.
- `/bus-factor` (reviewers) shows, per named author, the claims whose evidence comes only from
  that person's messages or commits. Notes and task sheets name no author, so those claims are
  counted as "without a named author" rather than guessed. Claims above the reader's clearance
  are skipped.

Code: `app/timeline.py`, `app/workspace_web.py`. Tests: `tests/test_workspace.py`.

## 3. Projects, audit log and named acknowledgements

- **Projects.** Admins create projects and add or remove people at `/projects`. Everyone else
  sees only projects they were added to; admins reach all. A project with no members is
  visible to admins only. The current project is kept in the session and re-checked on every
  request, so removing someone takes effect on their next click. Claim and source-text pages
  check project access too, so a guessed id from another project returns "not found".
- **Migration `0003`** creates `project_members` and gives every existing user access to every
  existing project, so an existing deployment behaves as before until an admin changes it.
- **Audit log** (`/audit`, reviewers): one trail of claim drafts, edits, approvals, rejections,
  verification events, release sign-offs, acknowledgements, conflict resolutions, answers and
  loaded sources, filterable by kind. Claim events appear only for claims the reader's role may
  open.
- **Named acknowledgements.** The release history lists, for each release, who signed it off
  and who acknowledged it, with times.

Code: `app/projects.py`, `app/audit_log.py`, `app/workspace_web.py`.

## Limits

- Bus factor relies on source authors. Without chat or GitHub sources it has little to show.
- Timeline dates come from source passages; a claim with no dated evidence has no date.
- Projects share one user table and one set of roles: a person has the same role in every
  project they belong to.
- The quality set is small (17 expected claims) and synthetic; treat the numbers as a
  comparison between extractors, not as a general accuracy figure.

## Later additions

- **Takeover brief** (`/handover/brief`): where to start, built only from approved claims the role may read.
- **Connections** on each claim page: sources, people, other claims on the same sources, open questions. Recorded links only.
- **Freshness** (`/freshness`): the age of the newest dated supporting passage per claim, with fixed thresholds (30 and 90 days). Age is a reason to re-check, not proof a claim is wrong.
- **Release comparison** on the release history page: added, reworded and dropped claims and conflicts resolved since the previous release.
- **Slack export reader**: upload a channel's JSON export as a chat source. Each message keeps its author, time and channel, for example `Slack #backend message 12 (04 Nov 14:21)`.
- **Jira CSV reader**: upload a Jira CSV export as a task source. Jira column names are mapped, and the Updated or Created date is kept so freshness can be measured.
- **Background extraction**: LLM extraction runs as a job on a worker thread and its status shows on the Sources page. This is an in-process job, not a distributed queue. A job does not survive a restart, and a job still active at startup is marked failed. Rule-based extraction stays immediate. Migration `0004` adds the `jobs` table.
- **Audit log filters**: by person, text and date range, with each entry linking to what it concerns.
- **Knowledge concentration** on the bus-factor page: per kind of claim, the share resting on one person's words alone, with a suggested action. Small groups show their counts, so "1 of 1" is not read as a trend.
- **Guided takeover** (`/onboarding`): the brief read one topic at a time, with a reading-time estimate (words at 200 a minute) and a closing list of what is still unresolved. Nothing is stored; the step is in the URL.
- **Extraction quality page** (`/quality`): shows the saved scoring reports, so a live-model report appears beside the rule baseline once it is committed.
- **Demo walkthrough**: `docs/16-demo-walkthrough.md` gives a fixed seven-minute order, expected questions and honest answers.
- **Navigation**: the primary bar keeps the few pages used most; everything else is grouped under a **More** menu that works without JavaScript.
- **Claim page**: a plain list of what a label checked and a reminder of what it does not mean.
- **Per-project roles**: an admin can give a member a different role in each project (approver, viewer or restricted). With none set, the person's default role applies. The role for the project being viewed is applied to every request and never written back to the account. Admin is instance-wide and is not a per-project role, so no project can promote anyone to admin. Migration `0005` adds a nullable `role` column to `project_members`, so existing access is unchanged.
- **Evidence breakdown and source tree** on each claim page: quotes found word for word, number and kinds of sources, contradicting quotes, any model opinion (advisory) and the exact passages the claim rests on. These are counts, not scores.
- **Conflicts** now cite the source passage behind each side.
- **Sources page** shows when each source was loaded and the date of its newest content.
- **Workflow diagram**: `docs/assets/workflow.svg` compares a typical AI summary with Handover's evidence-first flow.
- **Bulk review** (`/review/bulk`): approve many quote-verified claims with no conflict or model doubt in one step. Nothing is pre-ticked, each claim is re-checked on submit, and each approval is recorded under the reviewer's name.
- **Markdown export** of the takeover brief (`/handover/export.md`): same content and limits as the page for the viewer's role.
- **Teams**: an admin can group people into a named team and add the whole team to a project with a role. It copies current members and is not a live link.
- **Onboarding progress**: a person can confirm each topic of the guided takeover. Progress is kept per person, project and release, so a new release starts the walkthrough again. Migration `0006` adds the `teams`, `team_members` and `onboarding_steps` tables.
- **Claim comments**: reviewers can discuss a claim without changing its status. Comments appear in the audit log. Migration `0007` adds the `claim_comments` table.
- **Inbox** (`/inbox`): what needs attention in the current project for the person's role there, such as claims waiting, open conflicts, stale evidence and a release to acknowledge. It only reads.
- **Search** (`/search`): finds claims, and questions for reviewers, in the current project and within the role's clearance. Wildcard characters are treated literally.
- **JSON export** (`/handover/export.json`): the takeover brief for other tools, with the same content and limits as the page.
- **Comment authors follow the account**: comments store the author's account as well as the name written at the time, so a rename carries over. Migration `0008`.
- **Queue and worker for jobs**: `JOB_MODE=queue` makes the web process only queue a job; `python -m app.worker` claims and runs it, with a heartbeat so a dead worker's job is put back. Default stays the in-process thread. Migration `0009` adds `claimed_by` and `heartbeat_at`. See `docs/17-jobs-and-observability.md`.
- **Evaluation suite** (`tests/evals/`): claim accuracy, evidence accuracy, hallucination and secret-leak cases with a runner that writes `docs/evals/eval-report.md`. It also runs as a regression gate. Its first run found that a secret echoed by a model could be stored in a claim; model output is now masked before saving.
- **Release claims table**: `handover_release_claims` holds one row per claim in a release, append-only like the release. Existing releases are backfilled from `claims_json`, which stays as a frozen copy. Migration `0010`.
- **One throttle module**: `app/throttle.py` holds the request limiter and the login lockout. The unused in-memory login throttle and the single-key lockout helpers were removed.
- **Metrics and access log**: `/metrics` (bearer `METRICS_TOKEN` or admin session) with request latency, login failures, 429s, extraction duration, LLM failures, DB errors and job counts, plus one JSON access-log line per request.
- **Four answers per claim**: each claim page opens with what the problem is, why it matters, what evidence backs it and what to do next; the review queue gains a Next step column. Chosen by fixed rules from recorded facts, not generated.
- **README as a landing page**: technical detail moved to `docs/10`, `docs/17` and `docs/18`.

