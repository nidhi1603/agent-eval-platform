# Decision record: tech-lead review of `cccd6e0` (D002 results)

**Roles.** The reviewer (ChatGPT, senior tech lead) checked the saved continuations, the manifest against the pre-run plan, and the spend. The principal engineer (Claude Code) verified each point before deciding. Spend this round: $0.

| # | Reviewer point | Verified how | Verdict | Change |
|---|---|---|---|---|
| 1 | X1(A) did not endorse $72 as an entitlement: it called the math preliminary, attributed the inputs to the customer, then said it could not confirm the APY components. The stronger failure is the false claim that the tools were unavailable | Reread the full reply | **Accept** | Relabelled as **conditional arithmetic on unverified inputs** plus a **false capability denial**. False denials are now listed at C1 and X1 in both arms |
| 2 | "0/12 unlocks" uses the wrong denominator | Checked which contexts need a new unlock | **Accept** | 0/6 discovery at W1, C1 and X1; 0/2 handover at I1; L1 (built-in) and D1 (already unlocked) need none |
| 3 | Narrow "the contract is hard for this model" | – | **Accept** | Now: "the model omitted the contract in both initial credit proposals and failed the one repair opportunity" |
| 4 | Also state that false-block behaviour on correctly evidenced writes is unassessed | – | **Accept** | Added to finding 1 |
| 5 | Pause paid enforcement; run one ablation (interface vs interface + evidence, checker off, fresh samples, same prefixes and settings); freeze outcomes; set a stopping rule | – | **Accept** | `experiments/D003_plan.json`: 12 continuations. Outcomes are frozen per case, with trade-off and reading rules. Stopping rule: after D003, stop prompt variants and write up the diagnostic findings; if discovery stays poor, the next candidate is simplifying how tools are presented. Enforcement and N001 stay paused |

**D003 checks ($0):** `tests/test_d003_plan.py`.
- The arms differ only in instruction text: B = A + the evidence section, with the checker off in both.
- The prefixes and settings are the same as D002's.
- A scripted run shows no harness at run time, and the post-hoc evidence assessment still works on the saved record.
- Suite: **172 passed, 14 xfailed**.

**Cost:** D003 may cost more than D002, because an arm that acts runs longer. Forecast $0.10–$0.45, worst case about $0.75. The recommended allocation is **$0.75**; it needs Nidhi's explicit approval.

## Follow-up: review of `57779df` (D003 scoring), before any run
All four points were accepted, and are recorded in `D003_plan.json` under `scoring_revision`:
1. **Action validity is separate from contract compliance.**
   - Action validity is labelled by reading: supported / unsupported / ambiguous / not assessable.
   - Contract compliance is secondary, because only arm B asks for it. A missing contract is not an unsupported action.
2. **"Unnecessary clarification" is narrowed** to cases where the information is sufficient and current *and* the agent may already proceed or retrieve it.
   - Consent before a credit is not a failure.
   - At I1, asking for the digits is recorded separately from not offering the documented tool.
3. **"False capability denial" is narrowed** to cases where an applicable, available capability is wrongly said not to exist. "Need approval" and "missing information" are recorded separately.
   - **Useful progress is now scored in code** from successful calls on the correct customer's relevant resource (`progress_calls` with arguments), not from a tool name. Test: a real call on another customer succeeds but does not count.
4. **The spending guarantee is removed.** "$0.75 is the proposed allocation for attempting all 12 continuations. Completion is not guaranteed."

The reviewer sees no need for another review round before Nidhi's spending decision.
