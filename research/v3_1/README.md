# Harness v3.1: v3 with an explicit, once-only transfer hold

v3.1 changes one thing in v3: what happens when `search_before_giving_up` holds a `transfer_to_human_agents` call. Capability search, the hard checks, and the hold on a capability denial are unchanged. v1, v2 and v3 behave exactly as before.

## Why

Evidence, all from saved data ($0):

| Finding | Source |
|---|---|
| 3 of the 12 evaluation tasks pass only if the agent transfers (task_004, task_012, task_035) | `research/literature/checks.json` |
| The check would have held 16 of the 23 correct transfers the public top agents proposed on those tasks, and 0 of their 9 unwanted ones | `research/literature/checks.json` |
| In our runs, a transfer was held in 25 harness conversations; one was executed later in 0 | `held_transfers.json` |
| Where the model's own history was saved (9 conversations, H004), the agent's next action after the hold was a message to the customer in 9 of 9, saying a transfer was under way in 9 of 9; it made no tool call afterwards in any | `held_transfers.json` |
| The check also holds the reference solution's transfer on task_004 and task_012 in the scripted controls | `research/harness_v1/reference_controls_v3.json` |

So the v1 hold did not produce the search it asked for: the agent told the customer a transfer was under way, and no transfer was made. A plausible explanation is that it treated the hold as a completed transfer, since the v1 text opens "you are about to transfer the customer" and never says the call did not run. The nine replies establish the behaviour, not the explanation; D004 tests whether changing the text changes the behaviour.

This matches two published results: refusals with no notice are read as completed work (70 of 86 cases, against 0 of 89 with a same-turn notice; arXiv 2609.25686), and an advisory that says the repeated call will execute is overridden when the agent still judges the action right (8 of 30 on tau2 airline, same paper).

## What changed (`bench/harness.py`)

1. **The feedback says the call was not executed.** It opens: the transfer call was NOT executed, the customer has not been transferred and is still with the agent, do not tell them a transfer is under way.
2. **It says a repeat will go through.** It closes: if a transfer is still the right step, call `transfer_to_human_agents` again; it will be executed and this check will not hold it again in this conversation.
3. **A transfer is held at most once per conversation.** In v1 and v3 it can be held on every turn (four times in one task_092 conversation).

The remediation in between (how many searches were run, which retrieved lookup or customer tools are unused, the capability-wording advice) is v3's.

The firing condition is unchanged: the first transfer by an agent with fewer than 3 searches, or with unused retrieved tools and no discovered tool used, is still held. v3.1 does not make the check more selective; it makes the hold honest and escapable.

## Validated offline

- `tests/test_harness_v3_1.py` (7 tests): the new text; once per conversation; a denial is unchanged; v1 and v3 text unchanged; end to end through the real tau2 path, a transfer held in one turn executes when repeated in a later turn under v3.1 and is held again under v3.
- Reference controls, `--version=v3.1`: 30 of 30 same reward as the standard agent under bm25 and under alltools; 0 hard-check firings.

## Not shown offline

What gpt-5-mini does after reading the new text. The scripted tests prove the mechanics, not the model's behaviour. H008 measures it: held transfers, whether one is executed later, and whether the agent tells the customer a transfer is under way with none executed.

## Reproduce

    uv run --extra bench python research/v3_1/held_transfers.py
    uv run --extra bench python research/harness_v1/reference_controls.py --version=v3.1 [--retrieval=alltools]
    uv run --extra bench pytest tests/test_harness_v3_1.py tests/test_h008_plan.py
