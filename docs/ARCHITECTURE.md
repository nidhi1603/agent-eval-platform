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

## Layer 3 — The harness 🧪 (each piece added by an experiment, behind a flag)

```
  OFFLINE (once per knowledge-base version)        RUNTIME (every conversation turn)
  ┌────────────────────────────────────┐          ┌──────────────────────────────────────────┐
  │ Policy compiler  (strong model)     │          │ Conversation LLM (agent model)            │
  │ 698 docs → rules + dependencies     │─rules──► │  ├─ document search & reading (cycle 1)  │
  │ (versioned artifact, reviewed)      │          │  ├─ task-state object       (cycle 5)    │
  └────────────────────────────────────┘          │  ├─ plan → PLAN VERIFIER (code) (cycle 3)│
                                                   │  ├─ TRUST GATE before writes (cycle 4)   │
                                                   │  └─ ROUTER: cheap ↔ strong  (cycle 6)    │
                                                   └──────────────────────────────────────────┘
```

| Component | Cycle | Decided approach | Candidate tech |
|---|---|---|---|
| Document search and reading | 1 | Start from the benchmark's best retrieval; fix "searched but not read" | terminal-style grep/cat (Sierra: best in 5/6 configs) |
| **Policy compiler** (the differentiator) | 2 | Documents → structured rules and dependencies, compiled **offline once**, stored as a reviewed, versioned artifact | Strong model (GPT-6 Sol); ideas from interwhen, ContrAgent |
| Plan verifier | 3 | Agent drafts its action sequence; **deterministic code** checks it against the rules before execution | Plain Python over the rule graph (no LLM) |
| Trust gate | 4 | Customer claims must be confirmed by a tool before any account-changing action | Jev (calibrated yes/no) or a cheap LLM, validated vs hand labels |
| Task state | 5 | Explicit state object instead of re-reading the full history | SKILL.state / Belief-State Engine ideas |
| Router | 6 | Cheap model by default, escalate hard steps to a strong model | Jev or LangChain router middleware |

Each component is switchable, so the final ablation table (component on/off → Δpass^k, Δcost) comes for free.

## Layer 4 — Observability 🔜

- **Traces:** OpenTelemetry spans for every model call, tool call, verifier decision and grade, using the GenAI semantic conventions. One trace per trial, with context carried through the Redis message into the pod.
- **Metrics:** Prometheus; pass rate, pass^k, cost per resolved task, tokens, cache hit rate, p50/p95 turn latency, tool errors, queue depth. Low-cardinality labels only (model, variant, domain); per-trial IDs live in traces.
- **Logs:** structured JSON with `trace_id`.
- **Backends:** OTel Collector → Tempo, Prometheus, Loki → Grafana (all via Helm).
- **Use in research:** failure labels are attached to traces, so "which failures did this change fix?" is a query.

## Layer 5 — Research workflow ✅

- `docs/RESEARCH_PROTOCOL.md`: goals, fixed setup, integrity rules, the cycle loop, failure taxonomy, statistics, reading map.
- `splits/banking_knowledge.json`: 30 dev / 67 test tasks, difficulty-stratified, fingerprinted to the task file.
- `EXPERIMENTS.md`: every experiment pre-registered and logged, including failures.
- Sources: Agent Canon → DAIR.AI Academy → weekly arXiv triage (`scripts/arxiv_scan.py`).

## Model roles

| Role | Model | Status |
|---|---|---|
| Simulated customer | gpt-5.2 | Fixed (leaderboard standard) |
| Agent (conversation) | **GPT-6 Luna** recommended; held fixed across harness experiments | ❓ confirm |
| Policy compiler (offline) | GPT-6 Sol (strong, one-time cost) | 🧪 cycle 2 |
| Failure labeling / trust gate | Classical classifier → Jev → cheap LLM, first to pass validation | 🧪 |
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

## Open decisions

| # | Question | Recommendation |
|---|---|---|
| O1 | Agent model | GPT-6 Luna: fits the budget and makes the "cheaper model" claim strongest |
| O2 | Dispatcher concurrency on OpenAI usage tier 1 | Lower from 4 to 1–2 before the first real run |
| O3 | Where trajectories are stored | Postgres JSONB first (tens–hundreds of KB each); move to S3 if it grows |
| O4 | Publish the repo publicly | Needed for the resume link; awaiting approval |
| O5 | When to build the Next.js dashboard and EKS deploy | After the cycle-0 baseline, so they show real data |
