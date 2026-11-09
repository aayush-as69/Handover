"""Live provider check. Skipped unless you opt in, because it calls a real model and costs a little.

    LIVE_LLM_TEST=1 LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai \
    LLM_API_KEY=... LLM_MODEL=gemini-2.0-flash python -m pytest tests/test_live_llm.py -v -s

Any OpenAI-compatible provider works (Gemini, OpenAI, Groq, Together, a local Ollama).
It sends one small, invented note (no real data) and checks the reply is usable: at least one
claim, and every quote it cites really appears in the note word for word.
"""
import os
from datetime import datetime, timezone

import pytest

from app.enums import Sensitivity, SourceKind
from app.extract import ChunkView
from app.extract.llm import llm_from_env

pytestmark = pytest.mark.skipif(
    os.environ.get("LIVE_LLM_TEST") != "1", reason="set LIVE_LLM_TEST=1 and the LLM_* variables to run")

NOTE = (
    "Sprint review, 3 October. We decided to use PostgreSQL as the only datastore because the "
    "team already knows it. Riya owns the nightly backup job. Open item: nobody has tested "
    "restoring a backup yet. The payment gateway is Stripe."
)


def test_a_real_model_returns_usable_claims_with_genuine_quotes():
    chunk = ChunkView(id=1, source_name="review.md", source_kind=SourceKind.notes, locator="para 1",
                      author="Riya", occurred_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
                      text=NOTE, sensitivity=Sensitivity.team)
    with llm_from_env() as extractor:
        out = extractor.extract([chunk])
    print(f"{len(out.claims)} claims, warnings: {out.warnings}")
    assert out.claims, "the model returned no usable claims"
    for claim in out.claims:
        print("-", claim.statement)
        for ev in claim.evidence:
            assert ev.snippet in NOTE, f"quote not in the source: {ev.snippet!r}"
