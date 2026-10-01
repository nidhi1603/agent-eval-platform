# Execution outcome of actions: corrected parser (2026-10-01, $0)

**Why.** Every analysis counted an action as executed when its result was not flagged as an error and did not begin "Error". tau2 also reports failure as "Failed to log verification: Record may already exist.", which that rule counted as a success. The H009 audit found one such case (H009 task_050 attempt 1, full_exposure, i=58).

**New rule:** `bench.metrics.outcome()`, for actions: writes by the underlying tool's type, customer-tool handovers and transfers.

| Outcome | When |
|---|---|
| failure | the error flag, or the text begins "Error" or "Failed" |
| success | a receipt: contains "successful(ly)" or "confirmed", or begins "Tool given to user:", "Order ID:" or "Dispute ID:" |
| unknown | anything else. **Never counted as a success** |

**Where the formats come from:**
- tau2's banking tool source (`tau2/domains/banking_knowledge/tools.py`): every literal failure return begins "Error" or "Failed". The PIN helper messages are returned through "Error:" callers.
- A survey of every action result in all 240 local traces.

**Reads** have no receipt format. They keep the permissive rule (not an error), extended to "Failed" texts.

**Where it applies:**
- `bench.metrics.progress()`: successful, failed and unknown-outcome writes are reported apart from attempted writes, and reference matching uses only executed actions;
- `research/h009/audit/make_convs.py`.

**Runtime harness checks are unchanged,** so that v1–v3.1 behave as they ran. The verification gate reads the success receipt (`guard.VERIFIED`) and was never affected. The give-up check's "tool already used" test (`harness.used_names`) and the adapter's search-result test still use the "Error" prefix; a "Failed ..." result there could make a tool count as used. This is a known limit and is not corrected.

## Results (`recompute.py` → `corrections.json`; originals untouched)

| | Actions | Old rule executed → new failure | Unknown |
|---|---|---|---|
| All 240 local traces | 565 (517 success, 48 failure) | **1** | 0 |
| H008 (both arms) | | 0 | 0 |
| H009 | | 1: full_exposure `log_verification`, audited **ok** | 0 |

**What changes:** H009 full_exposure successful writes, 35 → 34. Nothing else changes in H008 or H009:
- no reference-action match;
- no pass;
- no audited violation, V or C;
- no verdict.

The committed `diagnostics.json`, `writes.json` and `tally.json` are kept as produced. This file records the correction.

    uv run --extra bench python research/execution_outcomes/recompute.py
