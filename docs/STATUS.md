# Project status (updated 2026-09-26, evening)

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
| D | C plus action-time enforcement of the same rules (only difference from C) |
| E | D with human-reviewed rules, labelled separately and never mixed with the "fully automatic" results |

**Evaluation design.**
- **Metric:** pass^k, meaning the chance the agent succeeds on all k tries.
- **Comparisons:** paired comparisons with task-level confidence intervals. *Planned, not implemented:* only pass^k point estimates exist (`app/metrics.py`).
- **Split:** fixed dev/test split of 30/67 tasks, stratified.
- **Pre-registration:** each experiment is written down before it runs.
- Leaderboard comparisons only through the official tau2 protocol (all 97 tasks, 4 trials). A dev, holdout or single-task score is never presented as a leaderboard reproduction.
- **Spend** is reported two ways: what tau2 reports (litellm price map, agent + user only, 0.0 for unknown models) and our ledger's figures: a usage-based estimate, unresolved reservations (failed calls or missing usage), and their sum as an upper bound. Provider-reconciled charges are not available to the code.

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

**Status: not reached.**
- Local path (no Kubernetes): **built and verified with scripted responses only.** A real banking dev task runs through tau2's orchestrator and official grader; traces are complete. No live model has been called: blocked on an API key and an approved budget.
- Platform recovery: unit-tested, with **9 reproduced defects** (`docs/DEFECTS.md`). Not verified live on the cluster. The cluster is not used for scored experiments until the defects are fixed.
- Explaining an observed agent failure: requires the first live run.

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

### Local runner (`bench/`, uncommitted at time of writing)

Decisions and sources: `docs/BENCHMARK_INTEGRATION.md`.

- **IMPLEMENTED + TESTED: tau2 pinned** (v1.0.1 @ b7ea907) as the `bench` extra. Every run verifies the installed package, the data checkout commit, that it is unmodified, that tau2 actually reads that data directory, and the hash of the task files that run.
- **IMPLEMENTED + TESTED: agent input allowlist.** The factory accepts `tools`, `domain_policy`, `llm`, `llm_args` and records what it withheld (`task`, audio options). The integrity gate: the task was withheld, and the policy and tool schemas are byte-identical to those built with the answer key emptied. Also recorded: a bounded (depth-4) search finds no Task object in the agent (it does not inspect closures), and a string scan (diagnostic, with positive controls) whose overlaps are reported for review. Test-split tasks and `golden_retrieval` are refused.
- **IMPLEMENTED + TESTED: estimated spend admission control** (`bench/budget.py`), not a guarantee. Agent, user simulator, LLM grader and embeddings each reserve a conservative bound (request bytes, which bounds byte-level BPE tokens, plus forced `max_tokens`) before sending; in-flight reservations count in decisions and totals; litellm and OpenAI SDK retries are disabled and ours are reserved per physical request; failed calls and calls with missing or malformed usage keep their reservation; caps, prices and limits are validated as finite; only a small set of model arguments is accepted; usage above the bounds stops the run. Relies on the recorded prices being right (the code checks their form, not their truth) and on the provider honouring `max_tokens`.
- **IMPLEMENTED + TESTED: structured trace** per run: provenance, pins, config, seed, agent-input audit, every message, tool calls paired with results, retrievals with returned document ids, termination reason, the official evaluator's breakdown, models observed, both spend figures and the per-call ledger. Each run gets a unique directory. `manifest.json` and an fsync'd `ledger.jsonl` (reserve before each request, settle after) are written before any network call, so a killed process still leaves both. The final trace is written in a guarded step (`trace_error.json` if that fails). Separate fields: `execution.finished`, `trace_complete` (`missing_fields` empty), `research_eligibility`, and `attribution` (cause + evidence), kept apart from the official `evaluation` and `termination_reason`. Provenance adds file hashes (bench code, prices, uv.lock, split, fixture) and saves `repo.diff` when the tree is dirty.
- **IMPLEMENTED + TESTED: failure attribution**, with the failing caller's role for exceptions. `too_many_errors` is attributed by who made the erroring calls; `timeout` and `max_steps` are `unattributed` (need trace review); unknown states are `unclassified`, never silently an agent failure.
- **VERIFIED (MOCK ONLY): zero-cost path.** Scripted responses on dev task_015: the reference conversation scores 1.0 and a refusal scores 0.0 through the official grader. These are harness tests, not benchmark results.
- **VERIFIED (MOCK ONLY): side-channel detection.** A scripted task_085 conversation that calls the leaky listing tool is flagged at exactly that call; the task_015 reference is not flagged.
- **NOT DONE: live smoke test.** No API key in `.env` and no approved budget. It will use `bm25` (labelled non-official); `alltools` needs the `srt` sandbox and `ripgrep`. One predetermined task is an integration smoke test, not a baseline estimate.

**Findings from the benchmark research:**
- The split's `tasks.json` hash was computed from a stale aggregate file: tau2 loads `tasks/task_*.json`, which differ on 13 tasks (3 dev). Membership unchanged; the runtime hash is now recorded and checked.
- The benchmark has a small side channel (reproduced): `list_discoverable_agent_tools` reveals whether a discoverable read is in the reference trajectory. Still exposed in unchanged runs, so it cannot be declared unused: each trajectory is checked by differential replay and flagged if exposed (kept, claims limited). Upstream issue drafted, not filed.
- tau2's own reported cost is 0.0 for models litellm cannot price and omits embeddings, the grader and failed calls.

### Not started
- Live baseline run and failure explanation (blocked, above).
- Fixes for the 9 platform defects (`docs/DEFECTS.md`); live failure demo.
- Paired bootstrap / task-level CIs.
- Retrieval (B), rule extraction (C/D), hand-written rule test set, human review (E).

**Money spent: $0.** Only stub agents and scripted responses have run.

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
├── bench/          local runner: run.py, agent.py, budget.py, trace.py, scripted.py, pins.py, prices.json, scripts/
├── app/            dispatcher.py, queue.py, models.py, main.py, k8s.py, schemas.py, settings.py, metrics.py, db.py
├── worker/         trial.py (pod entrypoint), agents.py (stub agents)
├── tests/          conftest.py, test_dispatcher.py, test_api.py, test_k8s.py, test_metrics.py, test_bench.py, test_known_defects.py
├── scripts/        failure_demo.sh, smoke.sh, make_split.py, arxiv_scan.py
├── deploy/helm/agent-eval/   values.yaml + templates
├── docs/           RESEARCH_PROTOCOL.md, ARCHITECTURE.md, BENCHMARK_INTEGRATION.md, DEFECTS.md
├── splits/banking_knowledge.json
├── research/arxiv_digest_2026-09-25.md
└── EXPERIMENTS.md  (E000 baseline: planned, not run)
```

---

## 6. Weaknesses suspected before the review

Items 1 and 5 are now reproduced as defects 2 and 8 in `docs/DEFECTS.md`; item 4 is addressed for the local path by the budget ledger.

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
