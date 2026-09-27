# Experiment log

Every experiment gets an entry **before** it runs (hypothesis and prediction) and is completed after.
Rules: [docs/RESEARCH_PROTOCOL.md](docs/RESEARCH_PROTOCOL.md). Failed ideas stay in the log.

## Template

```
### E### — <short name>
- Date / git SHA:
- Cycle / target failure bucket:
- Hypothesis:
- Prediction (written before running):
- Change (config flag):
- Setup: split=dev, k=4, agent model=, user sim=gpt-5.2
- Result: Δpass^1 = __ [95% CI __, __], Δpass^4 = __, Δcost/task = $__
- Failure buckets before → after:
- Decision: keep / revise / kill — why
- Reading that informed it:
```

---

### S001: integration smoke test (planned; not an experiment)
- Task: dev task_015, chosen by a rule fixed in advance (easiest DB-graded dev task, lowest id).
- Setup: 1 trial, retrieval=bm25 (non-official, labelled), user sim=gpt-5.2 with reasoning_effort=low, seed 300.
- Purpose: check credentials, request compatibility, logging, grading and spend accounting. Not a baseline estimate.
- Kept regardless of outcome; not retried until it passes.
- Run 2026-09-27 01:16 UTC, run_id 20260927T011640Z_task_015_live_da8b4495 (evidence: results/S001_task_015/).
  Agent gpt-5-mini-2025-08-07 (reasoning_effort low); user sim gpt-5.2-2025-12-11 (reasoning_effort low); bm25; seed 300.
- Result: official reward 0.0 (DB mismatch), termination user_stop, 10 messages, 6 model calls.
  Spend: full-price usage estimate $0.0189 (conservative; no unresolved reservations). Cache-aware estimate $0.0122 =
  tau2-reported, confirmed call by call from provider-reported cached tokens (agent 8,576, user 3,072); provider dashboard
  not yet reconciled. The user simulator is ~74% of the full-price estimate. The implemented checks detected no prohibited
  answer leakage;
  differential replay conclusive, no answer-dependent outputs; flag: non-official retrieval config (bm25).
- First consequential error (read from the trace; simulator followed its instructions): at message 4 the agent gave the
  customer the get_referral_link tool for the Crypto-Cash Back Card without evidence that card has a referral program.
  Its one search returned EcoCard and other cards' referral documents. A keyword search of all 698 documents found no
  Crypto-Cash Back referral document: that supports "could not verify this offer", not proof that no applicable policy exists.
  The agent also pre-filled card_name="Crypto-Cash Back Card", so it selected the wrong product itself. The customer used the tool for the wrong card, so the final database has a Crypto-Cash Back referral instead of
  the Platinum Rewards one. Failure label: TRUST (acted on an unverified customer claim), with READ as a contributor
  (the agent restated terms from the EcoCard document as if they applied).
- Harness verdict: integration path works end to end with real models. One trajectory; says nothing about how often this happens.
- Lesson: a satisfied customer, a successful tool call and a correct business outcome are three different measurements;
  here the first two were positive and the third failed.
- Working hypothesis (to be tested only after S002): before enabling an action, establish that authoritative evidence
  supports that action for the specific product and applicable conditions; correct mistaken customer claims separately
  (a customer can quote wrong terms and still qualify). Any rule-based intervention must be compared against a simple
  instruction requiring product-specific evidence, and false blocks must be measured.

### S002: exploratory six-task dev sample (planned)
- Plan fixed before running: experiments/S002_plan.json (selection rule: dev minus task_015, sorted by sha256("S002:"+id),
  first 6 -> task_069, task_080, task_035, task_089, task_029, task_047). Same settings as S001; one attempt each; no retries.
- One shared allocation for the batch (bench/batch.py). Tasks that cannot be admitted are recorded, not dropped.
- Per task: official reward, first consequential error with trace excerpt, cost, and whether the cause is uncertain.
- Status: awaiting approval of the batch allocation.

### E000 — Default-agent baseline (planned)
- Cycle / target: 0 — establish the reference point
- Hypothesis: the default tau2 agent's dev-split behaviour is a usable reference point for later paired comparisons.
- Note: a dev-split score is not a leaderboard reproduction (30 of 97 tasks). A leaderboard value for the same model is context for spotting gross harness errors only, never a pass/fail criterion.
- Setup: split=dev, k=4, retrieval=alltools, user sim=gpt-5.2
- Status: blocked on model API keys (agent model + OpenAI for the user simulator).

### F001: answer-dependent listing audit (feasibility study, 2026-09-27, $0)
- Question: can controlled differential replay detect hidden-answer dependencies in agent tool environments,
  with reproducible evidence and a measured false-positive rate? (The answer gives negative controls within coverage, not a general rate.)
- Result (dev split, bm25, no model calls, reference-constructed probes): one shared mechanism (`list_discoverable_agent_tools` prints an
  evaluation log filtered by the reference actions) exposes answer information in 17/30 tasks (145 of 442
  agent-visible reference-probe outputs); the flagged set equals the code-predicted set (a mechanism consistency check, not independent
  validation). With the local fix: 0 flags on 532 agent-visible probe outputs (569 calls executed). Grading logic is
  unchanged; hashes, schemas and grades matched on the tested scripted trajectories only. Exposure only; exploitation and score inflation
  not tested. Report: docs/findings/2026-09-27-answer-dependent-listing.md.
