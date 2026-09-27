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
  Spend: usage-based estimate $0.0189 (no unresolved reservations); tau2-reported $0.0122. Integrity checks passed;
  differential replay conclusive, no answer-dependent outputs; flag: non-official retrieval config (bm25).
- First consequential error (read from the trace; simulator followed its instructions): at message 4 the agent gave the
  customer the get_referral_link tool for the Crypto-Cash Back Card without evidence that card has a referral program.
  Its one search returned EcoCard and other cards' referral documents; no document describes a Crypto-Cash Back referral
  program. The customer used the tool for the wrong card, so the final database has a Crypto-Cash Back referral instead of
  the Platinum Rewards one. Failure label: TRUST (acted on an unverified customer claim), with READ as a contributor
  (the agent restated terms from the EcoCard document as if they applied).
- Harness verdict: integration path works end to end with real models. One trajectory; says nothing about how often this happens.

### E000 — Default-agent baseline (planned)
- Cycle / target: 0 — establish the reference point
- Hypothesis: the default tau2 agent's dev-split behaviour is a usable reference point for later paired comparisons.
- Note: a dev-split score is not a leaderboard reproduction (30 of 97 tasks). A leaderboard value for the same model is context for spotting gross harness errors only, never a pass/fail criterion.
- Setup: split=dev, k=4, retrieval=alltools, user sim=gpt-5.2
- Status: blocked on model API keys (agent model + OpenAI for the user simulator).
