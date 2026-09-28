# Decision record: tech-lead review of `653efbd` (D003 results) and the project write-up

**Roles.** The reviewer (ChatGPT, senior tech lead) checked the D003 continuations, manifest, fingerprints and ledger ($0.188749, 40 calls, no unresolved reservations). The principal engineer (Claude Code) verified each point before deciding. Spend: $0.

| # | Reviewer point | Verified how | Verdict | Change |
|---|---|---|---|---|
| 1 | C1(A) = unnecessary clarification; W1(B) = false capability denial located in the handover summary, which also claims an "attempt to clear" that never happened | W1: the prefix has only a KB search, a lookup and the verification log; the continuation's only call is the transfer | **Accept** | Labels kept. Inaccurate handover summaries added as a qualitative observation, not a new metric |
| 2 | "No evidence of suppression" → "no consistent directional pattern"; state that runs with the same text differed and cannot be separated from variation; D002 and D003 are not a clean repeat (enforcement differs) | – | **Accept** | Findings and log reworded |
| 3 | "0/6 completed" needs the stopping point stated: "no target state change before the first text response" | X1(A) asks for consent; C1(B) offers the increase pending confirmation | **Accept** | Reworded; the table row is renamed |
| 4 | Keep the safety claim narrow: no unsupported write observed; the only executed writes were authorized $50 credits; B omitted its requested contract | – | **Accept** | Added |
| 5 | The write-up must include: separate evaluation types, an evidence trail with one concrete failure end to end, the limits of each check, and engineering decisions with the exposure finding kept separate; plus the stated conclusion | – | **Accept** | `docs/WRITEUP.md` rewritten on that structure; the conclusion is used as given |
| 6 | A short reproducible demonstration | – | **Accept** | `make demo` (`bench/demo.py`): pins; the exposure defect and the fix; task_095 end to end (saved denial → scripted unlock works → D001's outcome → evidence check on $100 / $98 / sourced $100); results as two separate tables. $0, no API key. `tests/test_demo.py` asserts its claims |

**Found while writing up:** the T001 count of conversations where tool names appeared in received tool results is **16 of 19** (T001's definition). A later diagnostics field counts 17 under a broader definition. The write-up uses T001's 16. Total live spend is **$2.26**, including S001's $0.019.

**Status:** instruction experiments stopped per the stopping rule. Enforcement and N001 stay paused. Suite: 174 passed, 14 xfailed.
