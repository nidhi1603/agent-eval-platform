# Decision record: tech-lead review of `493f5e1` (D002 plan)

**Roles.** The reviewer (ChatGPT, senior tech lead) ran the suite (157 passed, 14 xfailed) and probed the checker at $0. The principal engineer (Claude Code) reproduced each defect before fixing it. Spending is Nidhi's decision; the reviewer's conditional go-ahead is not approval.

| # | Reviewer point | Verified how | Verdict | Change |
|---|---|---|---|---|
| 1 | Keep D1 as a positive control | – | **Agree** | No change |
| 2 | `customer:` keyed on argument names containing "request" is too broad; bind the amount to a stated request | Code read | **Accept** | Explicit `(tool, argument)` allowlist (`CUSTOMER_REQUEST_ARGS`: the credit-limit increase submission's `requested_increase_amount`). The number must appear in a customer message that makes a request. A granted limit named `requested_limit` on another tool is rejected |
| 3a | I1 accepted `card_last_4_digits="2025"` because the customer mentioned `11/14/2025` | Reproduced on I1's real prefix | **Accept** | Digits count only if they are (i) a card-digits field (`last_4…`) of an owned record, or (ii) stated by the customer *as card digits* ("last four are…", "ending in…"). Tests cover dates, phone fragments and zip fragments (all rejected), plus three phrasings and a card record (accepted) |
| 3b | `balance / (balance - balance)` raised `DivisionByZero` | Reproduced | **Accept** | Arithmetic failures become `invalid_contract`. As a second line, any checker exception becomes a `checker_error` assessment in the agent, so neither arm can end a conversation on a checker defect. Scripted tests in both modes |
| 3c | The withheld reply "I haven't changed anything on your account" could be false after an earlier successful change | Reproduced in W1: unfreeze succeeded, then two rejected clears | **Accept** | The reply is now "I did not execute that proposed change, because I couldn't document the values it depends on." The test asserts a changed final state and the new reply |
| 4 | Reporting clarifications for D1, C1, I1, X1 and zero amounts; call it a development diagnostic | – | **Accept** | Written into the plan's expected assessments and a new `outcomes.reporting_rules`. Zero amounts now have status `unchecked` (not `supported`) |

**Regressions.** Of the new focused tests, 8 fail on `493f5e1` and pass now. Suite: **169 passed, 14 xfailed**.

**Unchanged:** contexts, prefixes, arms, instruction text and fingerprint, run order, max_rounds and cost forecast. The corrections are recorded in `D002_plan.json` under `corrections_before_run`.

**D002 status:** technically cleared, conditional on these fixes, which are done. It is not run. It needs Nidhi's explicit approval of the $0.60 total.
