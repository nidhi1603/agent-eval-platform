# Agent Eval Platform

A reproducible evaluation harness for LLM support agents on Sierra's τ-Knowledge banking benchmark (tau2-bench v1.0.1, pinned). It was used to test whether harness components can make the same model (gpt-5-mini) complete more banking tasks than tau2's standard agent.

**Result, stated plainly:**
- Several components changed the behaviour they targeted in local tests.
- None produced a validated gain in completed tasks in full conversations.
- The value here is the evaluation engineering and the evidence, not a better banking agent.

| Read | For |
|---|---|
| [docs/RESULTS.md](docs/RESULTS.md) | every experiment side by side: full-conversation comparisons, targeted tests, 13 measurement defects found and fixed, spend |
| [docs/REPORT.md](docs/REPORT.md) | the technical report: hypotheses, findings, and why each line was stopped |
| [docs/WRITEUP.md](docs/WRITEUP.md) | phase 1 in detail (instructions and diagnostics) |
| [EXPERIMENTS.md](EXPERIMENTS.md) | the chronological log, including each review's corrections |

## What the platform does

- **Runs tasks through tau2's official path** and saves complete traces: messages, tool calls, retrievals, official evaluation, spend and provenance (`bench/run.py`).
- **Paired, pre-registered batches.** A frozen plan (tasks, arms, settings, decision rule, budget) is run with balanced arm order, parallel workers, a resume journal, and no retries (`bench/batch.py`).
- **Spend admission control.** Every model call reserves its worst-case cost before sending, and runs settle at the provider-billed cost. Each paid run is checked against the approved amount (`bench/budget.py`).
- **Answer independence.** The agent is built without the task. Differential replay flags any agent-visible output that depends on the hidden answer key (`bench/independence.py`). This found a benchmark exposure, reported upstream as sierra-research/tau2-bench#574.
- **Harness components**, each behind its own flag and each with a negative control (all 30 reference solutions keep their reward):
  - a direct-tool adapter;
  - checks before giving up, verification and writes;
  - capability search;
  - the verification-evidence and identity-disclosure checks;
  - proposal-time nudges (`bench/harness.py`, `bench/guard.py`, `bench/nudge.py`).
- **Targeted tests.** Saved-prefix continuations, restored conversations, and next-message probes with exact replay checks (`bench/continuation.py`, `bench/resume.py`, `bench/*_probe.py`).
- **Blind review tooling.** Exports for blind, two-reader labelling and frozen verdict functions (`research/*/`).

## Run it

Requires [uv](https://docs.astral.sh/uv/) and the pinned tau2-bench data (see `bench/pins.py`).

```bash
make test               # the test suite, offline
make demo               # deterministic checks (benchmark exposure and fix, a failure end to end) and saved results; offline, $0
make demo-provenance    # the intercepted-draft verification bug and its fix, end to end on a scripted conversation; offline, $0
```

A live conversation or a batch needs an OpenAI key in `.env`. It runs only under an explicit budget:

```bash
uv run --extra bench python -m bench.batch experiments/<PLAN>_plan.json --approved-usd <the plan's budget> --workers 2
```

## Limits

- One model (gpt-5-mini), one domain, 30 development tasks. The 67 held-out tasks were never run.
- Small samples: every result is a development screen, not a benchmark score or a leaderboard-comparable number. The official protocol is all 97 tasks × 4 trials.
- Many labels come from blind reading of transcripts, not from a validated classifier.
- Spend figures are estimates from token usage.

## The Kubernetes platform (secondary)

The repo also contains a run-orchestration service: a FastAPI API, Postgres, a Redis queue, and a dispatcher that runs each trial as an isolated Kubernetes Job. It enforces least privilege and a concurrency cap, and computes pass^k (`app/`, `deploy/`, [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)). It runs only a deterministic stub agent. All experiments above used the local runner in `bench/`. `make up && make smoke` starts it on kind.

Implementation was AI-assisted (Claude Code), with a second model reviewing each stage. Research direction, spending approvals and stopping decisions were the author's.
