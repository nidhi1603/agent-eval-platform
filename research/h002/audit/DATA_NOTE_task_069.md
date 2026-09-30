# Data note: task_069 and the Gold Account ATM rebate (recorded 2026-09-30; unresolved, nothing changed)

**What the task asserts.** The task (`tasks/task_069.json`, notes and user scenario) says, in effect, "Gold Account has NO ATM rebates". It treats recommending Gold savings as "the trap", and the scripted customer requires a savings account that reimburses out-of-network ATM fees.

**What a knowledge-base document says.** `doc_savings_accounts_gold_account_003` ("Gold Account specifications and requirements") lists "ATM fee rebate cap per month: $30", in both its text and its table.

**The task's required documents** include `doc_savings_accounts_gold_account_001` but **not** `_003`. So the conflict may come from the documents disagreeing with each other, or from a distinction we have not established (for example, rebates for checking vs savings).

**Handling:**
- H002's original results for task_069 are preserved. The task is not repaired or removed after seeing outcomes.
- Every result table that includes task_069 carries this note.
- If the conflict matters for a later claim, it should be reported upstream as a possible data issue, with Nidhi's approval before filing anything.
