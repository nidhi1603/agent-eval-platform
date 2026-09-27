# S002: first consequential error per task (labelled by reading each trace)

Batch: 6 pre-registered dev tasks, 1 trial each, run 2026-09-27.
- Models: gpt-5-mini agent (reasoning_effort low), gpt-5.2 user simulator.
- Setup: bm25, unchanged tau2 v1.0.1, $1 approved.
- Results: `experiments/S002_results.json`. Traces: `runs/local/20260927T06*_live_*/trace.json`.

**Outcome:** 6 of 6 finished, **0 of 6 rewarded**. Every run was ended by the user simulator and attributed to the agent by the official evaluator.
- Exposure: `not_observed` in all 6. The diagnostic was conclusive, and the agent never called `list_discoverable_agent_tools`.
- Exploratory: one trial per task. This is not a reliability estimate and not leaderboard-comparable (bm25).

**Labelling method.**
- The label is the earliest agent step after which the official outcome could no longer be reached.
- Each label was checked against the reference actions and the knowledge-base documents. Document IDs are cited, so each label can be re-checked.
- Labels are my reading (AI-assisted), not an automated classifier.

| Task | First consequential error | Evidence | Later errors in the same trace |
|---|---|---|---|
| task_035 | **msg 8:** did a generic `transfer_to_human_agents` without first unlocking and calling `emergency_credit_bureau_incident_transfer_1114`. The document it had retrieved (msg 3, `doc_credit_cards_credit_cards_(general)_012`) says "IMMEDIATELY use emergency_credit_bureau_incident_transfer_1114() then transfer_to_human_agents". At msg 6 it ran a KB search for the tool's name instead of unlocking it | ACTION reward 0: both discoverable steps are missing | msg 12 claims it added details to the handoff after the transfer |
| task_080 | **msg 22:** told the user it could not freeze the cards or order replacements "from here", and transferred them. Discoverable tools were never unlocked, although it had put tool names such as `freeze_debit_card_3892` into a KB search at msg 12 | 0 of 33 discoverable reference steps performed | none after the transfer |
| task_089 | **msg 8:** called `log_verification` with `time_verified: "2026-09-27 17:06:00 UTC"` without calling `get_current_time`. The environment time is 2025-11-14 03:40:00 EST, so the verification record can't match | The `log_verification` action doesn't match; DB reward 0 | msg 16 and msg 20: says it has no tool to find the debit card or its withdrawal history; `get_debit_cards_by_account_id_7823` and `get_bank_account_transactions_9173` were never unlocked |
| task_029 | **msg 19:** flagged "reward mismatches" using an invented rule (reward points should equal the dollar amount) without retrieving any card reward rates. None of the 6 reference transactions were in its list | 0 of 6 reference transactions identified | msg 21: says it "can't directly open formal investigation cases" and transfers, without searching the KB for a dispute procedure. The reference gives the user `submit_cash_back_dispute_0589` |
| task_069 | **msg 18:** recommended Bluest checking + Bronze savings. It said it "did not find any KB doc that explicitly states a savings account reimburses out-of-network ATM fees". The KB documents Silver Plus savings ATM rebates (`doc_savings_accounts_silver_plus_account_002`, `_003`), but the agent never retrieved them. It had done one broad search before recommending | Reference: Silver Plus savings + Blue checking. No accounts were opened | The user asked for a transfer at msg 27 |
| task_047 | **msg 16:** said the KB "doesn't list a Rho-Bank business card that explicitly advertises a 3.5% return on both travel and advertising". The Business Platinum Rewards Card documents 4.0% on travel and media advertising and a 0% foreign transaction fee (`doc_business_credit_cards_business_platinum_rewards_card_002`, `_003`, `_006`); the agent never retrieved them. The user then chose to close the card | Reference: log closure reason, then the user applies for Business Platinum | msg 20: relied on the user saying there were no disputes or pending replacements instead of checking with `get_user_dispute_history_7291` and `get_pending_replacement_orders_5765`. msg 26: redeemed points using reason `retention_offer` |

For comparison, **S001 (task_015, msg 4):** the agent gave `get_referral_link` for a card with no referral document in the retrieved results (labelled TRUST, with READ contributing).

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
