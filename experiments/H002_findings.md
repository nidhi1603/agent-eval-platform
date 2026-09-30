# H002 findings: baseline vs harness v1 vs harness v2 (BM25 pilot, 2026-09-30)

**Run:**
- 60 scheduled full conversations: 57 finished, 3 interrupted.
- Spend: $9.49 conservative upper bound (cap $12.00), including $1.40 for three conversations stopped by the operator and rerun.
- Settings: gpt-5-mini low reasoning; GPT-5.2 low customer; bm25; seed 300; 10 dev tasks × 2 attempts.
- Deviations: `experiments/H002_deviations.md`.

## Pre-registered outcomes

| | Baseline | v1 | v2 |
|---|---|---|---|
| **Passes (official reward 1.0)** | **0/20** | **1/20** | **0/20** |
| Interrupted | 1 (429) | 0 | 2 (one 429; one output-token cap, see below) |
| Unauthorized writes (executed before verification) | 0 | 0 | 0 |
| Valid actions blocked (withheld writes) | 0 | 0 | 0 |
| Checks held per conversation | – | 1.1 (search 19, clock 2, ids 1) | 4.35 (checklist 25, needs 22, search 22, plan 16, ids 2) |
| Cost per conversation, upper bound / cache-aware | $0.128 / $0.047 | $0.114 / $0.049 | $0.162 / $0.060 |
| Latency per conversation | 69 s | 70 s | 90 s |

**Paired comparisons** (per task and attempt):
- **v1 vs baseline:** 1 improved (task_023, attempt 0), 0 regressed, 18 both fail, 1 incomplete.
- **v2 vs baseline:** 0 improved, 0 regressed, 17 both fail, 3 incomplete.
- **v2 vs v1:** 0 improved, 1 regressed, 17 both fail, 2 incomplete.

**Decision rule** (at least 4 more passes of 20 than the baseline, and no more unauthorized writes): **neither harness qualifies.** So under the plan, the harnesses do not go forward to an `alltools` pilot. We inspect and revise.

## Exploratory diagnostics (not pre-registered; `research/h002/analyze.py`, `diagnostics.json`)

Reference actions are read only to measure progress on these dev tasks. The matching is approximate: arguments are compared as normalised strings, and order is ignored.

| Per conversation | Baseline | v1 | v2 |
|---|---|---|---|
| Reference actions completed (share) | **0.13** | **0.31** | **0.32** |
| Reference writes completed (share) | 0.04 | 0.10 | 0.09 |
| Distinct discovered tools used | 0.05 | 0.80 | 0.70 |
| Transfers to a human | 0.65 | 0.25 | 0.05 |
| Capability denials ("I can't…") | 0.65 | 0.10 | 0.20 |
| Knowledge-base searches | 2.65 | 2.90 | 2.75 |
| Required-document recall | 0.33 | 0.35 | 0.36 |
| Verification logged | 1.00 | 0.90 | 0.90 |

**What went wrong with the reference writes in the harness arms** (296 in total):

| Outcome | Count | Share |
|---|---|---|
| Never called | 230 | 78% |
| Correct | 29 | 10% |
| Wrong arguments | 27 | 9% |
| Tool error | 10 | 3% |

**Reading:**
1. **The harness fixed what it targeted.** Transfers fell from 0.65 to 0.05, denials from 0.65 to 0.10–0.20, use of discovered tools rose about 16×, and progress through the reference solution more than doubled (13% to 31–32%), with no unauthorized writes.
2. **It did not fix retrieval.** Agents still search fewer than 3 times, and recall of the required documents stays at 0.35. The give-up check fires only when the agent gives up, but most harness-arm conversations now **end believing they are done**. They carry out part of the task and never find the documents that say what else is required (78% of reference writes never attempted).
3. **The database-exact grade converts partial progress into zero.** A floor effect: with the baseline at 0/20, gpt-5-mini at low reasoning with BM25 is far below the level where these improvements turn into passes.
4. **v2 added cost (+27% upper bound, +29% latency) and no measurable benefit over v1.** It showed the same progress, same recall, and one more interrupted conversation.

## Plan deviations found at analysis
- **task_041, harness_v2, attempt 0:** interrupted after the model spent the full 4,096-token output cap on reasoning and returned an empty message. tau2's message validation rejects that, and `bench/trace.py` labels any unrecognised error "harness". The actual cause is the output-token cap, a setting shared by all arms. The outcome is kept (interrupted); the label is corrected here.
- **Worker count:** 3, then 2 after the rate-limit interruptions (see the deviations file).

## What this does and does not show
- **Shows:** on these 10 dev tasks, at this model setting, neither harness raised the official pass rate. Both changed behaviour in the targeted direction without unsafe writes.
- **Does not show:** that the harness cannot help. The floor effect and the retrieval bottleneck leave open whether it helps a stronger reasoning setting, or together with better retrieval.
