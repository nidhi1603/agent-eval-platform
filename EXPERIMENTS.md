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

### S002: exploratory baseline batch (run 2026-09-27, $1 approved)
- 6 pre-registered dev tasks, 1 trial each; gpt-5-mini agent, gpt-5.2 user simulator; bm25, unchanged tau2 v1.0.1.
- **Outcome:** 6/6 finished, **0/6 rewarded**. Exposure `not_observed` in all 6: the check was conclusive and the listing tool was never called.
- **Spend:** $0.601 full-price estimate ($0.283 cache-aware), within the $1 allocation. Per rollout, mean $0.100 full price. The user simulator is about 51% of cost.
- **First consequential errors,** labelled by reading traces (`experiments/S002_labels.md`):
  - The most common observed pattern is a negative conclusion without an adequate search ("not documented", "no tool", "can't do that here"): 5/6 traces, and the first error in 3/6.
  - Discoverable agent tools were not unlocked when needed in 3/6.
  - First-error categories are mixed; n = 6, so these are counts, not rates.

### S003: paired instruction comparison (planned; not run)
- **Question:** does one frozen instruction (`bench/variants/denial_check_v1.md`) reduce unsupported denials, and does official success change?
  - Scope: exploratory, 6 tasks × 2 arms × 1 attempt.
- **Tasks:** `task_031`, `task_019`, `task_094`, `task_095`, `task_066`, `task_087`. Chosen by sha256 from the dev tasks that were unused for S002 analysis and prompt design. F001 probed all dev tasks, so these are not "unseen".
- **Order:** balanced, pre-specified, with each task's two arms run back to back.
- **Settings:** identical to S002; the benchmark is unchanged.
- **Measures:**
  - Primary: official reward per pair.
  - Secondary: unsupported denials, harms (unnecessary actions, delayed transfers) and cost, labelled from a blinded export.
- **Forecast:** about $1.20. Allocation awaiting approval (recommended $1.50). Full plan: `experiments/S003_plan.json`.
- **S003 result (run 2026-09-27):**
  - All 12 finished; spend $1.118 full-price estimate. **0 improved, 0 regressed, 6 both fail.**
  - Unsupported denials: 4/6 baseline vs 2/6 variant (2 pairs lower, 0 higher; anecdotal at n = 6). One harm in each arm; the variant's was an unauthorized write.
  - The variant cost +45% (full price). Post-hoc: denials contradicting just-retrieved tool documents suggest the discoverable-tool mechanism, not search, is the bottleneck.
  - Details: `experiments/S003_findings.md`.
- **S003 decision:** `denial_check_v1` is retired as a candidate default. There was no observed success improvement, and cost rose (+45% full price, +24% cache-aware). The secondary metric measures search compliance, not denial correctness.

### T001: offline tool-discovery check (2026-09-27, $0)
- **Usage:** across 19 live traces, the agent unlocked a discoverable tool in only 2, even though tool names appeared in results it received in 16. It made no failed attempts.
- **Replay:** from the exact saved states where it said it could not act (S003 task_095 msg 26; S002 task_080 msg 22), the documented unlock-and-call sequence **works**. Unlocking returns the parameters, and the calls return accounts and cards and freeze the card.
- **Authorization:** writes execute with no identity verification. Authorization is enforced by the written policy only, not the interface.
- **Conclusion:** not a broken integration; the model did not use a working interface. Details: `experiments/T001_tool_discovery_check.md`. Test: `tests/test_tool_discovery.py`.

### G001: rewards-write permission check (2026-09-27, $0)
- **The rule:** `update_transaction_rewards_3847` requires an approved cash back dispute for that transaction, read from the environment's own records (policy doc `_004`).
- **Placement:** at the agent's proposal step, because tau2 grades by replaying recorded writes; a check at execution time would break grading.
- **Verified:**
  - it blocks the S003 unauthorized write from its saved state;
  - it allows the legitimate task_028 write after auto-approved disputes;
  - a full scripted conversation keeps blocked calls out of the trajectory and grading still completes.
- Details: `experiments/G001_rewards_guard.md`.

### D001: tool-discovery diagnostic pilot (planned; not run; revised per review before any run)
- **Design:** agent-only continuations from 4 saved failure points:
  - P1: permitted; success = correct tool, correct user_id, succeeded;
  - P2: permitted; lookup progress is reported separately from freeze completion (k/3);
  - M1: prerequisite missing; forbidden write proposed/executed, and valid next step;
  - A1: unavailable capability plus missing information, read.
- **Four instruction packages (2x2), v2 files:** none / interface description / validated worked example / both.
  - v2 corrects B's "genuinely unavailable" conclusion and the error-handling sentence.
  - v1 was never run.
  - Each package mixes interface information with behavioural guidance, so differences are attributed to packages, not to interface knowledge alone.
- **Size:** 16 runs, 1 sample, Latin-square order. The G001 guard is off in all arms.
- **Stopping rule:** if nothing improves, read the traces before buying repetitions; confirmation needs new contexts and a new approval.
- **Forecast:** about $0.30 full price. Allocation awaiting approval ($0.50).
- Plan: `experiments/D001_plan.json`.
