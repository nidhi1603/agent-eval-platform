# S002: first consequential error per task (labelled by reading each trace)

Batch: 6 pre-registered dev tasks, 1 trial each, run 2026-09-27.
- Models: gpt-5-mini agent (reasoning_effort low), gpt-5.2 user simulator.
- Setup: bm25, unchanged tau2 v1.0.1, $1 approved.
- Results: `experiments/S002_results.json`. Traces: `results/S002/<task>/trace.json` (copied from `runs/local/`).

**Outcome (S002's own result):** 6 of 6 finished, **0 of 6 rewarded**. Every run was ended by the user simulator and attributed to the agent by the official evaluator.
- Exposure: `not_observed` in all 6. The diagnostic was conclusive, and the agent never called `list_discoverable_agent_tools`.
- Exploratory: one trial per task. This is not a reliability estimate and not leaderboard-comparable (bm25).

**Labelling method.**
- The label is the earliest agent step after which the official outcome could no longer be reached.
- Each label was checked against the reference actions and the knowledge-base documents. Document IDs are cited, so each label can be re-checked.
- Labels are my reading (AI-assisted), not an automated classifier.

Each task is recorded in three separate parts: **observed behaviour** (what the trace shows), **suspected cause** (an interpretation, not tested) and **grading failure** (what the official evaluator checked).

| Task | Observed behaviour (first consequential step) | Suspected cause (untested) | Grading failure |
|---|---|---|---|
| task_035 | **msg 8:** plain `transfer_to_human_agents`. The retrieved doc (msg 3, `doc_credit_cards_credit_cards_(general)_012`) says "IMMEDIATELY use emergency_credit_bureau_incident_transfer_1114() then transfer_to_human_agents". At msg 6 the agent KB-searched the tool's name instead of unlocking it | Procedure retrieved but not followed. **Retrieval cannot explain this one** | ACTION basis: the unlock and call of the incident tool are missing (the transfer itself matched) |
| task_080 | **msg 22:** "can't complete the freezes… from here", then a transfer. No discoverable tool was ever unlocked, although tool names such as `freeze_debit_card_3892` appeared in its KB query at msg 12 | Did not use the unlock mechanism. Whether the doc it retrieved named every needed tool is not established | DB basis: DB mismatch. The reference has 33 discoverable steps and none were performed; that count is **context, not proof** that every step is required. The DB check requires the writes (freeze, close, order, dispute, activate) and allowlisted reads |
| task_089 | **msg 8:** `log_verification` with `time_verified: "2026-09-27 17:06:00 UTC"`, with no `get_current_time` call. The environment time is 2025-11-14 03:40:00 EST. Later (msgs 16, 20) it said it had no tool to find the card or the withdrawals; those tools were never unlocked | A fabricated procedural value; later, the unlock mechanism unused | DB basis. A zero-cost grader replay (reference actions with one change) shows the **wrong timestamp alone** changes the final DB, and **omitting the limit-increase write alone** changes it too. Two independently sufficient failures |
| task_029 | **msg 19:** flagged "reward mismatches" with an invented rule (points = dollars), without retrieving card reward rates. 0 of the 6 reference transactions were in its list. msg 21: "can't directly open formal investigation cases", then a transfer, without a KB search for a dispute procedure | Analysis from insufficient retrieval, then an unsupported denial | DB basis: the 6 user-side `submit_cash_back_dispute_0589` calls are missing (they needed `give_discoverable_user_tool`) |
| task_069 | **msg 18:** recommended Bluest checking + Bronze savings, saying it "did not find any KB doc that explicitly states a savings account reimburses out-of-network ATM fees". Silver Plus ATM rebate docs exist (`doc_savings_accounts_silver_plus_account_002`, `_003`) and were never retrieved; one broad search came before the recommendation | Search quality, query choice, or concluding too early: **not distinguished** by this trace | DB basis: the reference account openings, card application and closure are missing |
| task_047 | **msg 16:** "doesn't list a Rho-Bank business card that explicitly advertises a 3.5% return on both travel and advertising". Business Platinum docs (`doc_business_credit_cards_business_platinum_rewards_card_002`, `_003`, `_006`) document 4.0% on travel and media advertising and a 0% FX fee; never retrieved. Later: eligibility accepted on the customer's word (msg 20); points redeemed with reason `retention_offer` (msg 26) | Search quality, query choice, or concluding too early: **not distinguished** | DB basis: closure-reason log and checks missing; the card was closed instead of switched |

Context only (a separate earlier stage, not pooled with S002), **S001 (task_015, msg 4):** the agent gave `get_referral_link` for a card with no referral document in the retrieved results (labelled TRUST, with READ contributing).

## Patterns (counted over the 6 S002 traces; overlapping, not exclusive)

| Pattern | As the first error | Anywhere in the trace |
|---|---|---|
| **A negative conclusion without an adequate search** ("not documented", "no tool", "can't do that here"), which then drives a transfer or a wrong recommendation | 3 (069, 047, 080) | **5** (069, 047, 080, 089, 029) |
| **Discoverable agent tools not unlocked when needed**, even though the KB named them (035, 080) or they were needed and never searched for (089) | 2 (035, 080) | **3** (035, 080, 089). In 029 the missing tool is a user tool (`give_discoverable_user_tool`) |
| An answer or analysis from too little retrieval (no absence claim) | 1 (029) | 1 |
| A procedural argument invented instead of fetched (timestamp) | 1 (089) | 1 |
| Discoverable tools used correctly | – | 1 (047 unlocked and called two tools) |

**Most common observed failure:** the agent concludes something is unavailable (a document, a product, or a capability) without searching for it specifically, then transfers the customer or recommends the wrong thing. Where a tool is missing, the specific form is not unlocking tools the KB names.

**Caveats:**
- n = 6, one trial each; these are counts, not rates.
- The first-error categories are mixed.
- Other plausible causes were not tested: bm25 retrieval quality (the top-k misses the right document), and `reasoning_effort: low`.
- The policy text warns "Do not unlock tools that you do not plan on actually using: this causes issues in database logging". **Hypothesis, untested:** that warning makes the agent reluctant to unlock tools.

## Measured cost per rollout (the input to any paid follow-up)

| | Full-price estimate | Cache-aware estimate |
|---|---|---|
| Batch total, 6 rollouts, 119 LLM calls | $0.601 | $0.283 |
| Per rollout: mean (range) | $0.100 ($0.035–$0.142) | $0.047 ($0.021–$0.078) |
| Agent (gpt-5-mini), 77 calls | $0.292 | $0.119 |
| User simulator (gpt-5.2), 42 calls | $0.309 | $0.164 |

- The admission-control upper bound equalled the usage-based estimate: $0.601, with no unresolved calls.
- These are estimates from token usage and list prices. They are not reconciled with the provider's billing.
- The user simulator is about half the cost, so any intervention study pays for it on every trial.
