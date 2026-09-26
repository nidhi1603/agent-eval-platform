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

### E000 — Default-agent baseline (planned)
- Cycle / target: 0 — establish the reference point
- Hypothesis: the default tau2 agent's dev-split behaviour is a usable reference point for later paired comparisons.
- Note: a dev-split score is not a leaderboard reproduction (30 of 97 tasks). A leaderboard value for the same model is context for spotting gross harness errors only, never a pass/fail criterion.
- Setup: split=dev, k=4, retrieval=alltools, user sim=gpt-5.2
- Status: blocked on model API keys (agent model + OpenAI for the user simulator).
