# H002 failure audit: results (2026-09-30, $0)

**Method:**
- All 60 H002 conversations were exported with anonymous IDs and no configuration labels. The export is **partly blind**: the adapter's unlock turns are visible in the trajectory.
- They were labelled by three independent subagents using the fixed `CODEBOOK.md`, 20 each, then joined to the key.
- **Limits:**
  - One labeller per conversation, so there is no inter-rater agreement.
  - The export truncated tool results at 2,500 characters. Two labellers rebuilt the transaction totals from `db.json`.
  - Labels include judgement calls, recorded in each label's `notes`: C2/C3 tie-breaks, and the ambiguity over whether the Gold Rewards 0.025% bonus stacks.

## Primary category: the first failure that made success impossible

| | Baseline | v1 | v2 | Total |
|---|---|---|---|---|
| PASS | 0 | 1 | 0 | 1 |
| C1: customer request left unresolved | 0 | 0 | 1 | 1 |
| C2: missed requirement in a **retrieved** document | 9 | 3 | 4 | 16 |
| C3: requirement only in an **unretrieved** document | 7 | 10 | 7 | **24** |
| C4: wrong arguments or policy interpretation | 3 | 6 | 6 | 15 |
| C5: execution failure or truncation | 1 | 0 | 2 | 3 |
| C6: legitimately waiting on the customer | 0 | 0 | 0 | 0 |

**Which fix the labellers judged would plausibly have helped** (not mutually exclusive):

| Fix | Baseline | v1 | v2 | Total |
|---|---|---|---|---|
| Retrieving one more specific document | 12 | 15 | 14 | **41/60** |
| Argument grounding | 5 | 6 | 9 | 20/60 |
| A pre-close completion check | 6 | 3 | 5 | **14/60** |

**One document dominates the missing ones.** `doc_bank_accounts_bank_accounts_(general)_009` is missing in **16** conversations; it is the only document describing the account-lookup tool (`get_all_user_accounts_by_user_id_3847`). Then `_002` (5) and `_028`, the card lookup (4).

## Flags: violations and behaviours the implemented checks do not cover

| | Baseline | v1 | v2 |
|---|---|---|---|
| `unsafe_write` (verified, but against policy) | 1 | **4** | 1 |
| `wrong_args_write` | 3 | 4 | 3 |
| `claimed_done_without_receipt` | 2 | **8** | **12** |
| `transfer_inappropriate` | 15 | 7 | 6 |
| `denial_false` | 13 | 8 | 9 |
| `stop_appropriate` | 1 | 0 | 2 |
| `verification_weak` | 1 | 0 | 0 |

**The six unsafe writes:**

| Arm | Task | What happened |
|---|---|---|
| v1 | 069 | Opened an elite "Bluest Account"; the customer had consented only to Green or Blue |
| v1 | 069 | Opened a Platinum savings account without consent; wrong account class |
| v1 | 095 (×2) | Credited $100 of interest instead of the entitled $98: stacked a card bonus that doc `_045` says does not stack. The discrepancy reports carried the same error. The stacking reading is contested by one document |
| v2 | 041 | Filed disputes marked eligible for provisional credit beyond what the policy allows; ignored the customer's priority order |
| Baseline | 041 | Marked about 10 disputes eligible for provisional credit, against the rules in `_015` |

## Interpretation (stated with its limits)

1. **Missing documents are the most common first failure** (24/60), and the labellers judged that retrieval would help in 41/60. A completion check would help at most 14/60. **That supports ChatGPT's review: do not build the "finished?" check now.**
2. **The harness shifts failures later, not away.**
   - Missed requirements in *retrieved* documents fall: C2 9 → 3–4.
   - Wrong arguments and misread policy rise: C4 3 → 6.
   - Unsafe writes rise: 1 → 4 in v1.

   This matches the progress diagnostic: agents that stop giving up **reach consequential writes and then make the mistakes the checks don't cover** (amount entitlement, consent, account class, eligibility). So the harness **can increase unsafe writes**. With n = 20 per arm this is a signal, not an established rate.
3. **False completion claims are common in every arm**, often "I've transferred you" with no transfer call. A pattern count finds such claims in 13 baseline, 14 v1 and 6 v2 conversations. In 7 of v1's and 4 of v2's, the harness had earlier held a transfer proposal. So **a held transfer followed by a false "transferred" claim is a plausible harness side effect**. It is not established; it needs a check of each case. v2's `claims_need_receipts` does not cover transfer claims.
4. **Some failures are reasoning slips:**
   - one $358.92 transaction left out of a monthly window (3 conversations) → a wrong "you don't qualify";
   - double-counting a bonus.

   A higher reasoning setting might address these. H003 tests only whether that is plausible.
5. **One task conflicts with the documents (069).** The task assumes Gold savings has no ATM rebate; `doc_savings_accounts_gold_account_003` lists a $30/month cap. Flagged, not resolved.

## What would address the audited failures (candidates, not built)

| Candidate | Failures it targets | Evidence |
|---|---|---|
| **Tool-document retrieval.** Tools are discovered through documents. A dedicated search over the 46 documents that name tools, when the agent needs a record or an action. This is general, not specific to `_009`, and follows the tool-search pattern | The 16 conversations missing `_009`, plus `_028`, `_014` | Largest single cluster. Must be tested offline on held-out-style queries so it does not tune to dev |
| **Amount and eligibility grounding with enforcement.** The evidence checker (built) enforced on credits and eligibility flags, with recovery | 4 of the 6 unsafe writes, several C4s | Needs the stacking ambiguity settled by documents, not by us |
| **Consent before account-creating or credit writes** | The two 069 account openings | Documented policy steps |
| **Transfer-claim honesty.** Hold a reply that says "transferred" when no transfer call exists | False transfer claims | Low cost; `claims_need_receipts` extended |
