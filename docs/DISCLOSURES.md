# Disclosures

Required by the event rules (templates, reused code, external services, AI assistance).

## Build window
Development of this repository started on 2026-11-08, for Round 2. The Round 1 plan
(research, interviews, survey, slide deck) was written before building and contains no
product code. Commit history in this repository shows when each part was written.

## AI assistance
Claude (Anthropic) was used as a coding assistant to write and review code, tests,
documentation and the synthetic demo data in this repository. The participant directs the
work, reviews the output and is responsible for the submission.

## Templates and reused code
None. No template, boilerplate or previously written code is used.

## Libraries
FastAPI, Uvicorn, SQLAlchemy, Pydantic, Jinja2, python-multipart, HTTPX, pytest. All are
used under their open-source licences.

## External services
- GitHub REST API (`api.github.com`): used to read public repositories, unauthenticated, read
  only. See `app/ingest/github.py`.

- An LLM provider is optional and configured by the operator (`LLM_BASE_URL`, `LLM_API_KEY`,
  `LLM_MODEL`). Any OpenAI-compatible service works. Only non-confidential chunks are sent to
  it by default. The provider actually used for the submitted demo will be named here.

Planned and to be listed here when added: a hosting provider for the deployed demo.

## Data
All demonstration data in `data/demo/` is synthetic. No real credentials or confidential
workplace material is used. The "API key" in the demo chat is invented.
