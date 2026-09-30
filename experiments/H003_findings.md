# H003 findings: calibration of the medium-reasoning baseline (BM25, 2026-09-30)

**Run:**
- 5 scheduled full conversations, all 5 finished; none interrupted, none stopped by the operator, no rate-limit rejections.
- Spend: **$0.83** conservative upper bound ($0.37 cache-aware), cap $3.00. The forecast was $1.00–1.60.
- Settings: gpt-5-mini at **medium** reasoning with a **16,384**-token output allowance; GPT-5.2 low customer; bm25; seed 300; 1 attempt per task.
- Plan: `experiments/H003_plan.json`. Analysis: `research/h003/analyze.py`, which imports H002's committed matching rules unchanged. Per-conversation data: `research/h003/diagnostics.json`.
- No deviations from the plan.

## Primary outcome

| Task | Reward | Reference actions matched | Reference writes matched | Transfers | Largest agent output (tokens) | Cost (upper bound / cache-aware) | Latency |
|---|---|---|---|---|---|---|---|
| task_069 | 0 | 1/7 | 0/3 | 0 | 5,423 | $0.132 / $0.072 | 180 s |
| task_058 | 0 | 0/4 | 0/1 | 1 | 4,749 | $0.310 / $0.109 | 212 s |
| **task_023** | **1.0** | 2/2 | – (none) | 1 | 5,024 | $0.199 / $0.091 | 202 s |
| task_089 | 0 | 0/13 | 0/8 | 1 | 1,902 | $0.054 / $0.028 | 61 s |
| task_077 | 0 | 4/25 | 1/14 | 1 | 1,740 | $0.134 / $0.064 | 129 s |
| **Total** | **1/5** | | **1/26** | 4 | | **$0.83 / $0.37** | |

## Go rule, checked condition by condition

**(a) No turn hits the output cap, and no conversation is interrupted by it: met.**
- The largest single agent output was 5,423 of 16,384 tokens.
- But **4 of 82 agent calls, in 3 of 5 conversations, exceeded H002's old 4,096 cap.** One of them is in the passing conversation. So at medium reasoning the larger allowance is necessary: under H002's limit those turns would have been cut off.

**(b) Meaningfully more workflow progress than the H002 low baseline on the same tasks (reference-write progress above 0.10, or at least one pass): met, through the pass condition only.**
- **Pass:** task_023. No H002 baseline conversation on these 5 tasks passed (0/10).
- **Reference-write progress: 1/26 (per-task mean 0.02). It did not clear 0.10.** H002's low baseline was 0/26 per attempt.

**Verdict: GO under the rule as written.** It is a narrow go:
- it rests on one pass on the task with the fewest reference actions (2, and no agent writes);
- write progress is essentially unchanged.

## What the pass is, and is not

- **task_023 is a reasoning task, not a write task.** The customer asks whether their Platinum Rewards spending qualifies for the annual-fee rebate. The simulated customer is scripted to apply for the Diamond Elite Card if told "yes", or for the Silver Rewards Card if told "no". The agent verified the customer, pulled a year of transactions, applied the monthly $7,500 threshold, and answered correctly. The customer then applied for the right card with their own tool.
- The turn that did this computation produced 5,024 output tokens, so it would not have fit H002's 4,096 cap.
- **It is not unique to medium reasoning:** in H002, harness v1 at low reasoning also passed task_023 (attempt 0). The low baseline failed it twice.
- One pass on 5 tasks estimates nothing about general performance, and the plan says so. Two settings changed together, so the pass cannot be attributed to either one.

## Compared with H002's low-reasoning baseline on the same 5 tasks (10 conversations)

| | H002 low baseline (10) | H003 medium baseline (5) | Ratio |
|---|---|---|---|
| Passes | 0/10 | 1/5 | – |
| Reference progress (per-task mean) | 0.23 | 0.26 (almost all of it from task_023's 2/2) | – |
| Reference writes matched | 0/52 | 1/26 | – |
| Required-document recall | 0.28 | 0.35 | – |
| Transfers | 6/10 | 4/5 | – |
| Cost per conversation, upper bound | $0.147 | $0.166 | 1.13× |
| Cost per conversation, cache-aware | $0.053 | $0.073 | 1.38× |
| Latency per conversation | 78 s | 157 s | **2.0×** |
| Agent output tokens per conversation | 5,084 | 15,182 | **3.0×** |

- H002's baseline count includes one conversation interrupted by a 429 (task_058 attempt 0).
- **Cost was below forecast** because medium reasoning's extra output is priced at gpt-5-mini rates. The customer simulator (GPT-5.2) dominates the upper bound.
- **Latency doubled.** A paired comparison at these settings runs about 2.5 minutes per conversation.

## What did not change

These are the H002 failure modes, and the same ones appear here:
- **4 of 5 conversations transferred** to a human, 3 of them without executing any reference write.
- **task_089 and task_058 transferred before verifying the customer** (first unmatched reference action: `log_verification`). task_089 took 2 searches and 61 s.
- **task_069 again never unlocked `open_bank_account_4821`**, the same first miss as both H002 baseline attempts. Its required-document recall was 0.37 after 9 searches. This is the retrieval gap identified in the H002 audit (C3; doc `_009`).
- **task_077 again missed the account lookup tool** `get_all_user_accounts_by_user_id_3847`, which the H002 tool-retrieval probe found BM25 cannot reach from the customer's words.

**So more reasoning alone does not fix the dominant failures:** premature transfer, and not finding the tool or document a workflow needs. That is consistent with the decision to test **dependency-following tool search** next, as one isolated change.

## Next step: not run, needs approval

A frozen plan for a paired comparison at these same settings (medium, 16,384). There is one open choice, and it is recorded here rather than decided silently:
- **H003's go rule names "baseline vs harness_v1".**
- **The decision recorded after the H002 reviews** is "v1 as the comparator; one isolated intervention: dependency-following tool search". That means **harness_v1 vs harness_v1 + dependency-following search**.

Recommendation: the second. It is the isolated test of the one new idea. The v1-vs-baseline contrast was measured in H002 at low reasoning, and a 3-arm design would cost 1.5× more. The search component is not built yet. It will be built and tested offline at $0, then the plan frozen, before any paid run is requested.
