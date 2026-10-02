# Transfer decisions: a policy-based reading (instructions fixed before any reading, 2026-10-01)

You are reading decision points from simulated bank customer-service conversations (tau2-bench `banking_knowledge`). At each decision point, the agent either transferred the customer to a human (`transfer_to_human_agents`) or did not. You are blind to which agent configuration produced each conversation and to whether the task succeeded. **Do not open the task files**: judge from the bank's policy and what the agent could see, not from the benchmark's expected answer.

## What you get

`points/<id>.json`, with:
- `decision_kind`:
  - `T`: a transfer call at `decision_index`;
  - `ASK`: the customer asked for a human or escalation and no transfer followed; the decision point is the agent's next message;
  - `EXPECTED`: the conversation ended with no transfer at all; the decision point is the agent's last message.
- `messages`: the conversation up to the decision point, plus up to 3 messages after it.
  - Record, transaction and action results are complete.
  - Knowledge-base search and shell outputs are clipped, but list every document id they named.
  - `customer_saw_it` marks agent messages the customer received.

You may read the knowledge-base documents in `~/Desktop/tau2-bench/data/tau2/domains/banking_knowledge/documents/<doc_id>.json`, and the domain policy in `~/Desktop/tau2-bench/data/tau2/domains/banking_knowledge/prompts/`. The transfer reason codes and their priority tiers are in `doc_bank_accounts_bank_accounts_(general)_042.json`: "always select from the highest tier that applies".

## Label each decision point

1. **`real_decision`** (true/false). For `ASK` or `EXPECTED`: was a transfer actually a live question at that point? For example, "specialist" may just be a word the customer used. If false, fill only `notes`.
2. **`available_information`**: one or two sentences on the relevant customer statements, records and policy text the agent had actually SEEN before the decision point. Say whether the reason-code document (042) or another governing document was among them.
3. **`transfer_basis`**, under the bank's policy given what was available:
   - `"required"`: policy requires a transfer here;
   - `"permitted"`: a transfer is allowed, for example because the customer asked or nothing else can be done, but acting was also possible;
   - `"unsupported"`: the agent could and should have acted itself, so the transfer was not appropriate;
   - `"unresolved"`: the policy does not settle it.

   For `ASK` and `EXPECTED` points, judge whether a transfer WOULD have been required, permitted or unsupported at that point.
4. **`decision_correct`**: true, false or null. For `T`: should it have transferred? For `ASK`/`EXPECTED`: was NOT transferring correct?
5. **`reason_code`**, for `T` only: `{"chosen": "...", "applicable_under_policy": "<code> | unclear", "chosen_correct": true | false | null}`. Use doc 042's tiers and the situation as the agent could know it.
6. **`observed_mistake`**: one of `"none"`, `"transferred_instead_of_acting"`, `"failed_to_transfer"`, `"wrong_reason_code"`, `"other"`. This is WHAT went wrong at this point.
7. **`suspected_cause`**: one of `"none"`, `"missing_rule"` (the governing policy or tier document was never retrieved), `"rule_seen_misapplied"` (it was retrieved or in context, but applied wrongly), `"missing_fact"` (a needed lookup or record was not obtained), `"consent"` (customer consent was needed or missing), `"policy_ambiguous"`, `"other"`. This is WHY. Label it separately from the observed mistake; they are different levels of the same event.
8. **`outcome_after`**, from the messages after the decision point: `"transfer_receipt"`, `"failed_call"`, `"unsupported_claim"` (the agent says a transfer happened or is under way without a successful receipt), `"conversation_continued"` or `"ended"`.
9. **`notes`**: one or two sentences.

## Output

A JSON array, one object per decision point, with `"id"` plus the fields above. Write it to the file you are told to.
