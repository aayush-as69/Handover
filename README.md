<div align="center">

<img src="docs/assets/handover-logo.svg" alt="Handover logo" width="104" height="104" />

# Handover

### When someone leaves, the reasons shouldn’t.

**Evidence-backed project knowledge transfer.** Turn scattered project context into a handover a person has reviewed and signed off.

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Ready-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![CI](https://github.com/aayush-as69/Handover/actions/workflows/ci.yml/badge.svg)](https://github.com/aayush-as69/Handover/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

<p><strong><a href="https://handover-2hpd.onrender.com">Live demo</a></strong> · the demo password is set by the project team</p>

<a href="https://render.com/deploy?repo=https://github.com/aayush-as69/Handover">
  <img src="https://render.com/images/deploy-to-render-button.svg" alt="Deploy to Render" />
</a>

</div>

---

## The problem

When a teammate leaves, their code stays. The context behind it goes: why a decision was made, who owns what, which risk everyone quietly works around.

That knowledge sits in chats, meeting notes and task boards, or only in someone’s head.

## What Handover does

It reads those sources, proposes claims, and shows each one next to the exact quote it came from. A person approves every claim before it reaches the handover.

> Not another AI summary. A reviewable record of what the team knows, where it came from, and what still needs attention.

- **Every claim cites its source.** Quotes are checked word for word against the original text.
- **Nothing publishes without a person.** Approval is human, always. Sign-off creates a numbered, unchangeable release.
- **People see what their role allows.** Confidential material and secrets stay out of the handover, and out of any outside AI service.
- **It says what is missing.** Conflicting sources, unanswered questions and knowledge held by one person are flagged.

![Handover review queue](docs/assets/screenshots/review-queue.png)

![A claim with its supporting evidence](docs/assets/screenshots/claim-evidence.png)

## How much to trust a claim

| Label | What it tells you |
|---|---|
| **Quote-verified** | A supporting quote was found word for word and agrees with the claim. It does not prove the claim is true. |
| **Inferred** | Quotes exist, but the claim says more than they do. |
| **Conflicting** | A source says the opposite. |
| **Unsupported** | No usable quote was found. |

The labels come from mechanical checks, never from a model. Measured results, including the cases where the checks must not fail, are in the [evaluation report](docs/evals/eval-report.md).

## Try it

```bash
git clone https://github.com/aayush-as69/Handover.git && cd Handover
python3.12 -m venv .venv && source .venv/bin/activate      # Windows: py -3.12 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.lock -r requirements-dev.txt
export DEMO_MODE=1 DEMO_PASSWORD="choose-a-local-password"  # PowerShell: $env:DEMO_MODE="1"; $env:DEMO_PASSWORD="..."
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/login. The demo project is synthetic. Sign in as:

| User | Role | Try |
|---|---|---|
| `meera` | Approver | Review claims and sign off a release |
| `riya` | Admin | Add sources and run extraction |
| `kabir` | Viewer | Read the handover and acknowledge it |
| `rao` | Restricted | See what a reduced-clearance reader gets |

New here? The in-app **Guide** walks through it in two minutes, and the [demo walkthrough](docs/16-demo-walkthrough.md) is a seven-minute script.

## Documentation

Everything technical lives in [`docs/`](docs/README.md).

| If you want to | Read |
|---|---|
| Understand the product | [Overview](docs/01-project-overview.md) · [Features](docs/FEATURES.md) · [Demo walkthrough](docs/16-demo-walkthrough.md) |
| Set it up and develop | [Development setup](docs/10-development.md) · [Testing](docs/09-testing.md) |
| See how it is built | [Architecture](docs/04-architecture.md) · [Database](docs/05-database-design.md) · [Security](docs/07-security.md) · [Routes](docs/08-api-reference.md) |
| Run it for a team | [Deployment](docs/11-deployment-operations.md) · [Background jobs and monitoring](docs/17-jobs-and-observability.md) |
| Check the quality claims | [Evaluation](docs/18-evaluation.md) · [Limitations and roadmap](docs/13-limitations-roadmap.md) |

## Status and limits

- Verification checks wording, not truth, currency or completeness. A person decides.
- Secret masking and redaction are pattern based and can miss unusual values.
- The built-in extractor reads notes and task files; reading chat needs an optional LLM provider, whose quality on real data has not been measured yet.
- Built for a demo or a small team on one instance. See [limitations](docs/13-limitations-roadmap.md) before using real project data.

## License

Released under the [MIT License](LICENSE). Built by **Aayush Singh** for the CodeFrontier Hackathon (team STARTEND). AI tools assisted with planning and implementation; the code and project decisions were reviewed by the author.
