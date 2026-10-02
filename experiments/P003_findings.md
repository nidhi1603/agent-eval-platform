# P003 findings: reason-code re-check with vs without doc 042 (run 2026-10-02)

**Approved:** "run P003" (Nidhi, in chat), against the plan's frozen $1.00 cap. **Spend:** $0.14 billed estimate ($0.44 upper bound), 54 calls, all ok.
**Plan:** `experiments/P003_plan.json`, frozen at b535789, before any call.
**Fidelity:** all 54 requests sent the original tool list (`tools_sent_equal_original_request: true`).

## Verdict (frozen gate): PASS, with G1 met exactly at its threshold

| Gate | Result | Needed |
|---|---|---|
| G1: originally wrong cases right under treatment | **2 of 4** | at least 2 |
| G2: cases right, treatment vs control | **7 vs 5** of 9 | treatment more |
| G3: originally right cases failing under treatment | **0 of 5** | 0 |

**Sensitivity.** The pass depends on one case at 2 of 3 (db563b6). One more wrong sample there and G1 fails. Treat this as a screening pass, not a robust effect.

## Samples (27 per arm)

| | Control (re-check request) | Treatment (request + doc 042) |
|---|---|---|
| Right code | 13 | **20** |
| Wrong code | 11 | 7 |
| No transfer call (text only) | 3 | 0 |
| Invalid code | 0 | 0 |
| Wrong samples on originally right cases | **2** | **0** |
| Anomalies (extra transfer or other tool calls) | 0 | 0 |

On originally wrong cases, the control's samples were never right: 0 of 12. Treatment's were right in 5 of 12.

## Per case (right samples out of 3)

| Case | Task | Originally | Doc 042 before | Control | Treatment |
|---|---|---|---|---|---|
| d7f79f2 | 004 | wrong | present | 0 | **3** |
| db563b6 | 004 | wrong | absent | 0 | **2** |
| da368e0 | 004 | wrong | present | 0 | 0 |
| da94b93 | 004 | wrong | absent | 0 (2 text only) | 0 |
| dae642b | 004 | right | present | 2 (1 text only) | 3 |
| dbea0fa | 004 | right | present | 2 | 3 |
| dc7c3e3 | 004 | right | present | 3 | 3 |
| d17cd57 | 012 | right | present | 3 | 3 |
| d300e41 | 012 | right | present | 3 | 3 |

**By exposure (descriptive):**
- **Document absent:** treatment right in 1 of 2 cases, control 0.
- **Document present:** treatment right in 6 of 7 cases, control 5. That includes 1 of the 2 originally wrong cases: re-presenting the document coincided with a fix where it was already in context. This supports re-presenting it as a candidate intervention; it does not identify renewed attention as the mechanism (wording corrected after review).

**The two cases treatment did not fix** are the same customer situation, which the agent summarised as "requests transfer to update their account email". In all 6 treatment samples the agent kept `customer_requests_human_no_specific_reason`. The document was not enough when the agent's own framing of the situation did not match the account-ownership tier. This is observational.

**What the control did.** Re-asking without the document never fixed a wrong case. It broke 2 of 15 samples on originally right cases: one wrong code, one text-only reply. Text-only replies (3) occurred only in the control. In this selected probe the request alone did not help; that does not show that reconsideration without the document is generally ineffective (wording corrected after review).

## What this shows, and what it cannot

**Shows:** at a held transfer in these 9 selected task_004 and task_012 histories, re-checking with doc 042 picked the graded code more often than re-checking without it: 20 vs 13 of 27 samples, 7 vs 5 of 9 cases. It did not break any originally right case, at either case or sample level.

**Cannot show:**
- **Score effect.** Nothing was executed. A right code is a PROPOSED action, so this demonstrates neither a successful transfer nor a higher official reward.
- **Generality.** 9 cases from 2 tasks; all 4 originally wrong cases are one task (task_004) and two customer situations. This is development data, with 3 samples per arm.
- **Cost or obstruction in live conversations,** where every transfer would get one extra hold.

## Next step (per the frozen rule; needs its own plan and approval)

A full-conversation comparison: the standard agent vs the standard agent plus this component, on a fixed task mix, measuring completion, policy violations and cost.
- **The component:** reconsider each pending transfer ONCE with doc 042 and the re-check request. The reissued transfer is then handled normally, never held again.
- **The answer key stays out of runtime:** no target, task identity or grading information.
