# Project status (as of 2026-09-26)

An honest snapshot of what is built, what is verified, and what is not. Reviewers: please check every claim here against the code in this repo. Section 7 lists open questions.

**Authorship.**
- The code and docs were written with an AI coding assistant (Claude Code).
- I made the project decisions: choosing the project, accepting the external re-scope, writing the engineering charter, and stopping the live demo.
- No experiment results exist yet.

---

## 1. Goal and research question

**Benchmark.** Sierra's τ³-bench, `banking_knowledge` domain (tau2-bench v1.0.1, commit b7ea907): 97 tasks and 698 policy/knowledge documents. The agent must retrieve the relevant policies and follow them while serving a simulated customer.

**Research question (narrowed after an external review):**
> Can automatically extracted, source-linked action prerequisites improve a banking agent's reliability over a strong retrieval baseline, without blocking too many valid actions?

**Planned variants (none built yet):**

| Variant | Setup |
|---|---|
| A | Standard tau2 agent |
| B | A + strong retrieval |
| C | B + extracted rules placed in context |
| D | B + rules enforced at action time |
| E | D with human-reviewed rules, labelled separately and never mixed with the "fully automatic" results |

**Evaluation design.**
- **Metric:** pass^k, meaning the chance the agent succeeds on all k tries.
- **Comparisons:** paired comparisons with task-level confidence intervals.
- **Split:** fixed dev/test split of 30/67 tasks, stratified.
- **Pre-registration:** each experiment is written down before it runs.
- Leaderboard comparisons only through the official tau2 protocol.

**Out of scope:** training, distillation, routing, and memory.

**Closest prior work I know of:**
- PCAS (arXiv 2602.16708)
- Autoformalization into Policy-as-Code (2606.26649)
- COVENANT (2607.25400)
- interwhen (2602.11202)
- ContrAgent (2609.18128)

Commercial vendors already generate procedures automatically (Decagon AOP Copilot, Intercom Fin Procedures, Sierra Journeys, Salesforce Agent Script). I do **not** claim novelty over them.

---

## 2. First milestone (from my charter)

> Run a banking task end to end, save a complete structured trace, demonstrate recovery from the identified infrastructure failures, and explain one observed agent failure.

**Status: not reached.** Only the infrastructure-recovery part has progress, and it has been tested only with unit tests, not live on the cluster.

---

## 3. Status summary

Each item below is marked as **IMPLEMENTED**, **VERIFIED** (I have evidence), **NOT DONE**, or **PROPOSAL**.

### Earlier commits
```
4b6e9c0 Re-scope after external review: narrower question, honest comparisons
0b01e42 Architecture doc: layers, decisions made so far, and open decisions
30de037 Weekly arXiv triage script, first digest, Jev as a candidate tool
3182231 Protocol: DAIR.AI Academy as a standing research source, reading map per cycle
974caca Research protocol, experiment log, and fixed banking dev/test split
51fc0a7 Platform skeleton: API, queue, dispatcher, per-trial Kubernetes Jobs
```

### Latest commit: attempts, crash-safe queue, reconciler (12 files modified, 3 new; +410 / −208)

- **IMPLEMENTED: Attempt model.** A trial (one scored slot) can have several attempts (one Kubernetes Job each). Each attempt has its own status, Job name, callback token, cost, and failure reason.
- **IMPLEMENTED: Crash-safe queue.** Redis `BLMOVE` moves each trial id into a processing list, with `ack`, `nack` and `recover`. The previous version used `BLPOP`, which lost an item if the dispatcher crashed between pop and launch.
- **IMPLEMENTED: Reconciler.** It settles attempts whose pod ended without calling back:
  - Deadline exceeded counts as an **agent** timeout: the trial is marked errored and scores 0.
  - A crash, vanished Job, or missing callback counts as an **infra** failure. It is retried up to `max_infra_retries=1`; after that the trial is marked `infra_failed` and excluded from metrics.
- **IMPLEMENTED: Idempotency.** Duplicate queue deliveries are dropped, and a relaunch reuses the same Job name (a 409 from Kubernetes is a no-op). The API rejects late or duplicate callbacks with 409, but still records the cost they report, once.
- **IMPLEMENTED: Concurrency cap.** The dispatcher counts active attempts in the database (`max_concurrency=2`).
- **IMPLEMENTED: Fault-injection stub agents.** `stub-crash-first-attempt` exits with code 137 on attempt 1; `stub-hang` sleeps past its deadline.
- **VERIFIED: 21 of 21 tests pass**, rerun today (`pytest -q` → `21 passed in 0.66s`). Nine of them are failure-injection tests in `tests/test_dispatcher.py`, using a fake queue and a fake Kubernetes launcher (listed in that file).
- **VERIFIED: Rebuilt image deployed** to a local kind cluster via Helm. API, dispatcher, Postgres and Redis are all Running with **0 restarts** (~104 minutes uptime at the time of writing). The dispatcher previously crash-looped on cold start; I fixed that by removing `create_all` from it and retrying `recover()`.
- **NOT DONE: Live failure demo.** `scripts/failure_demo.sh` exists but has never run; I stopped it. It injects six failures on the real cluster: dispatcher restart, worker crash, pod deletion, deadline, duplicate delivery, and replayed callback.

### Not started
- **NOT DONE: Benchmark adapter.**
  - Add tau2 as a pinned dependency.
  - Register an agent factory that runs a real banking task.
  - **Integrity guard:** tau2's `build_agent` passes `task=` (which contains the expected actions) to every agent factory. Our factory must drop it, with a test proving that it does.
  - Never use tau2's `LLMGTAgent`: it is a ground-truth agent.
- **NOT DONE: Structured per-trial event trace** (JSON: messages, tool calls, retrievals, costs, reward breakdown).
- **NOT DONE: Local runner** without Kubernetes, so the core logic can be run and understood without the deployment stack.
- **NOT DONE: Spending guard.** Dollar cap including in-flight requests, and a maximum number of turns. Cost is currently self-reported by the worker.
- **PROPOSAL: Zero-cost end-to-end test.** Use litellm's `mock_response` so the full tau2 path runs without API spend.
- **NOT DONE: Retrieval (B), rule extraction (C/D), hand-written rule test set, human review (E), experiments.**

**Waiting on:**
- An API key, kept in a local `.env` file (never committed).
- An approved dollar cap, set before any paid run.

**Money spent: $0.** Only stub agents have run, with no LLM calls.

---

## 4. Architecture (as implemented)

```
POST /runs ──> Postgres (Run, Trial rows) ──> Redis queue (trial ids)
                                                   │ BLMOVE → processing list
                                                   v
                         Dispatcher: cap check → create Attempt (commit) → create k8s Job → ack
                                     reconcile() every 5s: settle Jobs that ended without a callback
                                                   │
                                                   v
             Trial pod (one per attempt): POST /trials/{id}/start (token) → run agent → POST /result
             non-root, read-only root filesystem, no service-account token, no DB creds,
             backoffLimit 0, activeDeadlineSeconds
```

**Lifecycles:**
- **Trial:** `queued → dispatched → running → completed | errored | infra_failed`
- **Attempt:** `created → launched → running → completed | errored | timed_out | infra_failed`

**Metric rule:**
- `completed` counts with its reward; `errored` counts as reward 0.
- `infra_failed` is excluded from pass^k and reported separately in `status_counts`.
- `spend_usd` sums the cost of every attempt, including superseded ones.

**Stack:** FastAPI, SQLAlchemy 2, Postgres 16, Redis 7, the Kubernetes Python client, Helm, kind.

---

## 5. Directory map

```
~/Desktop/agent-eval-platform/
├── app/            dispatcher.py, queue.py, models.py, main.py, k8s.py, schemas.py, settings.py, metrics.py, db.py
├── worker/         trial.py (pod entrypoint), agents.py (stub agents)
├── tests/          conftest.py, test_dispatcher.py, test_api.py, test_k8s.py, test_metrics.py
├── scripts/        failure_demo.sh, smoke.sh, make_split.py, arxiv_scan.py
├── deploy/helm/agent-eval/   values.yaml + templates
├── docs/           RESEARCH_PROTOCOL.md, ARCHITECTURE.md
├── splits/banking_knowledge.json
├── research/arxiv_digest_2026-09-25.md
└── EXPERIMENTS.md  (E000 baseline: planned, not run)
```

---

## 6. Weaknesses I already suspect (please confirm or refute)

1. **Trials can get stranded, i.e. never dispatched.**
   - `create_run` commits the trials and then pushes them to Redis. `reconcile()` commits `status="queued"` and then pushes.
   - A crash between the commit and the push leaves a `queued` trial that is in neither the Redis queue nor the processing list.
   - The reconciler only scans `launched`/`running` attempts, so nothing ever re-queues it. There's no sweeper for stale `queued` trials.
2. **Pod startup time counts against the deadline.**
   - `activeDeadlineSeconds` includes pod scheduling and image pull time.
   - A slow pull could therefore be misclassified as an **agent** timeout.
3. **Excluding infra failures may bias metrics.**
   - If infra failures correlate with hard tasks (e.g. OOM on long conversations), dropping them inflates pass^k.
   - Also, `run_pass_hat_k` skips tasks with fewer than k scored trials, so one infra failure silently removes that task from pass^k at the highest k.
4. **Cost can go unrecorded.**
   - Cost is self-reported in the result callback.
   - A pod killed mid-conversation spent money that is never recorded, so the future dollar cap can't rely on it alone.
5. **The concurrency cap is check-then-act.** It is safe only with a single dispatcher replica.
6. **Weak security.**
   - No authentication on `POST /runs`.
   - Callback tokens are stored in plaintext in Postgres (the demo script reads them with psql).
   - Local-dev only for now.
7. **Duplicate-delivery test only covers a finished trial.** Test 5 in the demo pushes a duplicate for an already finished trial; a duplicate *during* dispatch is covered only by a unit test.

---

## 7. Open questions

1. Is the attempt/trial split and the agent-vs-infra failure classification sound for **measurement**? Is excluding `infra_failed` from pass^k defensible, or should those trials count as failures, or be reported with bounds?
2. Are there failure modes that the 9 injection tests in `tests/test_dispatcher.py` miss? Is any test weaker than its name claims?
3. Is this infrastructure proportional to a 97-task benchmark at concurrency 2? Or should I freeze Kubernetes work now and build the local runner plus the tau2 adapter?
4. What is the smallest trustworthy path to the milestone: one real banking task, a complete trace, and one agent failure explained?
5. What else must the tau2 integration guard against besides dropping `task=`, to avoid answer leakage or grader exploitation?
6. How should the spending cap be enforced, given that cost is only known after each LLM call and several calls are in flight at once?
7. Is anything in sections 1–3 overclaimed?
