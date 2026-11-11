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
