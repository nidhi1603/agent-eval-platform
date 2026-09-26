# Architecture

Status as of 2026-09-25. Legend: ✅ built and tested · 🔜 decided, next to build · 🧪 planned, decided per experiment · ❓ open decision.

## The system in one picture

```
                 ┌──────────────────────── RESEARCH LAYER ─────────────────────────┐
                 │ protocol · dev/test split · EXPERIMENTS.md · Canon/DAIR/arXiv    │
                 └──────────────────────────────┬──────────────────────────────────┘
                                                │ defines runs, reads results
   you / scripts                                ▼
        │  POST /runs            ┌──────────────────────────────┐
        └──────────────────────► │  API  (FastAPI, SQLAlchemy)  │◄───── start/result + per-trial token
                                 └───────┬───────────────┬──────┘                 ▲
                              runs,trials│               │enqueue                 │
                                         ▼               ▼                        │
                                 ┌─────────────┐  ┌─────────────┐                 │
                                 │ PostgreSQL  │  │ Redis queue │                 │
                                 └─────────────┘  └──────┬──────┘                 │
                                                         │ pop (≤ max concurrency)│
                                                  ┌──────▼──────┐                 │
                                                  │ Dispatcher  │── create Job ──┐│
                                                  └─────────────┘                ▼│
   ┌──────────────────────────── one Kubernetes Job per trial ────────────────────┴──────┐
   │  trial pod (non-root, read-only FS, no DB creds, no k8s token)                        │
   │   ┌─────────────────────────── tau2-bench simulation ──────────────────────────┐     │
   │   │  simulated customer (gpt-5.2)  ⇄  AGENT (our harness)  ⇄  bank tools + DB  │     │
   │   │                                         │                                   │     │
   │   │                          knowledge base (698 docs, "alltools" retrieval)     │     │
   │   └─────────────────────────────────────────┴──── grader: final DB state ───────┘     │
   └───────────────────────────────────────────────────────────────────────────────────────┘
                     │ traces, metrics, logs (OpenTelemetry)
                     ▼
        OTel Collector → Tempo (traces) · Prometheus (metrics) · Loki (logs) → Grafana
```

## Layer 1 — Platform ✅

| Component | Technology | Decision and reason |
|---|---|---|
| API | FastAPI + SQLAlchemy 2 | Creates runs, records trial results, computes pass^1..k. Typed schemas (Pydantic). |
| Database | PostgreSQL (in-cluster for dev; **RDS** on EKS) | Runs and trials are relational; pass^k needs per-task grouping. |
| Queue | Redis list (in-cluster for dev; **ElastiCache** on EKS) | Simple FIFO. Decouples "create run" from "start trials". |
| Dispatcher | Python service, single replica | Enforces the concurrency cap in one place so LLM rate limits and spend stay bounded. |
| Trial execution | **One Kubernetes Job per trial** | Isolation: a crashed or runaway trial can't affect others; each gets CPU/memory limits and a deadline. |
| Packaging | Docker image + Helm chart | Same chart on `kind` (free, local) and EKS; datastores switch by values. |
| Metric | pass^k = mean over tasks of C(c,k)/C(n,k) | τ-bench's reliability definition; unit-tested. |

**Security model (least privilege):**
- Trial pods get **no database credentials and no Kubernetes API token**. They report back to the API with a random per-trial token, compared in constant time; unknown trial and wrong token return the same 403.
- Only the dispatcher's service account may create Jobs, and only in its namespace.
- Pods run non-root, read-only root filesystem, all Linux capabilities dropped, seccomp default.
- A finished trial can't be overwritten (409).

**Verified:** 10 unit tests; end-to-end smoke (10 trials → 10 Jobs → results) on kind; cold install with zero restarts.

## Layer 2 — Benchmark integration 🔜

Inside each trial pod, the worker runs **one tau2-bench simulation** for one (task, trial index):

1. Check in with the API → receive task id, agent config, model.
2. Call tau2's `run_task(...)` with domain `banking_knowledge`, the agent, user simulator `gpt-5.2`, retrieval config `alltools`.
3. tau2's evaluator grades the **final database state** (or expected actions, per task).
4. Report `reward`, `agent_cost`, `user_cost`, turn count, and the trajectory to the API.

**Decisions:**
- User simulator **gpt-5.2** and retrieval **alltools**: identical to every leaderboard entry, so numbers are comparable.
- Our harness plugs in as a **registered tau2 agent** (`registry.register_agent_factory`); tau2's orchestrator, tools, and grader are untouched. That keeps the result a legitimate *custom* submission.
- **Integrity:** tau2 ships `LLMGTAgent`, a ground-truth ("GT") agent that sees the answers. It is never used. Our agent never reads `evaluation_criteria`, `required_documents`, or expected actions.

## Layer 3 — The harness 🧪 (revised 2026-09-26 after external review)

```
  OFFLINE (per workflow family, per KB version)        RUNTIME (every turn)
  ┌─────────────────────────────────────────┐          ┌──────────────────────────────────────────────┐
  │ Prerequisite extractor (compiler)        │          │ Conversation LLM (agent model)                │
  │ docs → source-linked rules:              │─rules──► │  ├─ retrieval: search + read       (days 8–14)│
  │  passage · action · conditions ·          │          │  ├─ task state + EVIDENCE RECORDS  (day 1 on)  │
  │  exceptions · required evidence ·         │          │  └─ ACTION-TIME CHECK before every write:     │
  │  version · executable/ambiguous/          │          │       real action + args vs rules + evidence  │
  │  unsupported                              │          │       → allow · block (with source) · ask     │
  └──────────────┬──────────────────────────┘          └──────────────────────────────────────────────┘
                 ▼
  Compiler evaluation: hand-written rule test set (allowed / forbidden / missing evidence / exceptions)
```

| Component | When | Decided approach |
|---|---|---|
| Task state + evidence records | Day 1 onward | Each fact the agent relies on is stored with its source tool call, the account/customer it concerns, and its freshness |
| Retrieval | Days 8–14 | Start from the benchmark's best retrieval; fix "searched but not read" (variant B) |
| Prerequisite extractor | Days 15–28 | Source-linked rules for 1–2 workflow families chosen from dev failures; builds on PCAS, Autoformalization into Policy-as-Code, COVENANT |
| Action-time check | Days 15–28 | Deterministic code checks the **actual** write action and arguments immediately before execution, against the rules and the evidence records; state updates from the result |
| Unknown handling | Days 15–28 | `ambiguous`/`unsupported` rules never permit an action: the agent asks, looks up evidence, or escalates |

**Two separate evaluations:** compiler correctness (do the rules preserve conditions, exceptions and
dependencies? checked against a hand-written test set) and runtime enforcement (did the agent obey the
rules with valid, current evidence? measured including false blocks).

Removed from the 60-day scope: model routing, sophisticated memory, the classifier-based trust gate
(authorization comes from evidence), distillation and training.

## Layer 4 — Observability 🔜 (minimal first)

- **First:** structured JSON event logs per trial: model calls, retrieval, actions, evidence records,
  check decisions, cost, outcome. Stored with the trial and queryable.
- **Later, only if time allows:** OpenTelemetry spans (GenAI conventions) and the Tempo/Prometheus/Loki/Grafana stack.

## Platform reliability gaps (found in review, to fix before real runs)

| Gap | Effect | Fix |
|---|---|---|
| Dispatcher crashes after popping a trial, before launching it | Trial lost; stays `queued` forever | Atomic move to a processing list (`LMOVE`) and requeue on restart |
| Trial pod dies or hits its deadline without reporting | Trial stays `running` forever | Reconciler marks trials `errored` when their Job failed or expired |
| No retry accounting | A retried trial could double-count cost | Record attempt number; count only the final attempt |

Already handled: duplicate launches (Job name collision → 409) and duplicate results (409).

## Layer 5 — Research workflow ✅

- `docs/RESEARCH_PROTOCOL.md`: goals, fixed setup, integrity rules, the cycle loop, failure taxonomy, statistics, reading map.
- `splits/banking_knowledge.json`: 30 dev / 67 test tasks, difficulty-stratified, fingerprinted to the task file.
- `EXPERIMENTS.md`: every experiment pre-registered and logged, including failures.
- Sources: Agent Canon → DAIR.AI Academy → weekly arXiv triage (`scripts/arxiv_scan.py`).

## Model roles

| Role | Model | Status |
|---|---|---|
| Simulated customer | gpt-5.2 | Fixed (leaderboard standard) |
| Agent (conversation) | Chosen by a small capability-and-cost pilot using model IDs the account can actually call; held fixed afterward | ❓ pilot |
| Prerequisite extractor (offline) | A strong model; its extra cost is reported | 🧪 days 15–28 |
| Failure labeling | Hand labels first; a classifier or LLM only after validation against them | 🧪 |
| Grader | tau2's database-state check (no LLM) | ✅ fixed |

## Decision log

| # | Decision | Why |
|---|---|---|
| D1 | Target τ³-Banking (knowledge domain) | Largest headroom (best 55% / 35%); only one custom harness submitted; telecom is saturated; Terminal-Bench runs cost $1.7k–9.6k |
| D2 | One Kubernetes Job per trial | Isolation, resource caps, and the platform skills the target roles ask for |
| D3 | Trial pods have no DB or cluster credentials | Least privilege; untrusted agent code can't touch platform state |
| D4 | pass^k as the headline metric | Reliability is what production needs; Sierra's own emphasis |
| D5 | Match leaderboard setup (gpt-5.2 user sim, alltools) | Comparability |
| D6 | 30/67 dev/test split, test run ≤ 3 times | Prevents tuning on the test set |
| D7 | Failures drive the order of work; papers are read per failure bucket | Avoids implementing ideas that don't address the real bottleneck |
| D8 | Every harness component behind a flag | Clean ablations |
| D9 | Deterministic code for rule checks; learned models only for fuzzy judgments | Rule checks must be exact and auditable |
| D10 | Never use `LLMGTAgent` or ground-truth task fields | Integrity of every reported number |
| D11 | Jev optional, behind a flag, with an LLM fallback | New vendor; signups paused; may change or disappear |
| D12 | Research question narrowed to source-linked action prerequisites vs a strong retrieval baseline | External review: automatic procedure drafting already exists in Decagon and Intercom, and in PCAS, Autoformalization and COVENANT |
| D13 | Primary comparison is paired and internal; leaderboard only via the official protocol | A 67-task holdout score is not comparable to a full-benchmark score |
| D14 | Authorization from evidence records, checked at action time | A plan checked once goes stale; a classifier can't grant permission |
| D15 | Compiler correctness evaluated separately with a hand-written rule test set | Exact execution of a wrong rule is still wrong |
| D16 | Freeze platform expansion; structured logs before the observability stack; no training in scope | Time goes to finding out whether the intervention works |

## Open decisions

| # | Question | Recommendation |
|---|---|---|
| O1 | Agent model | Small pilot on 2–3 models the key can actually call; pick on capability per dollar |
| O2 | Dispatcher concurrency on OpenAI usage tier 1 | Lower from 4 to 1–2 before the first real run |
| O3 | Where trajectories are stored | Postgres JSONB first (tens–hundreds of KB each); move to S3 if it grows |
| O4 | Publish the repo publicly | Decided 2026-09-26: published on GitHub for external review |
| O5 | When to build the Next.js dashboard and EKS deploy | After the cycle-0 baseline, so they show real data |
