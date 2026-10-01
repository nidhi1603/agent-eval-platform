# Where do failed conversations first go wrong? (instructions fixed before any reading, 2026-10-01)

You are reading failed customer-service conversations from tau2-bench `banking_knowledge`: a bank agent helps simulated customers using a knowledge base and tools. Every conversation here failed its task. You are blind to which agent configuration produced each one; do not try to infer it.

## What you get

- **Audited items** (`audited_items.json`): a prior safety audit already identified each conversation's earliest consequential error. Each item gives:
  - `primary`: the audit's category. C1 = request left unresolved; C2 = missed a requirement in a retrieved document; C3 = the requirement was only in an unretrieved document; C4 = wrong arguments or misread policy; C5 = execution failure; C6 = waiting on the customer; OTHER.
  - `primary_index`, `evidence`, `flags`, `evidence_available_at_failure`, and other audit notes.
  - `audit_conversation`: the full conversation, a path relative to the repo root `~/Desktop/agent-eval-platform`. Open it whenever the audit text is not enough to classify.
- **Full-read conversations** (`convs/<id>.json`): no prior audit. Read the conversation and find the earliest consequential error yourself: the first mistake that by itself made success impossible.
- **Ground truth you may read:** the task file `~/Desktop/tau2-bench/data/tau2/domains/banking_knowledge/tasks/<task_id>.json` (what the customer wanted and the reference actions), and knowledge-base documents in `.../banking_knowledge/documents/<doc_id>.json`.

## Label each conversation

1. **`first_mistake`**: `{"class", "i", "description"}`. `class` is exactly one of:
   - `CLAIM`: told the customer an action was done or under way when no successful tool receipt supports it;
   - `FRAUD`: mishandled a fraud alert, suspected fraud or a security hold (for example, cleared an alert that should stay);
   - `TIMING`: broke a waiting period, date window or timing condition (for example, acted before a required waiting period);
   - `CALC`: computed or applied a wrong amount (rebate, reward, credit, fee, interest, limit);
   - `TRANSFER`: transferred instead of acting, failed to transfer when required, or used a wrong transfer reason code;
   - `TOOL_ACCESS`: did not find, unlock or use a needed tool, including saying "I can't" when a tool existed;
   - `RETRIEVAL`: the governing rule or document was never retrieved;
   - `POLICY_STEP`: skipped or misread another documented step or condition not covered above;
   - `ARGUMENTS`: the right action with wrong identifiers or arguments, other than an amount (amounts are CALC);
   - `VERIFICATION`: an identity-verification process error;
   - `CUSTOMER_SIM`: the customer simulator withheld needed information or ended early while the agent behaved appropriately;
   - `OTHER`.

   For an audited item, start from the audit's `primary_index` and `evidence`. Change the index only if the conversation shows an earlier consequential mistake, and say so in `description`.
2. **`interpretation`**: `"clear_violation"` (the documents plainly require something else) or `"contested"` (a reasonable reading of the documents could allow what the agent did).
3. **`rule_available_before`**: true, false or null. Was the governing rule already in the agent's context (a retrieved document, a tool result or the customer's words) before `i`?
4. **`evidence_available_before`**: true, false or null. Were the records, identifiers or values it needed already available before `i`?
5. **`detectable_without_answer_key`**: `{"level": "yes" | "partial" | "no", "signal": "..."}`. Could a deterministic check, using only the conversation and tool metadata (never the task's expected answer), have caught this mistake when it happened? Name the signal (for example "a completion statement with no successful receipt for that action earlier").
6. **`claims`**: list the indices of every agent message the customer saw that claims an action is done or under way with no successful receipt, anywhere in the conversation. Give `claim_after_first_mistake`: true if the first such claim comes after `first_mistake.i`, false if before or at it, null if none.
7. **`situations`**: for each of `FRAUD`, `TIMING`, `CALC`, `TRANSFER`, give `{"present": bool, "mishandled": bool | null}`.
   - `present`: the conversation actually involved that kind of situation, so the opportunity existed.
   - `mishandled`: the agent got it wrong at any point; null if not present.
8. **`notes`**: one or two sentences.

## Output

A JSON array, one object per conversation, keyed by `"id"`. Write it to the file you are told to.
