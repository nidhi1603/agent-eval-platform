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
| Writes executed before a verification log (the only violation category the implemented check detects) | 0 | 0 | 0 |
| Valid actions blocked (withheld writes) | 0 | 0 | 0 |
| Checks held per conversation | – | 1.1 (search 19, clock 2, ids 1) | 4.35 (checklist 25, needs 22, search 22, plan 16, ids 2) |
| Cost per conversation, upper bound / cache-aware | $0.128 / $0.047 | $0.114 / $0.049 | $0.162 / $0.060 |
| Latency per conversation | 69 s | 70 s | 90 s |

**Paired comparisons** (per task and attempt):
- **v1 vs baseline:** 1 improved (task_023, attempt 0), 0 regressed, 18 both fail, 1 incomplete.
- **v2 vs baseline:** 0 improved, 0 regressed, 17 both fail, 3 incomplete.
- **v2 vs v1:** 0 improved, 1 regressed, 17 both fail, 2 incomplete.

**Decision rule** (at least 4 more passes of 20 than the baseline, and no more unauthorized writes): **neither harness qualifies.** This does not depend on how the interruptions are treated: even if both interrupted v2 trials had passed, v2 would still be short of +4. So under the plan, neither harness goes forward to an `alltools` pilot.

**Safety, stated precisely:** no writes before a verification log were detected by the implemented check. Other authorization and policy violations have not been comprehensively assessed:
- unsupported amounts;
- the wrong account;
- missing consent;
- ineligible operations;
- verification logged without being performed correctly.

That includes the 27 wrong-argument writes in the harness arms. Those are covered by the failure audit (`research/h002/audit/`).

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
1. **Behaviour changed in the targeted direction.** Transfers fell from 0.65 to 0.05, denials from 0.65 to 0.10–0.20, use of discovered tools rose about 16×, and approximate reference-action progress went from 13% to 31–32%. **Changed behaviour is not the same as fixing giving up.** Some transfers are appropriate: task_092's reference includes one. Suppressing an escalation while leaving the task unfinished is not automatically an improvement.
2. **Retrieval coverage and incomplete execution are plausible explanations, not established causes.** Agents still search fewer than 3 times, and required-document recall stays at 0.35; 78% of reference writes are never attempted. The failure audit tests which failure actually stops each conversation.
3. **Reference-action progress is a diagnostic, not verified task completion.** Arguments are matched approximately and order is ignored. A matched action may still lack consent or come in the wrong order, and a legitimate alternative path may not match at all. Completing the correct overall outcome is the objective, and partial progress can include consequential mistakes. A floor effect (baseline 0/20) is likely, but that the model setting causes it is not established.
4. **v2 vs v1:** +42% cost (upper-bound means), +22% (cache-aware means), +29% latency, with no measurable benefit. *(Corrected: an earlier draft said "+27%", which was v2 vs the **baseline**, labelled as vs v1.)* Dropping v2 from the next paid comparison is a scope decision based on its overhead. It does not show that every v2 component is ineffective.

## Plan deviations found at analysis
- **task_041, harness_v2, attempt 0:** interrupted after the model spent the full 4,096-token output cap on reasoning and returned an empty message. tau2's message validation rejects that, and `bench/trace.py` labels any unrecognised error "harness". The actual cause is the output-token cap, a setting shared by all arms. The outcome is kept (interrupted); the label is corrected here.
- **Worker count:** 3, then 2 after the rate-limit interruptions (see the deviations file).

## What this does and does not show
- **Shows:** on these 10 dev tasks, at this model setting, neither harness raised the official pass rate. Both changed behaviour in the targeted direction without unsafe writes.
- **Does not show:** that the harness cannot help. The floor effect and the retrieval bottleneck leave open whether it helps a stronger reasoning setting, or together with better retrieval.

## Failure audit (added 2026-09-30; `research/h002/audit/SUMMARY.md`)

60 conversations, labelled partly blind by three independent labellers with a fixed codebook.

- **Most common first failure:** a requirement only in an unretrieved document (24/60). One document, the account-lookup tool's `_009`, is missing in 16.
- **Which fix would plausibly help:** retrieval 41/60, argument grounding 20/60, a completion check 14/60.
- **The harness shifts failures later.** Missed steps in retrieved documents fall (9 → 3–4). Wrong arguments or policy readings rise (3 → 6), and **unsafe writes rise (1 → 4 in v1)**: verified writes that break other policies (consent, amount entitlement, eligibility). This is a safety cost the verification check could not see.
- **False completion claims** occur in every arm. A held transfer followed by a false "transferred" claim is a plausible harness side effect, not yet established.
