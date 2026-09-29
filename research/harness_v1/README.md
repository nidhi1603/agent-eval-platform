# Harness v1: Stage 0 record (2026-09-29, $0)

Code: `bench/harness.py`. Tests: `tests/test_harness.py` (28 tests) and `tests/test_h001_plan.py`.
Frozen pilot plan: `experiments/H001_plan.json`, not run.

## What harness v1 is

It is the direct-tool adapter (A001) plus four checks. Each check runs when the agent proposes something, before
that proposal enters the benchmark's record. A held proposal and the feedback on it go only into the model's own
history.

| Check | Kind | Fires before | What the agent is told |
|---|---|---|---|
| `search_before_giving_up` | soft (advises once per give-up; a repeat is released) | a transfer to a human, or a reply saying something can't be done | how many searches it ran and which queries, and to search again naming the product and the action. If it has not used any discovered tool yet: the lookup tools and customer tools its retrieved documents named that it has not used (never write tools) |
| `clock_before_verification` | hard (one correction, then released) | `log_verification` with a time that is not a clock reading | the exact clock reading to use, or to call `get_current_time` |
| `verification_before_write` | hard (one correction, then withheld) | any write, when no verification has been logged | the steps: look the customer up, check their details, read the clock, log verification |
| `ids_observed` | hard (one correction, then withheld) | a write, or `log_verification`, with an identifier or card digits never seen in a successful tool result or in the customer's words | which values were not seen, and which lookups can supply them |

Limits:
- At most 1 regeneration per turn and 8 per conversation.
- A withheld write is replaced by a fixed reply to the customer, and the write never runs.
- Amounts and ownership are assessed with `bench/evidence.py` and logged, but not enforced.

**What the checks can see:** only the agent's own conversation, plus static tool metadata (read/write type, and
which names are discoverable). They never see the database or task data, and never call
`list_discoverable_agent_tools`.

**Feedback modes, for the Stage 2 ablation:**
- `structured` (the default);
- `generic` (the same checks, one generic retry message);
- `block` (hard checks only, with a bare "not executed").

## Design sources

| Source | What we took | What we did differently |
|---|---|---|
| **PolicyGuide** (2608.19861), **PolicyGuard** (2606.29225) | Verify outside the model, remediate with the missing step, one-shot gating, gate transfers | They compile a policy the agent is *given* up front. Here the policy has to be retrieved, so remediation points to *where to look* |
| **Outcome Monitors** (2608.19303) | The list of recovery tools is what produces the gain | – |
| **Verifier Tax** (2603.19328) | Blocking alone doesn't help; invented identifiers are the most common violation; more retries don't help | – |

None of these four evaluates banking_knowledge. None checks whether the agent searched enough before giving up, and
none handles tools discovered partway through a conversation.

## Positive control: the 19 saved failed conversations (`replay_saved.py`, `replay_saved.json`)

For each saved conversation, this asks where each check would *first* have fired, judged only from what the agent
had seen at that point.

| R001 primary cause | Conversations | A check fires at or before the failure point |
|---|---|---|
| Tool use | 7 | **7** (give-up check: 035 [8], 080 [22], 066-dc [20], 094 [4]/[14], 095 [26]/[32]) |
| Argument (invented time) | 2 | **2** (clock check: 089 [8], 087 [10]) |
| Retrieval | 8 | 3 (029, 031-dc, 087-dc). The other 5 never gave up; they answered or acted wrongly, which no give-up check can see |
| User simulator / policy | 2 | 0 (expected) |

- **One false fire:** 019-baseline [8]. The agent said it can't look up an account by phone number, which is true.
- **What a firing means:** that the conversation *reaches* a check. It does not show that the agent then recovers.
  Only live runs can show that.

## Negative control: correct behaviour on all 30 dev tasks (`reference_controls.py`, `reference_controls.json`)

**What was scripted.** A careful agent performs each task's reference solution:
- 3 knowledge-base searches;
- a customer lookup and a clock read before verification;
- a read of the customer's card accounts, transactions and bank accounts.

A scripted customer performs the reference customer actions and states the card digits. Each script runs through
the real tau2 path and the official evaluator, once with the baseline and once with harness v1.

**Results:**
- **Same official reward: 30/30** (all 1.0).
- **Hard checks firing on correct behaviour: 0/30.**
- **Soft advisory:** fired on 2 correct transfers (004, 012) after 3 searches, because the retrieved documents named unused tools. The cost is one extra model call, after which the repeated transfer is released.
- **Prompt size:** agent input tokens are 1.09× the baseline, from the discovered tools' definitions (15–22 offered per task).

**How the control changed the design (all before any spend):**
1. **Ownership-based identifier check: dropped from enforcement.** The first version enforced ownership (identifiers must be in the verified customer's own records). It held correct writes in **8/30** tasks: identifiers created mid-conversation (a new account's ID in a free-text receipt) and card digits the customer reads out. It is now logged only. The enforced version asks only whether the value was *seen at all*, which still catches invented identifiers.
2. **Tool-name matching: fixed.** The first version missed customer tools whose names have no numeric suffix (`get_card_last_4_digits`). Names are now matched against the registry.
3. **Unused-tools advisory: now requires that the agent has used no discovered tool yet.** The first version also fired on 035's correct "emergency tool, then transfer" sequence.
4. **Scripted solutions: completed.** The reference omits reads a real agent needs (e.g. 069 closes an existing account whose ID only an account lookup returns), so the scripted careful agent performs them.

## Honest limits

- The controls prove that the checks fire where intended, and do not break correct behaviour. They do not prove that a live model recovers after a check. That is what H001 measures.
- The soft advisory's search threshold (3) and its denial phrases were chosen after reading our own dev failures. That is dev-set tuning. Only the frozen held-out run (Stage 3) can show whether they generalise.
- Remediation text is generic. It names no task-specific product, value or procedure.
