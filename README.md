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

Not built yet: review screen, role views, deployment. See the roadmap below.

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

## Confidence labels
| Label | Meaning |
|---|---|
| verified | A supporting quote was found word for word in its source, and the claim's key terms, numbers and negation agree with it. |
| inferred | Quotes were found, but the claim says more than they do (extra terms, numbers or dates, or a flipped negation). A human must judge it. |
| conflicting | A quote found in the sources contradicts the claim. |
| unsupported | No quote could be found in any source, or there is no evidence. |

Every label carries a note explaining why, so a reviewer can see what the check found.

## Run it
```bash
pip install -r requirements-dev.txt
pytest
python -m app.demo                 # load the synthetic demo project and print a summary
python -m app.demo --extract rules # ...and extract draft claims with no API key
uvicorn app.main:app --reload
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

## Known limitations (so far)
- Secret masking is pattern based and leans towards masking too much. It will not catch every
  possible credential format.
- Chat dates are read as day/month/year unless the file clearly uses month/day/year.
- Live GitHub reading covers public repositories only, up to 100 commits, issues and pull
  requests, and is limited by GitHub's unauthenticated rate limit.
- There is no login or upload screen yet, so nothing is exposed over HTTP except `/health`.
- The rule-based extractor reads structure only. It cannot understand chat, spot conflicts
  between sources or find recurring problems; those need the LLM extractor.
- The LLM extractor is tested against simulated provider responses. Its quality on a live
  model has to be checked by running it with a real key and reviewing the output.
- Confidential chunks are not sent to a remote model by default, so no claims are generated
  from them in LLM mode.
- Verification is a coarse text check. It catches invented quotes, drifting paraphrase,
  made-up numbers and flipped negation. It cannot judge meaning, which is why a human approves
  every claim. Detecting conflicts between claims from different sources, and finding missing
  reasons and owners, are separate features that are not built yet.

## Roadmap
1. Foundation: data model, access rules, demo data (done)
2. Source ingestion: notes, chat, task CSV, GitHub (done)
3. Claim extraction with exact evidence snippets (done)
4. Verification pass and confidence labels (done)
5. Review screen with version history
6. Role login, filtered handover view, acknowledgement
7. Deployment, tests and architecture document

See `docs/DISCLOSURES.md` for AI assistance, libraries and data.
