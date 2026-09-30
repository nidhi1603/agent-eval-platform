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

---

## Update after the second review (2026-09-30)

**Wording, per review.** "Retrieval would help 41/60" now reads: **the labellers identified retrieval as a candidate intervention in 41/60 conversations.** A missing document explains an information gap. It does not show that the agent would have acted correctly once it had the document. Likewise, "the harness shifts failures later" is an observation from the audit, not an established cause.

### Label agreement (`agreement.json`)

A second, independent labeller relabelled a stratified sample of 15: 5 per arm, spread over each arm's categories, with the first labels hidden.

| Measure | Agreement |
|---|---|
| Primary category | **13/15 (Cohen's κ = 0.83)** |
| `retrieval_would_help` | 12/15 (first labeller said yes 9 times, second 6) |
| `completion_check_would_help` | 12/15 |
| `argument_grounding_would_help` | 12/15 |
| `unsafe_write` flag | 15/15 |
| `claimed_done_without_receipt` flag | 13/15 |
| `transfer_inappropriate` flag | 12/15 |

Both primary-category disagreements are C2 vs C3. That is the distinction between failing to use available evidence and missing the evidence, which is the one guiding the next intervention, so **the disagreements are kept, not merged away.** The "would help" counts are soft and should be read as rough.

### Unsafe writes, adjudicated (`unsafe_adjudication.json`)

All six flagged conversations were adjudicated against policy, consent and tool effects: 25 successful writes, of which 12 are violations, 1 ambiguous and 12 fine. **Report actions and conversations separately:**

| | Baseline | v1 | v2 |
|---|---|---|---|
| Conversations with at least one violation | 1 | **3** | 1 |
| Violating write actions | **8** | 3 | 1 |
| Ambiguous actions (document conflict) | 0 | 1 | 0 |

**Baseline:** 8 disputes flagged for provisional credit beyond the `_015` prior-dispute limit, $2,657.11 unentitled, in one conversation (task_041).

**v1:**
- 069: an elite account opened when the customer authorised only Green or Blue;
- 069: a savings account opened on consent whose condition was unanswered (and false);
- 095: a credit applied before the required transaction-history review.

The $100-vs-$98 credit is **ambiguous**: docs `gold_013` and `_045` conflict.

**v2:** 041, a provisional-credit flag over the limit.

**Consent:** only account opening has an explicit confirmation rule in the documents. No blanket consent requirement is implied.

**Correction:** the earlier "unsafe writes 1 → 4 (v1)" was a flag count. After adjudication, v1 has violations in more conversations (3 vs 1), and the baseline has more violating actions (8 vs 3). **The baseline's 8 are one conversation:** a serious failure example, not eight independent observations. **No reliable safety comparison is established.** Only flagged conversations were adjudicated, and absence of evidence is not equivalence.

### Transfers, reconciled (`transfer_reconciliation.json`)

| | Baseline | v1 | v2 |
|---|---|---|---|
| Executed transfer calls (the earlier "13/5/1") | 13 | 5 | 1 |
| Transfer proposals held by the harness | 0 | 9 | 17 |
| Conversations claiming a transfer with no transfer call | 1 | 6 | 3 |
| …of which the harness had held a transfer earlier | – | 6/6 | 3/3 |
| Audit `transfer_inappropriate` (the "15/7/6") | 15 | 7 | 6 |
| = executed transfers | 13 | 5 | 1 |
| + offered or claimed without a call | 2 | 2 | 5 |

The two counts differ because the audit flag also covers transfers that were offered or claimed but not executed. **In every harness conversation with a false "transferred" claim (9 of 9), the harness had held a transfer before it. In the baseline there is 1 such conversation.** This is a strong association, and a plausible side effect of holding transfers; it is not a controlled result.

### Offline tool-document retrieval probe (`../tool_retrieval_probe.py`, `tool_retrieval_probe.json`)

**Setup** (fixed before looking at results):
- Index: the 45 documents whose public text names a registry tool;
- BM25, top 3;
- queries only from what was visible at that point in the conversation;
- 54 of the 60 H002 conversations have a relevant tool document.

| Query source | Recall of needed tool documents (by end) | Irrelevant documents per conversation | Added tokens per conversation |
|---|---|---|---|
| The agent's own searches over the full knowledge base (actual) | 0.39 | 5.1 | – |
| The customer's latest message | 0.37 | 8.9 | 5,432 |
| All customer messages so far | 0.22 | 3.6 | 2,302 |
| The agent's queries on the tool index | 0.30 | 4.0 | 1,453 |
| The agent asking the customer for an identifier | 0.23 | 2.7 | 1,598 |
| **Dependency following** (identifier inputs of tools named in retrieved documents → search for what provides them) | 0.19 | 3.3 | 1,947 |
| Agent + customer messages | 0.44 | | |
| **Agent + dependency following** | **0.52** | | |

- **Queries from customer messages do not help.** The account-lookup document (`_009`, needed in 48 conversations) is never found from the customer's words: customers don't ask for lookups.
- **Dependency following is general:** static tool schemas plus documents the agent actually saw. It surfaces the transaction-history tool document (30/30 where needed; the agent found it in 1) and the card-lookup document (24/24; the agent in 20).
- **It still misses `_009` (0/48).** That document is short and generic, and does not rank in the top 3 for "account id". **Deliberately not tuned:** the method was fixed before results, and we will not adjust it to hit one document.
- **This shows evidence *availability* only, not recovered task success.**

### Data issue

`DATA_NOTE_task_069.md`: the task says Gold savings has no ATM rebate, but `doc_savings_accounts_gold_account_003` lists a $30/month cap. Results are preserved; the issue is unresolved.
