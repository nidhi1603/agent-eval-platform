# G001: a database-backed prototype check for one rewards-write prerequisite (2026-09-27, $0)

**Status: prototype, kept separate from the main comparison, off in every D001 arm.**
- It reads the environment's dispute records directly. That gives the combined agent-and-harness system an information channel the agent's own tools do not have: even an allow/deny result can reveal something about an unseen dispute.
- This is not answer-key leakage, since environment state and grading answers are different things. But "never reads evaluation criteria" does not establish equal information access.
- Results with this guard are not comparable to a baseline unless that access is disclosed and justified.
- The preferred design for a main comparison is an **observed-evidence guard**, using only tool results the conversation actually obtained.

The rule checks **one prerequisite**, an approved dispute. It does not establish:
- that the proposed amount is correct;
- that the transaction belongs to the customer;
- that other policy requirements hold.

A separate change from the discovery instructions, so that improved tool use and enforcement can be told apart. Code: `bench/guard.py`. Tests: `tests/test_guard.py`.

## The rule (one, reviewed)

**Policy source.** `doc_credit_cards_credit_cards_(general)_004`, "Applying Resolved Cash Back Dispute Corrections": "After a cash back dispute is resolved and approved, you must update the affected transaction(s)…". The first required step is to look up the user's resolved disputes.

**Evidence that satisfies it.** A `cash_back_disputes` record for that `transaction_id` with `status: RESOLVED` and `resolution: APPROVED`, read from the environment's own database. tau2 writes such a record when a dispute is submitted: RESOLVED/APPROVED if the task's dispute settings auto-resolve, otherwise SUBMITTED (`submit_cash_back_dispute_0589`).
- Nothing the agent or customer says can satisfy it.
- It never reads the task's evaluation criteria.
- It is re-checked on every call, never cached as "authorized".

## Where the check sits

tau2 grades the database by replaying every state-changing tool call recorded in the conversation (`Environment.set_state`). In strict mode, grading raises an error if a replayed result differs from the recorded one.

**We intercept proposals before they enter the benchmark trajectory,** so the unchanged replay evaluator receives only actions actually submitted to the environment. Other enforcement designs could work with consistent replay instrumentation; proposal interception is a practical choice here, not the only possible one.

**How a block works:**
1. If a proposed call is blocked, the model sees its attempt and the reason privately, and generates again. Up to 3 regenerations are allowed, and **every proposal is checked, including the last**.
2. After repeated blocks, a fixed refusal text is sent instead. **A blocked call is never released.**
3. Blocked proposals are absent from the official trajectory. They are fully recorded in the research trace (`trace.guard.events`: attempt number, rule, reason, tool call, arguments), and the regeneration calls are metered as agent calls in the spend ledger.

## Verified (zero cost)

| Test | Result |
|---|---|
| The S003 unauthorized write (task_019 variant, msg 24), checked in its exact saved state | **Blocked** |
| Dev task_028: disputes submitted and auto-approved, then the reference update | **Allowed**. The same write for a transaction without an approved dispute is still blocked |
| A dispute record that is only SUBMITTED | Blocked. Once changed to RESOLVED/APPROVED it is allowed (re-read per call) |
| Other tools | Not affected |
| Retries exhausted: the model proposes the blocked write 4 times | 4 blocked events (attempts 0–3), then the fallback text; the write never executes and is not in the trajectory; grading completes |
| A valid proposal after 2 blocks | Checked and returned; exactly 4 agent calls metered (unlock, blocked, blocked retry, text retry) |
| Full scripted conversation (task_028), guard on vs off | Off: the write executes and appears in the trajectory. On: blocked, logged, absent from the trajectory; official evaluation completes; input gate passes |

## Limits

- One rule, for one tool. It does not enforce identity verification or any other policy. The T001 check showed the environment executes writes with no verification at all.
- Whether the agent *recovers sensibly* after a block, and whether legitimate writes are ever wrongly blocked in live conversations, is untested. Only scripted and replayed states were used.
- Reading the database for authorization is what a permission service would do. It is disclosed as a harness change, not part of the agent's own knowledge.
