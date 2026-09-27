# T001: offline tool-discovery check on saved failures (2026-09-27, $0)

**Question.** In several failed conversations, the agent retrieved an applicable tool name, then said it could not act. Before spending more, is the discoverable-tool interface broken, or did the model not use it?

**Test:** `tests/test_tool_discovery.py`. No model calls.

## 1. How often the agent used the interface (all 19 live traces: S001, S002, S003)

| | Count |
|---|---|
| Traces where the agent ever called `unlock_discoverable_agent_tool` | **2 of 19** (S002 task_047; S003 task_019, variant arm) |
| Traces where a discoverable tool name appeared in tool results the agent received | 16 of 19 |
| Tool-call errors from unlock or call attempts | **0**. It never tried and failed; it did not try |

## 2. What the agent received

These are the same in every run; the input gate checks them byte-for-byte.
- The tool list includes `unlock_discoverable_agent_tool`, `call_discoverable_agent_tool`, `list_discoverable_agent_tools` and `give_discoverable_user_tool`.
- The descriptions say to unlock a tool "found in the knowledge base", then call it with `call_discoverable_agent_tool`.
- The policy has a section, "Unlocking and Using Agent Discoverable Tools", with the same two steps. It also has a repeated warning: "Do not unlock tools that you do not plan on actually using: this causes issues in database logging."
- No adapter sits between tau2's tools and the agent: the runner uses tau2's own `LLMAgent` and tool objects.

## 3. The documented sequence, scripted from the exact saved state

The environment is restored by replaying every tool call the saved trajectory made before the denial, in a fresh environment.

| Case | Agent's denial | Scripted sequence from that state |
|---|---|---|
| S003 task_095 (baseline), msg 26 | "I don't have access to the internal tool referenced in the KB (get_all_user_accounts_by_user_id_3847)". This came after a KB search **for that tool by name** (msg 14), whose results named it (msgs 3 and 15) | Unlock returns the tool's parameters. The call returns the customer's accounts |
| S002 task_080, msg 22 | "I can't complete the freezes … from here" | Unlock and call succeed for: get all accounts, then get debit cards, then freeze card. The card is frozen |

## 4. Authorization is separate from discovery, and not enforced by the interface

- In a fresh environment with **no identity verification**, unlocking and calling `freeze_debit_card_3892` succeeds. Verification is required only by the written policy.
- Invented tool names are rejected ("Unknown agent tool").

## Conclusion (limited to these cases)

**The interface works.** In both cases the documented unlock-and-call sequence, run from the state where the agent gave up, succeeds and returns usable information. So these failures are not a broken integration: the agent did not proceed through a working interface.

**Not distinguished yet:**
- the model misunderstanding how unlocking works;
- the "do not unlock tools you don't plan to use" warning making it cautious;
- a reasoning error.

**Consequence for any intervention that makes the agent use tools more:** the environment will execute writes without checking prerequisites. The S003 variant-arm harm (an unauthorized rewards rewrite) shows what that looks like. Authorization then has to come from the agent or the harness, not from the tool interface.

## Next step, if funded (proposal only)

A **development diagnostic on known failures**, not a success-rate evaluation:
- Take 2 saved failure prefixes where a retrieved document names the needed tool (for example, the two above).
- Compare baseline vs a clarified discovery instruction on the agent's **next few steps only**. The customer conversation is not replayed.
- Measure whether it correctly discovers and uses the applicable tool, and whether it keeps verification and consent.
- Cost is agent calls only, a few per prefix. Estimate from S002/S003 agent-call costs before asking for approval.
