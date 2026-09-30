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
- **Candidate interventions the labellers identified:** retrieval in 41/60, argument grounding in 20/60, a completion check in 14/60. These "would help" judgements agree only 12/15 on re-labelling, so treat them as soft. Primary categories agree 13/15 (κ = 0.83). Both disagreements are C2 vs C3, missing evidence vs failure to use available evidence: exactly the distinction that guides the next intervention, so they are kept, not merged away.
- **Observed, not established as caused:** missed steps in retrieved documents fall (9 → 3–4), and wrong arguments or policy readings rise (3 → 6).
- **Unsafe writes, adjudicated:** conversations with at least one violation: baseline 1, v1 3, v2 1. Violating actions: baseline 8, v1 3, v2 1 (plus 1 ambiguous in v1). This corrects the earlier flag-based "1 → 4". **No reliable safety comparison is established:** only flagged conversations were adjudicated, and absence of evidence is not equivalence. The baseline's 8 violating actions are one conversation: a serious failure example, not eight independent observations that eligibility is the dominant problem.
- **False completion claims** occur in every arm. **All 9 harness conversations with a false "transferred" claim (no transfer call) came after the harness had held a transfer; the baseline has 1 such conversation.** A strong association and a plausible side effect of holding transfers, but not a controlled result.
- **Offline tool-document retrieval probe:**
  - queries from customer words do not help;
  - dependency search alone reached 19% recall of needed tool documents; added to the agent's own searches, combined recall went from 39% to 52%. It supplements existing retrieval, and does not show the agent would use the extra evidence correctly;
  - the account-lookup document is still missed;
  - this shows availability only.

  See the audit summary.

## Decision after review (2026-09-30)
H002 review closed. Next steps, in order:
1. **H003 calibration**, once Nidhi authorizes its $3.00 cap.
2. **If calibration warrants a comparison: dependency-following tool search as the first isolated intervention.**
   - Arms: the selected configuration, with vs without dependency search. Model, simulator, limits and the rest of the harness identical.
   - Inputs: only tool schemas and documents legitimately available at the intervention point.
   - Outcomes: complete-task success, relevant-document retrieval, incorrect actions, added tokens, latency.
   - The account-lookup miss is kept as a known limitation, with no document-specific exception.
   - Not bundled with a completion checker or an eligibility guard.
3. **Transfer-claim check (later, separately):** it must require evidence of a *successful* transfer, not merely a transfer call. A rejected, blocked or failed call cannot support "I transferred you". The correction should help the agent state the actual status and the permitted next step.

v1 stays as a comparator; v2 stays frozen.

## Correction (2026-09-30, found during the H004 review): "reference writes" included lookups

- **The miscount:** research/h002/analyze.py counted every `call_discoverable_agent_tool` reference action as a "reference write". That includes lookups made through the wrapper (read tools): per attempt set, 45 true writes and 29 lookups.
- **What it affects:** the row "Reference writes completed (share)" and the "What went wrong with the reference writes" table (296 = 148 reference discoverable calls × 2 harness arms, 78% never called). Both are over **discoverable-tool calls, reads and writes**, not writes alone.
- **True writes matched** (`research/h004/relabel_progress.json`, same matching rules):

  | | True writes | Lookups |
  |---|---|---|
  | baseline | 6/90 = 0.07 | 0/58 |
  | v1 | 2/90 = 0.02 | 13/58 |
  | v2 | 4/90 = 0.04 | 10/58 |

- **The consequence:** the harness arms' higher discoverable-call progress came from **lookups**. On true writes, the baseline matched slightly more than either harness arm. All of these counts are small.
