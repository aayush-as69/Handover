<div align="center">

<img src="assets/handover-logo.svg" alt="Handover" width="48" />

# 18 — Evaluation

<sub>Handover · Product and engineering documentation</sub>

</div>

---

Handover's promise is that claims are traceable and that a made-up claim is not trusted. The evaluation suite in `tests/evals/` measures that, and the latest result is in [`evals/eval-report.md`](evals/eval-report.md).

| Fixture | Question |
|---|---|
| `claim_accuracy.json` | Does the extractor find the decisions, owners, risks and blockers a careful reader would? |
| `evidence_accuracy.json` | Does the quote check give the right label? Is "verified" ever given to an unsupported claim? |
| `hallucination_cases.json` | Are made-up claims dropped or kept below "verified"? Does the engine invent claims from sources with nothing in them? |
| `secret_leakage_cases.json` | Do secrets stay out of the database, out of what a remote model is sent, and out of anything a model writes back? |

```bash
python -m tests.evals.runner --engine rules --out docs/evals/eval-report.md --json docs/evals/eval-report.json
LLM_BASE_URL=... LLM_API_KEY=... LLM_MODEL=... python -m tests.evals.runner --engine llm --out docs/evals/eval-report-llm.md
pytest tests/evals          # the same checks as a regression gate in CI
```

## Reading the numbers

- Only claim accuracy and the "invents claims" half of the hallucination test depend on the engine. The quote check, the scripted-hallucination replay and the secret tests check Handover's own rules, so they must hold for any engine, including a bad one. `tests/evals/test_evals.py` proves this with a model that invents claims.
- The rules engine reads notes and task files, not chat, so its overall recall is low by design (chat 0%, notes and tasks 100% on the fixtures). The LLM engine is what reads chat; its report has not been generated yet because it needs a provider key.
- The gates in `runner.THRESHOLDS` are set at what the rules engine achieves today. Raising them is the way to keep a gain.

## What the suite has found

The first run showed that a secret echoed by a model in a claim's statement, value or quote would have been stored. The extraction pipeline now masks model output before saving and reports how many values it masked. The cases stay in the fixtures as a regression test.

## Limits

- Fixtures are small and written by the author. A high score shows the checks work on known cases, not that they catch every real-world failure.
- The quote check proves a quote exists and agrees with the claim's words. It cannot judge meaning.
- Secret patterns are pattern based; unusual formats may not be recognised.
- The older extraction benchmark (`python -m app.quality`, labelled kiosk project in `data/eval`) is kept; the two measure different things.
