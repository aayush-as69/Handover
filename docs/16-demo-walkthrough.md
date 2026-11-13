# Demo walkthrough (about 7 minutes)

A fixed order for presenting Handover so the story holds together. All data is synthetic. The demo password is the one set in the hosting environment; do not write it on slides.

## Before you start (5 minutes ahead)

1. Open the live site once so the free host wakes up. The first request after idle can take about a minute.
2. Sign in as `riya` (admin) in one window and `kabir` (viewer) in a private window.
3. Optional but recommended: as `meera` (approver), open **Bulk review**, tick the clean claims, approve them, then **Handover → Sign off**. This gives release 1 and makes the brief, timeline and guided read look full. Do it before the audience arrives; it is a normal human approval, nothing is skipped.

## The story (one sentence)

Riya is leaving the CampusEvents project. Kabir takes over. Everything Riya knew is in notes, chat and tasks. Handover turns that into claims, each tied to the exact words it came from, and a person approves every one.

## Steps

| # | Where | Say | Show |
|---|---|---|---|
| 1 | **How it works** | "The six steps, and what each label does and does not mean." | The label list. Stress: a label checks the words, never that the claim is true. |
| 2 | **Review queue** (as meera) | "Software drafted these. Nothing is trusted yet." | Open a quote-verified claim: the highlighted quote, **Evidence breakdown**, **Where it comes from**. |
| 3 | A weak claim | "This one is inferred or unsupported, so approval needs a written reason." | Try approving it without a note; show the refusal. |
| 4 | **Conflicts** | "Two sources disagree about the datastore. The tool will not pick a winner." | Each side cites its source. Resolve it and note it is recorded under your name. |
| 5 | **Bulk review** | "For the clean ones, a reviewer can approve many at once, still by choosing them." | Nothing is pre-ticked. Only quote-verified, conflict-free claims are listed. |
| 6 | **Handover → Sign off** | "A numbered release that cannot be edited afterwards." | **Release history** shows what changed since the last release. |
| 7 | Switch to **kabir** | "The new owner sees the same project, but only what his role allows." | **Takeover brief**, then **Guided takeover**: read a topic, confirm it, acknowledge. |
| 8 | **rao** (restricted) | "A mentor sees less. Higher-sensitivity text is hidden, not blurred." | Compare the same handover for rao and kabir. |
| 9 | Back to **riya / meera** | "What if knowledge is stuck in one head, or is old?" | **Timeline**, **Bus factor** (concentration bars), **Freshness**. |
| 10 | **Audit log** | "Who did what, and when." | Filter by person; open an entry. |
| 11 | **Projects** | "Several projects, with a different role in each." | A person who is approver in one project and viewer in another. |

## Answers to expect

- **Is the AI deciding?** No. The language model is optional and advisory. A rule-based extractor works with no key. A person approves every claim, and the quote check is mechanical.
- **Does "quote-verified" mean true?** No. It means the quote exists in the source and fits the claim. It does not mean true, current or complete. The freshness page exists because of that gap.
- **How good is the live model?** Not measured yet. The rule-based baseline is measured (see the **Extraction quality** page); a live-model report is the next step. Say so plainly.
- **Slack and Jira?** Exported files are read, with author and time kept. There is no live connection or scheduled sync.
- **Is it production-ready?** It runs on PostgreSQL with migrations, backup and restore, login lockout and tests in CI. Background jobs run inside the web process, not in a separate queue, and there are no organisations or separate tenants yet.
- **What about secrets in sources?** Detection is pattern based and may miss unusual formats; confidential text is withheld from remote models by default.

## If something goes wrong

- Slow first page: the free host is waking up. Talk through step 1 while it loads.
- A page shows "nothing is published yet" for kabir: the release was not signed off. Do step 6 as meera.
- Never improvise a number. If asked for a figure that is not on screen, say it has not been measured.
