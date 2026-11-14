# Evaluations

Fixtures and a runner that measure Handover's trust checks and its extractor.

| File | Question it answers |
|---|---|
| `claim_accuracy.json` | Does the extractor find the decisions, owners, risks and blockers a careful reader would? |
| `evidence_accuracy.json` | Does the quote check label each claim correctly? Never "verified" for an unsupported one. |
| `hallucination_cases.json` | Are made-up claims dropped or kept below "verified"? Does the engine invent claims from empty sources? |
| `secret_leakage_cases.json` | Do secrets stay out of the database, out of what a remote model is sent, and out of anything a model writes back? |

```bash
python -m tests.evals.runner --engine rules                      # no key needed
python -m tests.evals.runner --engine rules --out docs/evals/eval-report.md --json docs/evals/eval-report.json
LLM_BASE_URL=... LLM_API_KEY=... LLM_MODEL=... python -m tests.evals.runner --engine llm --out docs/evals/eval-report-llm.md
pytest tests/evals                                               # the same checks as a gate
```

All text and "secrets" are invented. Only claim accuracy and the "invents claims" half of the hallucination
evaluation depend on the engine; the rest check Handover's own rules and must hold for any engine. The latest
rules-engine report is `docs/evals/eval-report.md`. Add a case by adding an entry to the matching JSON file.

An evaluation that only ever passes is not measuring anything, so keep adding the failures you find. The first
run of this suite found that a secret echoed by a model could be stored in a claim; the pipeline now masks it.
