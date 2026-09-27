# G001: a proposal-time permission check for the rewards write (2026-09-27, $0)

A separate change from the discovery instructions, so that improved tool use and enforcement can be told apart. Code: `bench/guard.py`. Tests: `tests/test_guard.py`.

## The rule (one, reviewed)

**Policy source.** `doc_credit_cards_credit_cards_(general)_004`, "Applying Resolved Cash Back Dispute Corrections": "After a cash back dispute is resolved and approved, you must update the affected transaction(s)…". The first required step is to look up the user's resolved disputes.

**Evidence that satisfies it.** A `cash_back_disputes` record for that `transaction_id` with `status: RESOLVED` and `resolution: APPROVED`, read from the environment's own database. tau2 writes such a record when a dispute is submitted: RESOLVED/APPROVED if the task's dispute settings auto-resolve, otherwise SUBMITTED (`submit_cash_back_dispute_0589`).
- Nothing the agent or customer says can satisfy it.
- It never reads the task's evaluation criteria.
- It is re-checked on every call, never cached as "authorized".

## Where the check sits, and why

tau2 grades the database by **replaying every state-changing tool call recorded in the conversation** (`Environment.set_state`). In strict mode, grading raises an error if a replayed result differs from the recorded one.

So a check at *execution* time would fail. A blocked write would still be in the recorded conversation, and grading would re-execute it or raise an error.

The check therefore sits at the agent's *proposal* step:
1. The agent's proposed tool calls are checked before the message is returned.
2. If one is blocked, the model sees its attempt and the reason privately, and generates again (up to 3 times).
3. The blocked proposal never enters the conversation, so grading stays consistent.
4. Blocked proposals are logged in `trace.guard.events`, and runs are flagged "agent proposal guard (harness change; benchmark unchanged)".

## Verified (zero cost)

| Test | Result |
|---|---|
| The S003 unauthorized write (task_019 variant, msg 24), checked in its exact saved state | **Blocked** |
| Dev task_028: disputes submitted and auto-approved, then the reference update | **Allowed**. The same write for a transaction without an approved dispute is still blocked |
| A dispute record that is only SUBMITTED | Blocked. Once changed to RESOLVED/APPROVED it is allowed (re-read per call) |
| Other tools | Not affected |
| Full scripted conversation (task_028), guard on vs off | Off: the write executes and appears in the trajectory. On: blocked, logged, absent from the trajectory; official evaluation completes; input gate passes |

## Limits

- One rule, for one tool. It does not enforce identity verification or any other policy. The T001 check showed the environment executes writes with no verification at all.
- Whether the agent *recovers sensibly* after a block, and whether legitimate writes are ever wrongly blocked in live conversations, is untested. Only scripted and replayed states were used.
- Reading the database for authorization is what a permission service would do. It is disclosed as a harness change, not part of the agent's own knowledge.
