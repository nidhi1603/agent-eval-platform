# A001: direct-tool adapter, milestone 1 (built and verified, 2026-09-28, $0)

**Hypothesis to test later (A002).** Presenting retrieved tools as directly callable functions improves correct task execution, compared with requiring the model to unlock them and invoke them through wrappers.

**Why this change.**
- In selected saved failures, the agent had seen the needed tool's name and did not use the working unlock-and-call interface (T001).
- Instruction changes did not make discovery reliable (S003, D001–D003).
- This changes the interface instead of the instructions. Nothing else changes: no new retrieval, model, instructions, guards, nudges or evidence rules. The factory refuses to combine the adapter with any other intervention.

## What the adapter does (`bench/adapter.py`)
1. **Offers only names the agent received.** It reads successful `KB_search` results in the agent's own conversation for discoverable agent-tool names from the benchmark's registry. Customer tools are never offered; `give_discoverable_user_tool` is unchanged.
2. **Gets schemas through the permitted interface.**
   - For each new name, the harness issues the benchmark's own unlock call as a harness turn, without calling the model. Only after a successful receipt is the tool offered, with the benchmark's own definition.
   - Verified: for all 44 agent tools, the offered parameters and required fields match the unlock text exactly.
3. **Preserves the original execution.** A direct call by the model is sent as the benchmark's `call_discoverable_agent_tool` wrapper, with the same arguments and call id. The model's history keeps its direct call; the recorded trajectory holds the unlock and wrapper calls.
4. **Separates availability from authorization.** Offering a tool makes it callable, nothing more. The instructions are the unchanged baseline policy.

## Verification ($0; `tests/test_adapter.py`, 8 tests)
**Grading neutrality of unlocking:**
- tau2 keeps unlock state in memory; the database is written only when a tool is called.
- A scripted probe (task_015) with extra unlocks, and with an extra unlock plus a read, kept its official reward of 1.0.

**Equivalence under the official evaluator** (scripted agent and customer, real BM25):

| Task | Grading basis | Through the wrappers | Through the adapter |
|---|---|---|---|
| task_058 (open a savings account) | database | **1.0** | **1.0** |
| task_035 (emergency bureau-incident transfer) | actions | **1.0** | **1.0** |

- In task_035 the adapter also unlocked two other tools named in the same search results, and sent `"{}"` as the argument string where the reference omits it. The grade was unchanged.
- The benchmark saw the wrapper call with identical arguments, and never saw the direct call.

**Other checks:**
- Only names from successful KB results are offered: not names in error results, other tools' outputs, or customer tools.
- Nothing is offered before a search, and offered but unused tools are never executed.
- In saved-prefix runs, harness unlock turns are labelled `by: adapter`, not counted as model proposals.
- The batch runner supports the adapter as an arm option, and pairs repeated attempts separately.

**Integrity:** the agent-input integrity check still passes. The initial system prompt and tool list are unchanged; offered tools appear only after the agent's own searches.

## Disclosure
This modifies the agent scaffold. Any leaderboard submission using it would be a **custom** submission (tau2 `docs/leaderboard-submission.md`), with the adapter described.
